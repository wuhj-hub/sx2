"""
双弦投资系统 v2.0 — 数据获取层
==================================
Sina财经为主数据源（GitHub Actions稳定可用）
akshare/push2/datacenter-web/Tushare为备用降级链路
逻辑链数据(Sina K线) + 资金流数据(Sina板块/个股)
"""

import time
import logging
import urllib.request
import urllib.parse
import json
import os
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# Python 3.13 兼容补丁
try:
    import pkgutil
    if not hasattr(pkgutil, 'ImpImporter'):
        pkgutil.ImpImporter = type('ImpImporter', (), {})
except Exception:
    pass

import akshare as ak

import config

log = logging.getLogger("shuangxian")


# ── 工具函数 ──────────────────────────────────────────────

def _safe_float(val, default=0.0):
    try:
        if val == '-' or val is None or val == '':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _retry(func, retries=3, delay=2, **kwargs):
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


def _sina_request(url, timeout=15):
    """通用Sina请求，带超时和重试"""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://finance.sina.com.cn/',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode('utf-8')
    except Exception as e:
        log.debug(f"Sina请求失败: {url[:80]}... → {e}")
        return None


# ════════════════════════════════════════════════════════
#  逻辑链弦：K线数据（Sina为主）
# ════════════════════════════════════════════════════════

def get_sina_kline(symbol: str, scale: int = 240, datalen: int = 1500) -> pd.DataFrame:
    """
    Sina财经K线数据
    scale: 240=日线, 60=60分钟
    symbol: sh000300, sz300750, sh600519 等
    """
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/=/"
           f"CN_MarketDataService.getKLineData?"
           f"symbol={symbol}&scale={scale}&datalen={datalen}")
    raw = _sina_request(url)
    if not raw:
        return pd.DataFrame()
    try:
        # jsonp格式: /*<script>...</script>*/=([...]);
        # 提取 [] 之间的JSON数组
        start = raw.index('[')
        end = raw.rindex(']') + 1
        data = json.loads(raw[start:end])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        for c in ['open', 'high', 'low', 'close', 'volume']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        if 'day' in df.columns:
            df['day'] = pd.to_datetime(df['day'])
        df = df.sort_values('day').reset_index(drop=True)
        return df
    except Exception as e:
        log.warning(f"Sina K线解析失败 {symbol}: {e}")
        return pd.DataFrame()


def get_sina_realtime_batch(codes: list) -> dict:
    """
    批量获取Sina实时行情
    codes: ['sh600519', 'sz300750', ...]
    返回: {code: {name, close, pct_change, volume, amount, ...}}
    """
    result = {}
    # Sina hq.sinajs.cn 一次最多约800只
    batch_size = 200
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        url = f"https://hq.sinajs.cn/list={','.join(batch)}"
        raw = _sina_request(url)
        if not raw:
            continue
        try:
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
                    prev_close = float(fields[2]) if fields[2] else 0
                    close = float(fields[3]) if fields[3] else 0
                    pct_change = ((close - prev_close) / prev_close * 100) if prev_close else 0
                    result[code] = {
                        'name': fields[0],
                        'open': float(fields[1]) if fields[1] else 0,
                        'prev_close': prev_close,
                        'close': close,
                        'high': float(fields[4]) if fields[4] else 0,
                        'low': float(fields[5]) if fields[5] else 0,
                        'volume': float(fields[8]) if fields[8] else 0,
                        'amount': float(fields[9]) if fields[9] else 0,
                        'pct_change': pct_change,
                        'date': fields[30],
                        'time': fields[31],
                    }
        except Exception as e:
            log.debug(f"Sina实时行情解析失败: {e}")
    return result


def get_stock_pool() -> list:
    """
    获取股票池：沪深300 + 中证500 + 中证1000
    返回: [{'symbol': 'sh600519', 'code': '600519', 'name': '贵州茅台', 'pool': 'hs300'}, ...]
    """
    stocks = []
    # 用akshare获取成分股
    for idx_code, pool_name in [("000300", "hs300"), ("000905", "zz500"), ("000852", "zz1000")]:
        try:
            df = _retry(ak.index_stock_cons_csindex, symbol=idx_code)
            if df is not None and not df.empty:
                # 列名: 日期, 指数代码, 指数名称, 指数英文名称, 成分券代码, 成分券名称, ...
                code_col = '成分券代码' if '成分券代码' in df.columns else df.columns[4]
                name_col = '成分券名称' if '成分券名称' in df.columns else df.columns[5]
                for _, row in df.iterrows():
                    code = str(row[code_col]).zfill(6)
                    name = str(row[name_col])
                    prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0','3')) else 'bj')
                    stocks.append({
                        'symbol': f'{prefix}{code}',
                        'code': code,
                        'name': name,
                        'pool': pool_name,
                    })
                log.info(f"  {pool_name}({idx_code}): {len(df)}只")
        except Exception as e:
            log.warning(f"  {pool_name}({idx_code})获取失败: {e}")
    
    # 去重(保留最小池的标记，hs300优先)
    seen = {}
    pool_priority = {'hs300': 0, 'zz500': 1, 'zz1000': 2}
    for s in stocks:
        code = s['code']
        if code not in seen or pool_priority.get(s['pool'], 9) < pool_priority.get(seen[code]['pool'], 9):
            seen[code] = s
    result = list(seen.values())
    log.info(f"  股票池总计: {len(result)}只(去重后)")
    return result


def get_industry_constituents() -> dict:
    """
    获取行业板块成分股 → {行业名: [symbol1, symbol2, ...]}
    同时返回反向映射 → 存入 industry_map.json
    
    优先使用 akshare 东方财富行业板块接口（更稳定），
    失败时降级到 Sina 申万行业节点
    """
    industry_map = {}   # symbol → industry_name (key格式: sh600519)
    industry_stocks = {}  # industry_name → [symbols]
    
    # ── 主源：akshare 东方财富行业板块 ──────────────────
    try:
        log.info("  获取行业分类(akshare东方财富)...")
        # 获取所有行业板块名称
        board_df = _retry(ak.stock_board_industry_name_em)
        if board_df is not None and not board_df.empty:
            # 申万一级行业（31个）— 排除概念板块
            sw_industries = [
                '钢铁', '采掘', '化工', '有色金属', '建筑材料', '建筑装饰',
                '电气设备', '机械设备', '国防军工', '汽车', '家用电器',
                '轻工制造', '食品饮料', '纺织服装', '医药生物', '农林牧渔',
                '商贸零售', '社会服务', '银行', '非银金融', '房地产',
                '交通运输', '电子', '计算机', '通信', '传媒', '公用事业',
                '环保', '综合', '煤炭', '石油石化',
            ]
            matched = 0
            for ind_name in sw_industries:
                try:
                    cons_df = _retry(ak.stock_board_industry_cons_em, symbol=ind_name)
                    if cons_df is not None and not cons_df.empty:
                        code_col = next((c for c in cons_df.columns if '代码' in c), None)
                        if code_col:
                            symbols = []
                            for code in cons_df[code_col].astype(str):
                                code = code.zfill(6)
                                prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0','3')) else 'bj')
                                sym = f'{prefix}{code}'
                                symbols.append(sym)
                                industry_map[sym] = ind_name
                            industry_stocks[ind_name] = symbols
                            matched += 1
                            log.info(f"  行业 {ind_name}: {len(symbols)}只")
                except Exception as e:
                    log.debug(f"  行业 {ind_name} 获取失败: {e}")
            
            if matched >= 10:
                log.info(f"  行业映射(akshare): {len(industry_map)}只股票, {matched}个行业")
                return industry_map, industry_stocks
            else:
                log.warning(f"  akshare行业映射仅{matched}个行业，降级Sina")
    except Exception as e:
        log.warning(f"  akshare行业板块获取失败: {e}，降级Sina")
    
    # ── 降级：Sina 申万行业板块节点 ──────────────────
    log.info("  降级获取行业分类(Sina)...")
    industry_nodes = [
        ('sw_gt', '钢铁'), ('sw_jtys', '交通运输'), ('sw_gcls', '建筑装饰'),
        ('sw_jsj', '计算机'), ('sw_dz', '电子'), ('sw_yx', '银行'),
        ('sw_fdc', '房地产'), ('sw_yl', '医药生物'), ('sw_jx', '机械设备'),
        ('sw_qc', '汽车'), ('sw_sy', '商贸零售'), ('sw_hg', '化工'),
        ('sw_jz', '建筑'), ('sw_dy', '公用事业'), ('sw_ny', '石油石化'),
        ('sw_jr', '非银金融'), ('sw_sp', '食品饮料'), ('sw_jj', '家用电器'),
        ('sw_mt', '煤炭'), ('sw_youse', '有色金属'), ('sw_gf', '国防军工'),
        ('sw_nlm', '农林牧渔'), ('sw_zh', '综合'),
    ]
    
    for node, ind_name in industry_nodes:
        page = 1
        symbols = []
        while True:
            url = (f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   f"Market_Center.getHQNodeData?page={page}&num=200&sort=amount&asc=0&node={node}")
            raw = _sina_request(url)
            if not raw:
                break
            try:
                data = json.loads(raw)
                if not data:
                    break
                for item in data:
                    code = str(item.get('code', '')).zfill(6)
                    if code:
                        prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0','3')) else 'bj')
                        sym = f'{prefix}{code}'
                        symbols.append(sym)
                        industry_map[sym] = ind_name
                if len(data) < 200:
                    break
                page += 1
            except Exception:
                break
        
        if symbols:
            industry_stocks[ind_name] = symbols
            log.info(f"  行业 {ind_name}(Sina): {len(symbols)}只")
    
    log.info(f"  行业映射(Sina): {len(industry_map)}只股票, {len(industry_stocks)}个行业")
    return industry_map, industry_stocks


# ════════════════════════════════════════════════════════
#  资金流弦：板块/个股资金流（复用v1.4降级链路）
# ════════════════════════════════════════════════════════

# ── push2 备用源 ──────────────────────────────────────

def _fallback_push2_clist(fs_param: str, fields: str, page_size: int = 200) -> list:
    cdn_nodes = ['86', '1', '2', '56', 'push2ex']
    base_template = "https://{}.push2.eastmoney.com/api/qt/clist/get"
    params = f"?pn=1&pz={page_size}&po=1&np=1&fltt=2&invt=2&fid=f62&fs={fs_param}&fields={fields}"
    for node in cdn_nodes:
        url = base_template.format(node) + params
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://data.eastmoney.com/',
        })
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('data') and data['data'].get('diff'):
                log.info(f"  push2备用源成功 (CDN: {node})")
                return data['data']['diff']
        except Exception:
            continue
    return []


def _fallback_datacenter_web(report_name: str, sort_col: str = 'NET_INFLOW_AMT',
                              page_size: int = 200) -> list:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = urllib.parse.urlencode({
        'sortColumns': sort_col, 'sortTypes': '-1',
        'pageSize': str(page_size), 'pageNumber': '1',
        'reportName': report_name, 'columns': 'ALL',
        'source': 'WEB', 'client': 'WEB',
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
            log.info(f"  datacenter-web备用源成功")
            return data['result']['data']
    except Exception:
        pass
    return []


# ── Sina板块资金流（主源） ────────────────────────────

def get_sector_fund_flow(indicator: str = "今日") -> pd.DataFrame:
    """板块资金流排名，Sina为主源"""
    # 先试Sina
    results = []
    for fenlei in ['0', '1']:  # 0=行业, 1=概念
        url = (f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"MoneyFlow.ssl_bkzj_bk?page=1&num=100&sort=netamount&asc=0&fenlei={fenlei}")
        raw = _sina_request(url)
        if raw:
            try:
                data = json.loads(raw)
                if data:
                    results.extend(data)
            except Exception:
                pass
    
    if results:
        rows = []
        for item in results:
            name = str(item.get('name', ''))
            if not name:
                continue
            net_inflow = _safe_float(item.get('netamount', 0))
            change_pct = _safe_float(item.get('avg_changeratio', 0)) * 100
            net_inflow_pct = _safe_float(item.get('ratioamount', 0)) * 100
            turnover = _safe_float(item.get('turnover', 0))
            rows.append({
                '名称': name, '涨跌幅': change_pct,
                '主力净流入-净额': net_inflow, '主力净流入-净占比': net_inflow_pct,
                '换手率': turnover,
            })
        df = pd.DataFrame(rows).sort_values('主力净流入-净额', ascending=False).reset_index(drop=True)
        log.info(f"  Sina板块资金流: {len(df)}个板块")
        return df
    
    # 降级到push2
    log.info("  Sina板块资金流失败，降级push2...")
    fs_param = "m:90+t:2"
    fields = "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124"
    raw = _fallback_push2_clist(fs_param, fields)
    if raw:
        rows = []
        for item in raw:
            try:
                rows.append({
                    '名称': str(item.get('f14', '')),
                    '涨跌幅': _safe_float(item.get('f3', 0)),
                    '主力净流入-净额': _safe_float(item.get('f62', 0)),
                    '主力净流入-净占比': _safe_float(item.get('f184', 0)),
                    '换手率': _safe_float(item.get('f124', 0)),
                })
            except Exception:
                continue
        if rows:
            return pd.DataFrame(rows)
    
    # 降级到datacenter-web
    log.info("  push2失败，降级datacenter-web...")
    raw2 = _fallback_datacenter_web('RPT_INDUSTRY_BOARD_MONEY_FLOW')
    if raw2:
        rows = []
        for item in raw2:
            name = item.get('BOARD_NAME', '') or item.get('SECURITY_NAME_ABBR', '')
            if not name:
                continue
            rows.append({
                '名称': name,
                '涨跌幅': _safe_float(item.get('CHANGE_RATE', 0)),
                '主力净流入-净额': _safe_float(item.get('NET_INFLOW_AMT', 0)),
                '主力净流入-净占比': _safe_float(item.get('NET_INFLOW_RATE', 0)),
                '换手率': _safe_float(item.get('TURNOVER_RATE', 0)),
            })
        if rows:
            return pd.DataFrame(rows)
    
    log.warning("板块资金流所有源均失败")
    return pd.DataFrame()


# ── 个股资金流 ────────────────────────────────────────

def get_individual_fund_flow_rank(indicator: str = "今日") -> pd.DataFrame:
    """个股资金流排名，多源降级"""
    # 主源：akshare
    try:
        df = _retry(ak.stock_individual_fund_flow_rank, indicator=indicator)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        log.warning(f"个股资金流akshare主源失败: {e}")

    # 降级1：push2 CDN
    log.info("  尝试个股资金流备用源1 (push2直连)...")
    fs_param = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    fields = "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124,f152,f173"
    raw = _fallback_push2_clist(fs_param, fields, page_size=200)
    if raw:
        rows = []
        for item in raw:
            code = str(item.get('f12', ''))
            name = str(item.get('f14', ''))
            if not code or not name:
                continue
            rows.append({
                '代码': code, '名称': name,
                '涨跌幅': _safe_float(item.get('f3', 0)),
                '主力净流入-净额': _safe_float(item.get('f62', 0)),
                '主力净流入-净占比': _safe_float(item.get('f184', 0)),
                '换手率': _safe_float(item.get('f124', 0)),
                '流通市值': _safe_float(item.get('f152', 0)),
                '成交额': _safe_float(item.get('f173', 0)),
            })
        if rows:
            return pd.DataFrame(rows)

    # 降级2：Tushare
    log.info("  尝试个股资金流备用源2 (Tushare)...")
    token = os.environ.get("TUSHARE_TOKEN", "") or config.TUSHARE_TOKEN
    if token:
        trade_date = datetime.now().strftime('%Y%m%d')
        url = "https://api.tushare.pro"
        payload = json.dumps({
            "api_name": "moneyflow", "token": token,
            "params": {"trade_date": trade_date}
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('data') and result['data'].get('items'):
                fields_t = result['data']['fields']
                items = result['data']['items']
                rows = []
                for item in items:
                    rd = dict(zip(fields_t, item))
                    ts_code = str(rd.get('ts_code', ''))
                    code = ts_code.split('.')[0] if '.' in ts_code else ts_code
                    net_mf = _safe_float(rd.get('net_mf_amount', 0))
                    rows.append({
                        '代码': code, '名称': '',
                        '涨跌幅': 0, '主力净流入-净额': net_mf * 10000,
                        '主力净流入-净占比': 0,
                    })
                if rows:
                    df = pd.DataFrame(rows).sort_values('主力净流入-净额', ascending=False)
                    log.info(f"  Tushare个股: {len(df)}只")
                    return df
        except Exception as e:
            log.debug(f"  Tushare失败: {e}")

    log.warning("个股资金流所有源均失败")
    return pd.DataFrame()


# ── 指数/市场数据 ─────────────────────────────────────

def get_index_daily(symbol: str = "sh000001", days: int = 30) -> pd.DataFrame:
    """指数日线，Sina K线"""
    df = get_sina_kline(symbol, scale=240, datalen=days+50)
    if df.empty:
        # 降级akshare
        try:
            df = _retry(ak.stock_zh_index_daily, symbol=symbol)
            df = df.rename(columns={
                'date': 'day', 'open': '开盘', 'high': '最高',
                'low': '最低', 'close': '收盘', 'volume': '成交量'
            })
            df['day'] = pd.to_datetime(df['day'])
        except Exception:
            return pd.DataFrame()
    if df.empty:
        return df
    df = df.sort_values('day').tail(days).reset_index(drop=True)
    return df


def get_market_turnover() -> dict:
    sh = get_index_daily('sh000001', days=25)
    sz = get_index_daily('sz399001', days=25)
    if sh.empty or sz.empty:
        return {'today_amount': 0, 'avg20_amount': 0, 'amount_ratio': 0, 'status': '数据缺失'}
    
    # 用成交量近似（Sina返回的volume单位可能不一致）
    sh_vol = sh['volume'].astype(float)
    sz_vol = sz['volume'].astype(float)
    merged = pd.merge(
        sh[['day', 'volume']].rename(columns={'volume': 'sh_vol'}),
        sz[['day', 'volume']].rename(columns={'volume': 'sz_vol'}),
        on='day'
    )
    merged['总成交额'] = merged['sh_vol'].astype(float) + merged['sz_vol'].astype(float)
    merged = merged.sort_values('day').reset_index(drop=True)
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
    if sh.empty:
        return pd.DataFrame()
    result = pd.DataFrame()
    result['日期'] = sh['day'].values
    for col_src, idx_name in [('close', '收盘'), ('pct', '涨跌')]:
        if col_src == 'pct':
            result['上证涨跌'] = sh['close'].astype(float).pct_change().fillna(0).values
            result['深证涨跌'] = sz['close'].astype(float).pct_change().fillna(0).values
            result['全A替代涨跌'] = qa['close'].astype(float).pct_change().fillna(0).values
        else:
            result['上证收盘'] = sh['close'].astype(float).values
            result['深证收盘'] = sz['close'].astype(float).values
            result['全A替代收盘'] = qa['close'].astype(float).values
    return result
