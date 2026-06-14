"""
双弦投资系统 — 数据获取层
==================================
封装所有 akshare 数据调用，统一异常处理和重试逻辑。
保留原有核心逻辑，小幅更新以支持双弦系统需求。
"""

import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

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


def get_index_daily(symbol: str, days: int = 30) -> pd.DataFrame:
    """获取指数日线数据"""
    df = _retry(ak.stock_zh_index_daily, symbol=symbol)
    df = df.rename(columns={
        'date': '日期', 'open': '开盘', 'high': '最高',
        'low': '最低', 'close': '收盘', 'volume': '成交量'
    })
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期').tail(days).reset_index(drop=True)
    return df


def get_market_turnover() -> dict:
    """获取全市场成交额数据"""
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
    """获取三大指数数据"""
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
    """获取ETF份额变化数据"""
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


def get_sector_fund_flow(indicator: str = "今日") -> pd.DataFrame:
    """获取板块资金流排行"""
    try:
        df = _retry(ak.stock_sector_fund_flow_rank, indicator=indicator, sector_type="行业资金流")
        return df
    except Exception as e:
        log.warning(f"行业资金流获取失败: {e}")
        return pd.DataFrame()


def get_sector_fund_flow_hist(sector_name: str, days: int = 30) -> pd.DataFrame:
    """获取单个板块资金流历史"""
    try:
        df = _retry(ak.stock_sector_fund_flow_hist, symbol=sector_name)
        if df is not None and len(df) > 0:
            return df.tail(days)
        return pd.DataFrame()
    except Exception as e:
        log.warning(f"行业'{sector_name}'资金流历史获取失败: {e}")
        return pd.DataFrame()


def get_individual_fund_flow_rank(indicator: str = "今日") -> pd.DataFrame:
    """获取个股资金流排名"""
    try:
        df = _retry(ak.stock_individual_fund_flow_rank, indicator=indicator)
        return df
    except Exception as e:
        log.warning(f"个股资金流排名获取失败: {e}")
        return pd.DataFrame()


def get_individual_fund_flow(symbol: str, market: str = "sh") -> pd.DataFrame:
    """获取单个个股资金流历史"""
    try:
        df = _retry(ak.stock_individual_fund_flow, stock=symbol, market=market)
        return df
    except Exception as e:
        log.warning(f"个股'{symbol}'资金流获取失败: {e}")
        return pd.DataFrame()


def get_margin_sh(days: int = 30) -> pd.DataFrame:
    """获取上海融资融券数据"""
    try:
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=days+10)).strftime('%Y%m%d')
        df = _retry(ak.stock_margin_sse, start_date=start, end_date=end)
        return df
    except Exception as e:
        log.warning(f"上海融资融券获取失败: {e}")
        return pd.DataFrame()


def get_margin_sz(date_str: str = None) -> pd.DataFrame:
    """获取深圳融资融券数据"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    try:
        df = _retry(ak.stock_margin_szse, date=date_str)
        return df
    except Exception as e:
        log.warning(f"深圳融资融券获取失败: {e}")
        return pd.DataFrame()


def get_north_flow(symbol: str = "沪股通", days: int = 30) -> pd.DataFrame:
    """获取北向资金数据"""
    try:
        df = _retry(ak.stock_hsgt_hist_em, symbol=symbol)
        if df is not None and len(df) > 0:
            return df.tail(days)
        return pd.DataFrame()
    except Exception as e:
        log.warning(f"北向资金获取失败: {e}")
        return pd.DataFrame()


def get_stock_zh_a_daily(symbol: str, days: int = 30) -> pd.DataFrame:
    """获取A股日线数据"""
    df = _retry(ak.stock_zh_a_daily, symbol=symbol, adjust="")
    if df is not None and len(df) > 0:
        return df.tail(days)
    return pd.DataFrame()


def get_stock_list() -> pd.DataFrame:
    """获取A股股票列表"""
    try:
        df = _retry(ak.stock_zh_a_spot_em)
        return df
    except Exception:
        pass
    log.warning("A股列表获取失败，六层滤网功能受限")
    return pd.DataFrame()


def get_sina_realtime(codes: list) -> dict:
    """获取新浪实时行情（批量）"""
    import urllib.request
    import os
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


# ════════════════════════════════════════════════════════
# 双弦系统新增数据获取函数
# ════════════════════════════════════════════════════════

def get_stock_info_cninfo(symbol: str) -> dict:
    """获取个股详细信息（用于逻辑链标的验证）"""
    try:
        df = ak.stock_individual_info_em(symbol=symbol)
        if df is not None and len(df) > 0:
            info_dict = dict(zip(df['item'], df['value']))
            return {
                'code': symbol,
                'name': info_dict.get('股票简称', ''),
                'industry': info_dict.get('行业', ''),
                'market': info_dict.get('上市时间', ''),
                'concept': info_dict.get('概念', ''),
            }
    except Exception as e:
        log.warning(f"个股'{symbol}'详细信息获取失败: {e}")
    return {}


def get_sector_concentration(sector_name: str, days: int = 5) -> dict:
    """计算板块资金浓度及波动"""
    try:
        df = get_sector_fund_flow_hist(sector_name, days=days)
        if df.empty or len(df) < 2:
            return {'concentration': 0, 'trend': 'unknown', 'sigma': 0}
        
        cols = df.columns.tolist()
        flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
        if flow_col:
            df[flow_col] = pd.to_numeric(df[flow_col].astype(str).str.replace(',', '').str.replace('亿', ''), errors='coerce')
            recent = df[flow_col].tail(days)
            mean_flow = recent.mean()
            std_flow = recent.std()
            today = recent.iloc[-1]
            
            # 计算趋势
            if len(recent) >= 3:
                trend_slope = (recent.iloc[-1] - recent.iloc[0]) / len(recent)
                trend = 'rising' if trend_slope > 0 else 'falling'
            else:
                trend = 'unknown'
            
            # 计算浓度（相对于均值）
            concentration = today / mean_flow if mean_flow > 0 else 0
            
            return {
                'concentration': concentration,
                'trend': trend,
                'sigma': std_flow,
                'mean': mean_flow,
                'today': today,
            }
    except Exception as e:
        log.warning(f"板块'{sector_name}'资金浓度计算失败: {e}")
    return {'concentration': 0, 'trend': 'unknown', 'sigma': 0}


def get_stock_fund_acceleration(symbol: str, market: str = "sh", days: int = 5) -> dict:
    """计算个股资金加速度"""
    try:
        df = get_individual_fund_flow(symbol, market)
        if df.empty or len(df) < 3:
            return {'acceleration': 0, 'trend': 'unknown'}
        
        cols = df.columns.tolist()
        flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
        if flow_col:
            df[flow_col] = pd.to_numeric(df[flow_col].astype(str).str.replace(',', '').str.replace('亿', ''), errors='coerce')
            recent = df[flow_col].tail(days)
            
            # 计算加速度（一阶导数）
            if len(recent) >= 3:
                accel = recent.diff().diff().iloc[-1] if len(recent) >= 3 else 0
                trend = 'positive' if recent.iloc[-1] > recent.iloc[0] else 'negative'
            else:
                accel = 0
                trend = 'unknown'
            
            # 连续正增长天数
            positive_days = 0
            for v in recent.values[::-1]:
                if v > 0:
                    positive_days += 1
                else:
                    break
            
            return {
                'acceleration': float(accel) if pd.notna(accel) else 0,
                'trend': trend,
                'positive_days': positive_days,
                'recent_flows': recent.tolist(),
            }
    except Exception as e:
        log.warning(f"个股'{symbol}'资金加速度计算失败: {e}")
    return {'acceleration': 0, 'trend': 'unknown', 'positive_days': 0}


def batch_get_stock_info(codes: list) -> dict:
    """批量获取股票信息"""
    results = {}
    for code in codes:
        info = get_stock_info_cninfo(code)
        if info:
            results[code] = info
        time.sleep(0.3)  # 避免请求过快
    return results
