"""
双弦投资系统 v2.0 — 逻辑链弦：月线牛市 + 日线突破 + 底背离买点
======================================================
基于V3.0最优方案（年化+32.97%，5/5达标）：
1. 月线牛市判定：MACD>0 + 站上MA20 + MA20斜率>0
2. 日线突破信号：涨停 / 放量半年新高 / 半年新高
3. 日线MACD底背离买点（新增）：月线牛市股中出现底背离 → 趋势回踩买入信号
4. 领涨行业优先排序（非硬过滤）
5. 混合止损：MA20保底 + 8%移动止盈 + 月线转熊退出

v2.1 — 并行化改造：3处串行K线拉取循环改为 ThreadPoolExecutor 并发执行
"""

import logging
import json
import os
import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import data_fetcher as df
import config

log = logging.getLogger("shuangxian.logic")

# ── 并行配置 ──────────────────────────────────────────
MAX_WORKERS = 6  # 4~8 之间，避免 Sina API 限频


# ════════════════════════════════════════════════════════
#  月线牛市判定
# ════════════════════════════════════════════════════════

def compute_monthly_bars(daily_df: pd.DataFrame) -> pd.DataFrame:
    """将日线数据聚合为月线"""
    if daily_df.empty:
        return pd.DataFrame()
    d = daily_df.copy()
    d['month'] = d['day'].dt.to_period('M')
    monthly = d.groupby('month').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
    ).reset_index()
    monthly['month'] = monthly['month'].astype(str)
    return monthly


def is_monthly_bull(monthly_df: pd.DataFrame) -> dict:
    """
    判定月线牛市状态
    3项全满 = 牛市：
    - MACD > 0
    - 收盘价站上MA20
    - MA20斜率 > 0
    
    返回: {
        'is_bull': 0/1,
        'monthly_score': 0-3,
        'macd': float,
        'above_ma20': bool,
        'ma20_slope': float,
        'details': str
    }
    """
    if len(monthly_df) < 22:  # 至少22根月线才能算MA20
        return {
            'is_bull': 0, 'monthly_score': 0,
            'macd': 0, 'above_ma20': False, 'ma20_slope': 0,
            'details': '月线数据不足(<22根)'
        }
    
    close = monthly_df['close'].values
    
    # MA20
    if len(close) >= 20:
        ma20 = np.mean(close[-20:])
        ma20_prev = np.mean(close[-21:-1]) if len(close) >= 21 else ma20
    else:
        ma20 = np.mean(close)
        ma20_prev = ma20
    
    above_ma20 = close[-1] > ma20
    ma20_slope = (ma20 - ma20_prev) / ma20_prev if ma20_prev > 0 else 0
    
    # MACD (12, 26, 9)
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    macd_val = 2 * (dif[-1] - dea[-1])
    
    # 计分
    score = 0
    details = []
    
    # 条件1: MACD > 0
    macd_positive = macd_val > 0
    if macd_positive:
        score += 1
        details.append('MACD>0')
    else:
        details.append('MACD≤0')
    
    # 条件2: 站上MA20
    if above_ma20:
        score += 1
        details.append('站上MA20')
    else:
        details.append('跌破MA20')
    
    # 条件3: MA20斜率>0
    if ma20_slope > 0:
        score += 1
        details.append('MA20上扬')
    else:
        details.append('MA20下行')
    
    is_bull = 1 if score == 3 else 0
    
    return {
        'is_bull': is_bull,
        'monthly_score': int(score),
        'macd': float(round(macd_val, 4)),
        'above_ma20': bool(above_ma20),
        'ma20_slope': float(round(ma20_slope, 6)),
        'details': ', '.join(details)
    }


def _ema(data, period):
    """指数移动平均"""
    if len(data) < period:
        return np.full_like(data, data[0] if len(data) > 0 else 0)
    result = np.zeros_like(data, dtype=float)
    result[0] = data[0]
    multiplier = 2.0 / (period + 1)
    for i in range(1, len(data)):
        result[i] = data[i] * multiplier + result[i-1] * (1 - multiplier)
    return result


# ════════════════════════════════════════════════════════
#  月线扫描 — 单只股票工作函数（供 ThreadPoolExecutor 调用）
# ════════════════════════════════════════════════════════

def _scan_one_monthly(s: dict) -> dict | None:
    """
    扫描单只股票的月线牛市状态（线程安全，无共享写操作）。
    返回: {'symbol': str, 'daily': DataFrame, 'bull_status': dict} 或 None
    """
    try:
        daily = df.get_kline(s['symbol'], scale=240)  # 默认600根(~2.5年)
        if daily.empty or len(daily) < 130:
            return None
        
        monthly = compute_monthly_bars(daily)
        bull_status = is_monthly_bull(monthly)
        
        return {
            'symbol': s['symbol'],
            'daily': daily,
            'bull_status': bull_status,
        }
    except Exception as e:
        log.debug(f"  {s['symbol']} 月线扫描失败: {e}")
        return None


# ════════════════════════════════════════════════════════
#  日线突破信号
# ════════════════════════════════════════════════════════

def detect_daily_signals(daily_df: pd.DataFrame, symbol: str) -> list:
    """
    检测日线突破信号
    返回: [{'date': '2026-06-18', 'signal_type': 'limit_up', 'close': xx, 'pct_change': xx}, ...]
    """
    if len(daily_df) < 130:
        return []
    
    signals = []
    close = daily_df['close'].values
    high = daily_df['high'].values
    low = daily_df['low'].values
    open_ = daily_df['open'].values
    volume = daily_df['volume'].values
    dates = daily_df['day'].values
    
    for i in range(120, len(daily_df)):
        dt = pd.Timestamp(dates[i])
        ds = dt.strftime('%Y-%m-%d')
        
        pct_change = float((close[i] - close[i-1]) / close[i-1] * 100) if close[i-1] > 0 else 0
        
        # 信号1: 涨停 (涨幅≥9.5% + 收盘接近最高价)
        if pct_change >= 9.5 and (high[i] - close[i]) / high[i] < 0.01:
            signals.append({
                'date': ds,
                'signal_type': 'limit_up',
                'close': float(close[i]),
                'pct_change': round(pct_change, 2),
                'symbol': symbol,
            })
            continue
        
        # 信号2/3: 突破120日新高
        if i >= 120:
            high_120 = np.max(high[i-120:i])
            if high[i] > high_120:
                # 放量确认：今日成交量 > 20日均量 * 1.5
                avg_vol_20 = np.mean(volume[max(0,i-20):i])
                vol_ratio = float(volume[i] / avg_vol_20) if avg_vol_20 > 0 else 0
                
                if vol_ratio >= 1.5:
                    signals.append({
                        'date': ds,
                        'signal_type': 'new_high_vol',
                        'close': float(close[i]),
                        'pct_change': round(pct_change, 2),
                        'symbol': symbol,
                        'vol_ratio': round(vol_ratio, 2),
                    })
                else:
                    signals.append({
                        'date': ds,
                        'signal_type': 'new_high',
                        'close': float(close[i]),
                        'pct_change': round(pct_change, 2),
                        'symbol': symbol,
                        'vol_ratio': round(vol_ratio, 2),
                    })
    
    return signals


# ════════════════════════════════════════════════════════
#  日线突破扫描 — 单只股票工作函数
# ════════════════════════════════════════════════════════

def _scan_one_daily_signal(s: dict, daily_data_cache: dict,
                           target_date: str, industry_map: dict,
                           current_industry_bull: dict,
                           cache_lock: threading.Lock) -> list:
    """
    扫描单只月线牛市股的日线突破信号（线程安全）。
    daily_data_cache 只读访问无需锁；写时加锁。
    返回: [signal_dict, ...]  目标日期的信号列表
    """
    try:
        # 优先复用缓存（读操作，无需锁——Python dict 读是线程安全的）
        if s['symbol'] in daily_data_cache:
            daily = daily_data_cache[s['symbol']]
        else:
            daily = df.get_kline(s['symbol'], scale=240, datalen=300)
            # 写入缓存供后续使用
            with cache_lock:
                daily_data_cache[s['symbol']] = daily
        
        if daily.empty or len(daily) < 130:
            return []
        
        signals = detect_daily_signals(daily, s['symbol'])
        # 过滤出目标日期的信号
        result = []
        for sig in signals:
            if sig['date'] == target_date:
                sig['code'] = s['code']
                sig['name'] = s.get('name', '')
                sig['industry'] = industry_map.get(
                    s['symbol'], industry_map.get(s['code'], '未知'))
                sig['ind_bull_ratio'] = current_industry_bull.get(
                    sig['industry'], 0)
                result.append(sig)
        return result
    except Exception as e:
        log.debug(f"  {s['symbol']} 日线扫描失败: {e}")
        return []


# ════════════════════════════════════════════════════════
#  日线MACD底背离检测
# ════════════════════════════════════════════════════════

def detect_daily_divergence(daily_df: pd.DataFrame, symbol: str) -> dict:
    """
    检测日线MACD底背离信号
    
    底背离 = 价格创新低 但 MACD 不创新低，说明下跌动能衰竭，可能反转向上。
    在月线牛市背景下，底背离是趋势回踩后的优质买点。
    
    算法：
    1. 计算MACD (12,26,9)
    2. 找到价格局部极小值（波谷），窗口±W根K线
    3. 比较相邻两个波谷：
       - 价格: 第二个低点 < 第一个低点（价格新低）
       - MACD: 第二个低点MACD > 第一个低点MACD（指标不新低）
    4. 确认价格已从第二个低点回升（避免下跌中途误判）
    
    返回: 发现背离时返回信号dict，否则返回None
    """
    lookback = config.DIVERGENCE_LOOKBACK
    window = config.DIVERGENCE_LOCAL_WINDOW
    min_gap = config.DIVERGENCE_MIN_GAP
    recover_pct = config.DIVERGENCE_RECOVER_PCT
    macd_type = config.DIVERGENCE_MACD_TYPE
    
    if len(daily_df) < 120:
        return None
    
    close = daily_df['close'].values.astype(float)
    low = daily_df['low'].values.astype(float)
    dates = daily_df['day'].values
    
    # 只分析最近 lookback 根K线（但MACD计算需要更早的数据预热）
    start_idx = max(0, len(daily_df) - lookback)
    
    # 计算全序列MACD
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    hist = 2 * (dif - dea)  # MACD柱
    
    # 选择背离判断指标
    if macd_type == "dif":
        macd_line = dif
    else:
        macd_line = hist
    
    # 找局部价格极小值（波谷）: low[i]是窗口内最低
    local_lows = []
    for i in range(start_idx, len(daily_df)):
        left = max(0, i - window)
        right = min(len(daily_df), i + window + 1)
        if low[i] == np.min(low[left:right]):
            local_lows.append(i)
    
    # 需要至少2个波谷才能比较
    if len(local_lows) < 2:
        return None
    
    # 从最近的波谷对开始检查（优先最新信号）
    for j in range(len(local_lows) - 1, 0, -1):
        i2 = local_lows[j]   # 较新的低点
        i1 = local_lows[j-1]  # 较旧的低点
        
        # 间隔检查：两个低点不能太近也不能太远
        gap = i2 - i1
        if gap < min_gap:
            continue
        
        # 第二个低点不能太旧（需在回望窗口内）
        if len(daily_df) - 1 - i2 > lookback:
            break
        
        # 底背离核心条件：
        # 1) 价格创新低：第二个低点的最低价 < 第一个低点的最低价
        price_lower = low[i2] < low[i1]
        # 2) MACD不创新低：第二个低点的MACD值 > 第一个低点的MACD值
        macd_higher = macd_line[i2] > macd_line[i1]
        
        if not (price_lower and macd_higher):
            continue
        
        # 3) 确认回升：当前价格已从第二个低点回升超过 recover_pct
        current_price = close[-1]
        recovery = (current_price - low[i2]) / low[i2] if low[i2] > 0 else 0
        if recovery < recover_pct:
            continue
        
        # 全部条件满足 → 底背离信号
        dt = pd.Timestamp(dates[i2])
        ds = dt.strftime('%Y-%m-%d')
        pct_change = float((close[-1] - close[-2]) / close[-2] * 100) if close[-2] > 0 else 0
        
        return {
            'date': ds,
            'signal_type': 'bottom_divergence',
            'close': float(close[-1]),
            'pct_change': round(pct_change, 2),
            'symbol': symbol,
            'divergence_low': float(low[i2]),
            'prev_low': float(low[i1]),
            'macd_at_low': round(float(macd_line[i2]), 4),
            'macd_at_prev_low': round(float(macd_line[i1]), 4),
            'recovery_pct': round(float(recovery * 100), 2),
            'gap_days': int(gap),
        }
    
    return None


# ════════════════════════════════════════════════════════
#  底背离扫描 — 单只股票工作函数
# ════════════════════════════════════════════════════════

def _scan_one_divergence(s: dict, daily_data_cache: dict,
                         industry_map: dict, name_map: dict,
                         cache_lock: threading.Lock) -> dict | None:
    """
    扫描单只月线牛市股的底背离信号（线程安全）。
    返回: 信号dict 或 None
    """
    try:
        if s['symbol'] in daily_data_cache:
            daily = daily_data_cache[s['symbol']]
        else:
            needed = config.DIVERGENCE_LOOKBACK + 60
            daily = df.get_kline(s['symbol'], scale=240,
                                 datalen=max(needed, 200))
            with cache_lock:
                daily_data_cache[s['symbol']] = daily
        
        if daily.empty or len(daily) < 120:
            return None
        
        div = detect_daily_divergence(daily, s['symbol'])
        if div:
            div['code'] = s['code']
            div['name'] = s.get('name', '') or name_map.get(s['symbol'], '')
            div['industry'] = industry_map.get(
                s['symbol'], industry_map.get(s['code'], '未知'))
            return div
        return None
    except Exception as e:
        log.debug(f"  {s['symbol']} 底背离检测失败: {e}")
        return None


def scan_divergence_signals(stock_pool: list, bull_stocks: list,
                            daily_data_cache: dict, industry_map: dict,
                            target_date: str) -> list:
    """
    扫描底背离信号：在月线牛市股票中检测日线MACD底背离（并行版）
    
    底背离 = 价格创新低但MACD不创新低，下跌动能衰竭。
    月线牛市 + 日线底背离 = 趋势回踩买点（高置信度）。
    
    返回: [{'date', 'signal_type', 'code', 'name', 'industry', ...}, ...]
    """
    if not config.DIVERGENCE_ENABLED:
        log.info("  底背离检测: 已禁用")
        return []
    
    log.info(f"  底背离检测: 扫描 {len(bull_stocks)} 只月线牛市股...")
    
    name_map = {s['symbol']: s.get('name', '') for s in stock_pool}
    
    # 筛选出月线牛市股
    bull_items = [s for s in stock_pool if s['symbol'] in bull_stocks]
    scan_count = len(bull_items)
    
    divergence_signals = []
    cache_lock = threading.Lock()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _scan_one_divergence, s, daily_data_cache,
                industry_map, name_map, cache_lock
            ): s for s in bull_items
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                divergence_signals.append(result)
    
    log.info(f"  底背离扫描: {scan_count}只, 发现信号: {len(divergence_signals)}个")
    return divergence_signals


# ════════════════════════════════════════════════════════
#  行业牛市状态 + 领涨行业优先排序
# ════════════════════════════════════════════════════════

def compute_industry_bull_status(monthly_bull_map: dict, industry_map: dict) -> dict:
    """
    计算每个行业当月的月线牛市比例
    monthly_bull_map: {symbol: {'2026-06': {'is_bull': 1, ...}, ...}}
    industry_map: {code: '行业名'}
    
    返回: {month_key: {industry: bull_ratio}}
    """
    all_months = set()
    for sym, bm in monthly_bull_map.items():
        for mk in bm:
            all_months.add(mk)
    
    result = {}
    for mk in all_months:
        ind_counts = defaultdict(lambda: {'total': 0, 'bull': 0})
        for sym, bm in monthly_bull_map.items():
            # 兼容 symbol(sh600519) 和 code(600519) 两种 key 格式
            ind = industry_map.get(sym, industry_map.get(sym[2:] if len(sym) > 2 else sym, '未知'))
            info = bm.get(mk)
            if info:
                ind_counts[ind]['total'] += 1
                ind_counts[ind]['bull'] += info['is_bull']
        result[mk] = {}
        for ind, c in ind_counts.items():
            if c['total'] >= 3:
                result[mk][ind] = c['bull'] / c['total']
            else:
                result[mk][ind] = 0.5
    return result


# ════════════════════════════════════════════════════════
#  主流程：每日扫描
# ════════════════════════════════════════════════════════

def run_logic_scan(target_date: str = None) -> dict:
    """
    逻辑链弦每日扫描（并行版 v2.1）
    target_date: '2026-06-18'，默认今天
    
    返回: {
        'date': str,
        'monthly_bull_count': int,
        'signals': [signal_dict, ...],
        'candidates': [candidate_dict, ...],  # 按领涨行业优先排序
        'industry_status': {industry: bull_ratio, ...},
    }
    """
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')
    
    mk = target_date[:7]  # '2026-06'
    log.info(f"=== 逻辑链弦扫描 — {target_date} ===")
    
    # 1. 加载/更新缓存
    cache_dir = config.CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    
    monthly_bull_path = os.path.join(cache_dir, 'monthly_bull.json')
    industry_map_path = os.path.join(cache_dir, 'industry_map.json')
    stock_pool_path = os.path.join(cache_dir, 'stock_pool.json')
    
    # 加载行业映射
    if os.path.exists(industry_map_path):
        with open(industry_map_path) as f:
            industry_map = json.load(f)
        log.info(f"  行业映射缓存: {len(industry_map)}只")
    else:
        log.info("  获取行业映射...")
        industry_map, _ = df.get_industry_constituents()
        with open(industry_map_path, 'w') as f:
            json.dump(industry_map, f, ensure_ascii=False)
        log.info(f"  行业映射已缓存: {len(industry_map)}只")
    
    # 加载股票池
    if os.path.exists(stock_pool_path):
        with open(stock_pool_path) as f:
            stock_pool = json.load(f)
        log.info(f"  股票池缓存: {len(stock_pool)}只")
    else:
        log.info("  获取股票池...")
        stock_pool = df.get_stock_pool()
        with open(stock_pool_path, 'w') as f:
            json.dump(stock_pool, f, ensure_ascii=False)
        log.info(f"  股票池已缓存: {len(stock_pool)}只")
    
    # 兼容旧缓存：确保每只股票都有 code 和 symbol 字段
    for s in stock_pool:
        if 'code' not in s and 'symbol' in s:
            s['code'] = s['symbol'][2:]  # sh600519 → 600519
        if 'symbol' not in s and 'code' in s:
            prefix = 'sh' if s['code'].startswith('6') else 'sz'
            s['symbol'] = f"{prefix}{s['code']}"

    # 2. 加载/更新月线牛市缓存
    if os.path.exists(monthly_bull_path):
        with open(monthly_bull_path) as f:
            monthly_bull = json.load(f)
        log.info(f"  月线牛市缓存: {len(monthly_bull)}只")
    else:
        monthly_bull = {}
    
    # 3. 逐只扫描（增量更新：只扫描缓存中缺失或过时的）—— 并行版
    need_update = []
    pool_codes = set(s['code'] for s in stock_pool)
    
    for s in stock_pool:
        sym = s['symbol']
        if sym not in monthly_bull or mk not in monthly_bull.get(sym, {}):
            need_update.append(s)
    
    if need_update:
        log.info(f"  需更新月线牛市: {len(need_update)}只")
        # 日线数据缓存：月线扫描拉过的K线存起来，日线信号扫描直接复用
        daily_data_cache = {}
        cache_lock = threading.Lock()
        
        # 分批更新，每批内并行执行
        batch_size = 50
        for i in range(0, len(need_update), batch_size):
            batch = need_update[i:i + batch_size]
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(_scan_one_monthly, s): s
                           for s in batch}
                for future in as_completed(futures):
                    result = future.result()
                    if result is None:
                        continue
                    sym = result['symbol']
                    # 线程安全写入共享数据结构
                    with cache_lock:
                        daily_data_cache[sym] = result['daily']
                        if sym not in monthly_bull:
                            monthly_bull[sym] = {}
                        monthly_bull[sym][mk] = result['bull_status']
            
            done = min(i + batch_size, len(need_update))
            log.info(f"  月线扫描进度: {done}/{len(need_update)}")
        
        # 保存缓存
        with open(monthly_bull_path, 'w') as f:
            json.dump(monthly_bull, f, ensure_ascii=False)
        log.info(f"  月线牛市缓存已更新: {len(monthly_bull)}只")
    else:
        daily_data_cache = {}
    
    # 4. 当日月线牛市股票
    bull_stocks = []
    for sym, bm in monthly_bull.items():
        if mk in bm and bm[mk].get('is_bull') == 1:
            bull_stocks.append(sym)  # sym格式: sh600519 / sz300750
    log.info(f"  当前月线牛市: {len(bull_stocks)}只")
    
    # 行业牛市状态
    industry_bull = compute_industry_bull_status(monthly_bull, industry_map)
    current_industry_bull = industry_bull.get(mk, {})
    # 领涨行业排序
    leading_industries = sorted(
        current_industry_bull.items(),
        key=lambda x: x[1],
        reverse=True
    )
    log.info(f"  领涨行业 TOP5: {[(ind, f'{r:.0%}') for ind, r in leading_industries[:5]]}")
    
    # 6. 日线突破信号（只扫描月线牛市的股票）—— 并行版
    today_signals = []
    scan_count = 0
    
    # 名称映射
    name_map = {s['symbol']: s.get('name', '') for s in stock_pool}
    
    # 筛选出月线牛市股
    bull_items = [s for s in stock_pool if s['symbol'] in bull_stocks]
    scan_count = len(bull_items)
    
    cache_lock = threading.Lock()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _scan_one_daily_signal, s, daily_data_cache,
                target_date, industry_map, current_industry_bull, cache_lock
            ): s for s in bull_items
        }
        for future in as_completed(futures):
            sigs = future.result()
            if sigs:
                today_signals.extend(sigs)
    
    log.info(f"  日线扫描: {scan_count}只月线牛市股, 今日信号: {len(today_signals)}个")
    
    # 6b. 底背离检测（月线牛市股中检测日线MACD底背离）
    divergence_signals = scan_divergence_signals(
        stock_pool, bull_stocks, daily_data_cache, industry_map, target_date
    )
    # 为底背离信号补充行业牛市占比
    for div in divergence_signals:
        div['ind_bull_ratio'] = current_industry_bull.get(div.get('industry', ''), 0)
    
    # 7. 领涨行业优先排序（突破信号）
    if config.INDUSTRY_PRIORITY:
        priority_order = {'limit_up': 0, 'new_high_vol': 1, 'new_high': 2}
        today_signals.sort(key=lambda x: (
            priority_order.get(x['signal_type'], 3),
            -x.get('ind_bull_ratio', 0),
            -x.get('pct_change', 0)
        ))
    else:
        priority_order = {'limit_up': 0, 'new_high_vol': 1, 'new_high': 2}
        today_signals.sort(key=lambda x: (
            priority_order.get(x['signal_type'], 3),
            -x.get('pct_change', 0)
        ))
    
    # 8. 汇总
    signal_summary = defaultdict(int)
    for sig in today_signals:
        signal_summary[sig['signal_type']] += 1
    
    # 底背离信号按行业牛市占比排序（高的优先）
    divergence_signals.sort(key=lambda x: (
        -x.get('ind_bull_ratio', 0),
        -x.get('recovery_pct', 0)
    ))
    
    result = {
        'date': target_date,
        'month_key': mk,
        'monthly_bull_count': len(bull_stocks),
        'signal_count': len(today_signals),
        'signal_summary': dict(signal_summary),
        'candidates': today_signals[:20],  # 最多20只突破候选
        'divergence_signals': divergence_signals[:20],  # 最多20只底背离候选
        'divergence_count': len(divergence_signals),
        'industry_status': current_industry_bull,
        'leading_industries': leading_industries[:10],
    }
    
    log.info(f"  信号分布: {dict(signal_summary)}")
    log.info(f"  突破候选: {len(today_signals[:20])}只, 底背离: {len(divergence_signals[:20])}只")
    
    return result
