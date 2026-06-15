"""
资金流实盘复盘脚本 — 数据获取层
==================================
封装所有 akshare 数据调用，统一异常处理和重试逻辑。
push2.eastmoney.com 在 GitHub Actions 上被封时，自动切换备用源：
  1. push2 CDN 节点直连（86/1/2 等）
  2. datacenter-web.eastmoney.com API
"""

import time
import logging
import urllib.request
import urllib.parse
import json
import os
from datetime import datetime, timedelta

import pandas as pd

# Python 3.13 兼容补丁
try:
    import pkgutil
    if not hasattr(pkgutil, 'ImpImporter'):
        pkgutil.ImpImporter = type('ImpImporter', (), {})
except Exception:
    pass

import akshare as ak

log = logging.getLogger("shuangxian")


def _safe_float(val, default=0.0):
    """安全转换浮点数，处理 push2 返回的 '-' 等非数值"""
    try:
        if val == '-' or val is None or val == '':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _retry(func, retries=3, delay=2, **kwargs):
    """带重试的通用调用包装"""
    for i in range(retries):
        try:
            return func(**kwargs)
        except Exception as e:
            if i < retries - 1:
                log.warning(f"[重试 {i+1}/{retries}] {func.__name__} 失败: {e}")
                time.sleep(delay)
            else:
                log.error(f"[放弃] {func.__name__} 最终失败: {e}")
                raise


# ── push2 备用源：多CDN节点直连 ──────────────────────────

def _fallback_push2_clist(fs_param: str, fields: str, page_size: int = 200) -> list:
    """
    备用源1：直接请求东方财富 push2 API，尝试多个 CDN 节点。
    GitHub Actions IP 被 push2 主域封禁时，CDN 子节点可能绕过。
    """
    cdn_nodes = ['86', '1', '2', '56', 'push2ex']
    base_template = "https://{}.push2.eastmoney.com/api/qt/clist/get"
    params = f"?pn=1&pz={page_size}&po=1&np=1&fltt=2&invt=2&fid=f62&fs={fs_param}&fields={fields}"

    for node in cdn_nodes:
        url = base_template.format(node) + params
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Referer': 'https://data.eastmoney.com/',
        })
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            raw = resp.read().decode('utf-8')
            data = json.loads(raw)
            if data.get('data') and data['data'].get('diff'):
                log.info(f"  push2备用源成功 (CDN: {node})")
                return data['data']['diff']
        except Exception as e:
            log.debug(f"  push2 CDN {node} 失败: {e}")
            continue

    return []


# ── datacenter-web 备用源 ──────────────────────────────

def _fallback_datacenter_web(report_name: str, sort_col: str = 'NET_INFLOW_AMT',
                              page_size: int = 200) -> list:
    """
    备用源2：请求 datacenter-web.eastmoney.com API。
    这是东方财富数据中心网站的后端 API，IP 限制较宽松。
    """
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = urllib.parse.urlencode({
        'sortColumns': sort_col,
        'sortTypes': '-1',
        'pageSize': str(page_size),
        'pageNumber': '1',
        'reportName': report_name,
        'columns': 'ALL',
        'source': 'WEB',
        'client': 'WEB',
    })
    full_url = f"{url}?{params}"

    req = urllib.request.Request(full_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode('utf-8'))
        if data.get('result') and data['result'].get('data'):
            log.info(f"  datacenter-web备用源成功 (report: {report_name})")
            return data['result']['data']
    except Exception as e:
        log.debug(f"  datacenter-web 失败: {e}")

    return []


# ── 板块资金流（含备用源） ──────────────────────────────

def get_sector_fund_flow(indicator: str = "今日") -> pd.DataFrame:
    """
    板块资金流排名。
    主源：akshare → 备用源1：push2 CDN直连 → 备用源2：datacenter-web
    """
    # 主源：akshare
    try:
        df = _retry(ak.stock_sector_fund_flow_rank, indicator=indicator, sector_type="行业资金流")
        if df is not None and not df.empty:
            return df
    except Exception as e:
        log.warning(f"板块资金流 akshare主源失败: {e}")

    # 备用源1：push2 CDN 直连
    log.info("  尝试板块资金流备用源1 (push2直连)...")
    fs_param = "m:90+t:2"  # 行业板块
    fields = "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124,f1,f13"
    raw = _fallback_push2_clist(fs_param, fields)
    if raw:
        df = _build_sector_df_from_push2(raw)
        if not df.empty:
            return df

    # 备用源2：datacenter-web
    log.info("  尝试板块资金流备用源2 (datacenter-web)...")
    raw2 = _fallback_datacenter_web('RPT_INDUSTRY_BOARD_MONEY_FLOW')
    if raw2:
        df = _build_sector_df_from_datacenter(raw2)
        if not df.empty:
            return df

    log.warning("板块资金流所有源均失败，返回空数据")
    return pd.DataFrame()


def _build_sector_df_from_push2(raw: list) -> pd.DataFrame:
    """将 push2 原始数据转为 DataFrame，列名兼容 akshare 格式"""
    rows = []
    for item in raw:
        try:
            net_inflow = _safe_float(item.get('f62', 0))
            rows.append({
                '名称': str(item.get('f14', '')),
                '涨跌幅': _safe_float(item.get('f3', 0)),
                '主力净流入-净额': net_inflow,
                '主力净流入-净占比': _safe_float(item.get('f184', 0)),
                '超大单净流入-净额': _safe_float(item.get('f66', 0)),
                '超大单净流入-净占比': _safe_float(item.get('f69', 0)),
                '大单净流入-净额': _safe_float(item.get('f72', 0)),
                '大单净流入-净占比': _safe_float(item.get('f75', 0)),
                '中单净流入-净额': _safe_float(item.get('f78', 0)),
                '中单净流入-净占比': _safe_float(item.get('f81', 0)),
                '小单净流入-净额': _safe_float(item.get('f84', 0)),
                '小单净流入-净占比': _safe_float(item.get('f87', 0)),
                '换手率': _safe_float(item.get('f124', 0)),
            })
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if not df.empty:
        log.info(f"  push2板块数据: {len(df)} 个板块")
    return df


def _build_sector_df_from_datacenter(raw: list) -> pd.DataFrame:
    """将 datacenter-web 原始数据转为 DataFrame，列名兼容 akshare 格式"""
    rows = []
    for item in raw:
        try:
            name = item.get('BOARD_NAME', '') or item.get('SECURITY_NAME_ABBR', '') or ''
            net_inflow = _safe_float(item.get('NET_INFLOW_AMT', 0))
            change_rate = _safe_float(item.get('CHANGE_RATE', 0))
            net_inflow_rate = _safe_float(item.get('NET_INFLOW_RATE', 0))
            turnover = _safe_float(item.get('TURNOVER_RATE', 0))
            if not name:
                continue
            rows.append({
                '名称': name,
                '涨跌幅': change_rate,
                '主力净流入-净额': net_inflow,
                '主力净流入-净占比': net_inflow_rate,
                '换手率': turnover,
            })
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if not df.empty:
        log.info(f"  datacenter板块数据: {len(df)} 个板块")
    return df


# ── 个股资金流（含备用源） ──────────────────────────────

def get_individual_fund_flow_rank(indicator: str = "今日") -> pd.DataFrame:
    """
    个股资金流排名。
    主源：akshare → 备用源1：push2 CDN直连 → 备用源2：datacenter-web
    """
    # 主源：akshare
    try:
        df = _retry(ak.stock_individual_fund_flow_rank, indicator=indicator)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        log.warning(f"个股资金流 akshare主源失败: {e}")

    # 备用源1：push2 CDN 直连
    log.info("  尝试个股资金流备用源1 (push2直连)...")
    fs_param = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"  # A股
    fields = "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124,f152,f173,f170,f171,f1,f13"
    raw = _fallback_push2_clist(fs_param, fields, page_size=200)
    if raw:
        df = _build_individual_df_from_push2(raw)
        if not df.empty:
            return df

    # 备用源2：datacenter-web
    log.info("  尝试个股资金流备用源2 (datacenter-web)...")
    raw2 = _fallback_datacenter_web('RPT_STOCK_BOARD_MONEY_FLOW', page_size=200)
    if raw2:
        df = _build_individual_df_from_datacenter(raw2)
        if not df.empty:
            return df

    log.warning("个股资金流所有源均失败，返回空数据")
    return pd.DataFrame()


def _build_individual_df_from_push2(raw: list) -> pd.DataFrame:
    """将 push2 个股原始数据转为 DataFrame，列名兼容 akshare 格式"""
    rows = []
    for item in raw:
        try:
            code = str(item.get('f12', ''))
            name = str(item.get('f14', ''))
            if not code or not name:
                continue
            net_inflow = _safe_float(item.get('f62', 0))
            rows.append({
                '代码': code,
                '名称': name,
                '涨跌幅': _safe_float(item.get('f3', 0)),
                '主力净流入-净额': net_inflow,
                '主力净流入-净占比': _safe_float(item.get('f184', 0)),
                '超大单净流入-净额': _safe_float(item.get('f66', 0)),
                '超大单净流入-净占比': _safe_float(item.get('f69', 0)),
                '大单净流入-净额': _safe_float(item.get('f72', 0)),
                '大单净流入-净占比': _safe_float(item.get('f75', 0)),
                '中单净流入-净额': _safe_float(item.get('f78', 0)),
                '中单净流入-净占比': _safe_float(item.get('f81', 0)),
                '小单净流入-净额': _safe_float(item.get('f84', 0)),
                '小单净流入-净占比': _safe_float(item.get('f87', 0)),
                '换手率': _safe_float(item.get('f124', 0)),
                '流通市值': _safe_float(item.get('f152', 0)),
                '成交额': _safe_float(item.get('f173', 0)),
                '5日主力净流入-净额': _safe_float(item.get('f170', 0)),
                '10日主力净流入-净额': _safe_float(item.get('f171', 0)),
            })
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if not df.empty:
        log.info(f"  push2个股数据: {len(df)} 只股票")
    return df


def _build_individual_df_from_datacenter(raw: list) -> pd.DataFrame:
    """将 datacenter-web 个股原始数据转为 DataFrame，列名兼容 akshare 格式"""
    rows = []
    for item in raw:
        try:
            code = str(item.get('SECURITY_CODE', '') or item.get('CODE', ''))
            name = str(item.get('SECURITY_NAME_ABBR', '') or item.get('NAME', ''))
            if not code or not name:
                continue
            net_inflow = _safe_float(item.get('NET_INFLOW_AMT', 0))
            rows.append({
                '代码': code,
                '名称': name,
                '涨跌幅': _safe_float(item.get('CHANGE_RATE', 0)),
                '主力净流入-净额': net_inflow,
                '主力净流入-净占比': _safe_float(item.get('NET_INFLOW_RATE', 0)),
                '成交额': _safe_float(item.get('TRADE_AMOUNT', 0)),
                '流通市值': _safe_float(item.get('FREE_MARKET_CAP', 0)),
                '换手率': _safe_float(item.get('TURNOVER_RATE', 0)),
            })
        except Exception:
            continue
    df = pd.DataFrame(rows)
    if not df.empty:
        log.info(f"  datacenter个股数据: {len(df)} 只股票")
    return df


# ── 以下为原有函数，无修改 ──────────────────────────────

def get_index_daily(symbol: str, days: int = 30) -> pd.DataFrame:
    df = _retry(ak.stock_zh_index_daily, symbol=symbol)
    df = df.rename(columns={
        'date': '日期', 'open': '开盘', 'high': '最高',
        'low': '最低', 'close': '收盘', 'volume': '成交量'
    })
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期').tail(days).reset_index(drop=True)
    return df


def get_market_turnover() -> dict:
    sh = get_index_daily('sh000001', days=25)
    sz = get_index_daily('sz399001', days=25)
    sh_amount = sh['成交量'].astype(float)
    sz_amount = sz['成交量'].astype(float)
    merged = pd.merge(sh[['日期', '成交量']], sz[['日期', '成交量']],
                       on='日期', suffixes=('_sh', '_sz'))
    merged['总成交额'] = merged['成交量_sh'].astype(float) + merged['成交量_sz'].astype(float)
    merged = merged.sort_values('日期').reset_index(drop=True)
    today_amount = float(merged.iloc[-1]['总成交额'])
    avg20_amount = float(merged.tail(20)['总成交额'].mean())
    return {
        'today_amount': today_amount,
        'avg20_amount': avg20_amount,
        'amount_ratio': today_amount / avg20_amount if avg20_amount > 0 else 0,
    }


def get_three_indices(days: int = 5) -> pd.DataFrame:
    sh = get_index_daily('sh000001', days=days)
    sz = get_index_daily('sz399001', days=days)
    try:
        qa = get_index_daily('sh000985', days=days)
    except Exception:
        qa = sh.copy()
    result = pd.DataFrame()
    result['日期'] = sh['日期'].values
    result['上证收盘'] = sh['收盘'].astype(float).values
    result['上证涨跌'] = sh['收盘'].astype(float).pct_change().fillna(0).values
    result['深证收盘'] = sz['收盘'].astype(float).values
    result['深证涨跌'] = sz['收盘'].astype(float).pct_change().fillna(0).values
    result['全A替代收盘'] = qa['收盘'].astype(float).values
    result['全A替代涨跌'] = qa['收盘'].astype(float).pct_change().fillna(0).values
    return result


def get_etf_scale_changes(days: int = 25) -> pd.DataFrame:
    try:
        df = _retry(ak.fund_etf_scale_sse)
        df = df.rename(columns={
            '基金代码': 'code', '基金简称': 'name',
            'ETF类型': 'type', '统计日期': 'date', '基金份额': 'shares'
        })
        return df
    except Exception as e:
        log.warning(f"ETF份额数据获取失败: {e}")
        return pd.DataFrame()


def get_sector_fund_flow_hist(sector_name: str, days: int = 30) -> pd.DataFrame:
    try:
        df = _retry(ak.stock_sector_fund_flow_hist, symbol=sector_name)
        if df is not None and len(df) > 0:
            return df.tail(days)
        return pd.DataFrame()
    except Exception as e:
        log.warning(f"行业'{sector_name}'资金流历史获取失败: {e}")
        return pd.DataFrame()


def get_individual_fund_flow(symbol: str, market: str = "sh") -> pd.DataFrame:
    try:
        df = _retry(ak.stock_individual_fund_flow, stock=symbol, market=market)
        return df
    except Exception as e:
        log.warning(f"个股'{symbol}'资金流获取失败: {e}")
        return pd.DataFrame()


def get_margin_sh(days: int = 30) -> pd.DataFrame:
    try:
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=days+10)).strftime('%Y%m%d')
        df = _retry(ak.stock_margin_sse, start_date=start, end_date=end)
        return df
    except Exception as e:
        log.warning(f"上海融资融券获取失败: {e}")
        return pd.DataFrame()


def get_margin_sz(date_str: str = None) -> pd.DataFrame:
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    try:
        df = _retry(ak.stock_margin_szse, date=date_str)
        return df
    except Exception as e:
        log.warning(f"深圳融资融券获取失败: {e}")
        return pd.DataFrame()


def get_north_flow(symbol: str = "沪股通", days: int = 30) -> pd.DataFrame:
    try:
        df = _retry(ak.stock_hsgt_hist_em, symbol=symbol)
        if df is not None and len(df) > 0:
            return df.tail(days)
        return pd.DataFrame()
    except Exception as e:
        log.warning(f"北向资金获取失败: {e}")
        return pd.DataFrame()


def get_stock_zh_a_daily(symbol: str, days: int = 30) -> pd.DataFrame:
    df = _retry(ak.stock_zh_a_daily, symbol=symbol, adjust="")
    if df is not None and len(df) > 0:
        return df.tail(days)
    return pd.DataFrame()


def get_stock_list() -> pd.DataFrame:
    try:
        df = _retry(ak.stock_zh_a_spot_em)
        return df
    except Exception:
        pass
    log.warning("A股列表获取失败，六层滤网功能受限")
    return pd.DataFrame()


def get_sina_realtime(codes: list) -> dict:
    import urllib.request
    proxy_handler = urllib.request.ProxyHandler({
        'http': os.environ.get('HTTP_PROXY', ''),
        'https': os.environ.get('HTTPS_PROXY', '')
    })
    opener = urllib.request.build_opener(proxy_handler)
    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://finance.sina.com.cn'
    })
    try:
        resp = opener.open(req, timeout=10)
        raw = resp.read().decode('gbk')
    except Exception as e:
        log.warning(f"Sina实时行情获取失败: {e}")
        return {}
    result = {}
    for line in raw.strip().split('\n'):
        if '=' not in line:
            continue
        var_part, data_part = line.split('=', 1)
        code = var_part.split('_')[-1].strip('"')
        data_str = data_part.strip().strip('";')
        if not data_str:
            continue
        fields = data_str.split(',')
        if len(fields) >= 32:
            result[code] = {
                'name': fields[0],
                'open': float(fields[1]) if fields[1] else 0,
                'prev_close': float(fields[2]) if fields[2] else 0,
                'close': float(fields[3]) if fields[3] else 0,
                'high': float(fields[4]) if fields[4] else 0,
                'low': float(fields[5]) if fields[5] else 0,
                'volume': float(fields[8]) if fields[8] else 0,
                'amount': float(fields[9]) if fields[9] else 0,
                'date': fields[30],
                'time': fields[31],
            }
    return result
