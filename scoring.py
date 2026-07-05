"""
双弦投资系统 v2.2 — 候选股3维综合评分
======================================
AND门控过滤后，按 资金维度(35%) + 技术维度(35%) + 趋势维度(30%) 综合评分排序

资金维度（35分满分）：
  - 3日主力净流入金额 → 0-15分（按百分位排名映射）
  - 资金沉淀率（3日净流入/3日成交额） → 0-10分
  - 个股资金流当日是否净流入 → 0-10分（流入=10，流出=0）

技术维度（35分满分）：
  - MACD金叉/柱线方向 → 0-12分
  - 成交量是否突破20日均量 → 0-8分（倍量=满分）
  - 是否处于底背离买点 → 0-8分（是=8，否=0）
  - 筹码集中度 → 0-7分（90%集中度<15%=7分，15-25%=4分，>25%=0分）

趋势维度（30分满分）：
  - 三层共振得分 → 0-15分（+3=15, +2=12, +1=8, 0=5, 负分=0）
  - 股价是否在MA20上方 → 0-5分
  - 20日涨跌幅 → 0-10分（正收益且幅度适中得高分）
"""

import logging
import numpy as np

import config

log = logging.getLogger("shuangxian.scoring")


# ════════════════════════════════════════════════════════
#  资金维度评分
# ════════════════════════════════════════════════════════

def _score_capital_3d_flow(net_flow_3d: float, all_3d_flows: list) -> float:
    """
    3日主力净流入金额评分 → 0-15分
    按百分位排名映射：前10%=15分，前30%=12分，前50%=8分，前70%=5分，其余=2分
    """
    if not all_3d_flows or net_flow_3d == 0:
        return 0
    
    # 过滤掉0值
    valid_flows = [f for f in all_3d_flows if f != 0]
    if not valid_flows:
        return 0
    
    # 计算百分位
    rank = sum(1 for f in valid_flows if f <= net_flow_3d) / len(valid_flows)
    
    if rank >= 0.9:
        return 15
    elif rank >= 0.7:
        return 12
    elif rank >= 0.5:
        return 8
    elif rank >= 0.3:
        return 5
    else:
        return 2


def _score_capital_sedimentation(sedimentation_rate: float) -> float:
    """
    资金沉淀率评分 → 0-10分
    沉淀率越高说明主力锁仓意愿越强
    映射：>10%=10分, >5%=8分, >2%=5分, >0%=3分, ≤0%=0分
    """
    if sedimentation_rate <= 0:
        return 0
    elif sedimentation_rate > 0.10:
        return 10
    elif sedimentation_rate > 0.05:
        return 8
    elif sedimentation_rate > 0.02:
        return 5
    else:
        return 3


def _score_capital_today_flow(net_flow_today: float) -> float:
    """
    个股资金流当日是否净流入 → 0-10分
    流入=10，流出=0
    """
    if net_flow_today is None:
        return 5  # 数据缺失给中间分
    return 10 if net_flow_today > 0 else 0


def score_capital_dimension(multi_period: dict, individual_net_flow: float = None,
                            all_3d_flows: list = None) -> dict:
    """
    资金维度综合评分（满分35分）
    
    参数:
        multi_period: {code: {'3d': float, 'sedimentation_rate': float, ...}}
        individual_net_flow: 当日主力净流入
        all_3d_flows: 所有候选股的3日净流入列表（用于百分位排名）
    
    返回: {'score': float, 'max': 35, 'details': dict}
    """
    if all_3d_flows is None:
        all_3d_flows = []
    
    # 3日净流入评分
    net_flow_3d = multi_period.get('3d', 0) if multi_period else 0
    score_3d = _score_capital_3d_flow(net_flow_3d, all_3d_flows)
    
    # 沉淀率评分
    sed_rate = multi_period.get('sedimentation_rate', 0) if multi_period else 0
    score_sed = _score_capital_sedimentation(sed_rate)
    
    # 当日净流入评分
    score_today = _score_capital_today_flow(individual_net_flow)
    
    total = score_3d + score_sed + score_today
    
    return {
        'score': total,
        'max': 35,
        'details': {
            '3日净流入': score_3d,
            '沉淀率': score_sed,
            '当日净流入': score_today,
        }
    }


# ════════════════════════════════════════════════════════
#  技术维度评分
# ════════════════════════════════════════════════════════

def _score_tech_macd(kline_df) -> float:
    """
    MACD金叉/柱线方向评分 → 0-12分
    - MACD金叉(DIF上穿DEA) → 12分
    - MACD柱线连续缩短且为负→由负转正 → 10分
    - MACD柱线>0且缩短 → 8分
    - MACD柱线>0且伸长 → 6分
    - MACD柱线<0但缩短 → 4分
    - MACD柱线<0且伸长 → 0分
    """
    if kline_df is None or len(kline_df) < 35:
        return 4  # 数据不足给中间分
    
    close = kline_df['close'].values.astype(float) if hasattr(kline_df, 'values') else np.array(kline_df['close'], dtype=float)
    
    # 计算MACD
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    hist = 2 * (dif - dea)
    
    if len(hist) < 3:
        return 4
    
    # 检查金叉：DIF从下方穿越DEA
    if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
        return 12
    
    # 柱线方向判断
    current_hist = hist[-1]
    prev_hist = hist[-2]
    
    if current_hist > 0:
        if current_hist < prev_hist:
            return 8  # 柱线>0但缩短
        else:
            return 6  # 柱线>0且伸长
    else:
        if current_hist > prev_hist:
            return 4  # 柱线<0但缩短
        else:
            return 0  # 柱线<0且伸长


def _ema(data, period):
    """指数移动平均"""
    if len(data) < period:
        return np.full_like(data, data[0] if len(data) > 0 else 0, dtype=float)
    result = np.zeros(len(data), dtype=float)
    result[0] = data[0]
    multiplier = 2.0 / (period + 1)
    for i in range(1, len(data)):
        result[i] = data[i] * multiplier + result[i-1] * (1 - multiplier)
    return result


def _score_tech_volume(kline_df) -> float:
    """
    成交量突破20日均量评分 → 0-8分
    - 倍量以上(>2x) → 8分
    - 放量(1.5-2x) → 6分
    - 温和放量(1.2-1.5x) → 4分
    - 略高于均量(1.0-1.2x) → 2分
    - 低于均量 → 0分
    """
    if kline_df is None or len(kline_df) < 25:
        return 2
    
    volume = kline_df['volume'].values.astype(float) if hasattr(kline_df, 'values') else np.array(kline_df['volume'], dtype=float)
    
    if len(volume) < 21:
        return 2
    
    avg_vol_20 = np.mean(volume[-21:-1])  # 前20日均量
    today_vol = volume[-1]
    
    if avg_vol_20 <= 0:
        return 2
    
    ratio = today_vol / avg_vol_20
    
    if ratio >= 2.0:
        return 8
    elif ratio >= 1.5:
        return 6
    elif ratio >= 1.2:
        return 4
    elif ratio >= 1.0:
        return 2
    else:
        return 0


def _score_tech_divergence(is_divergence: bool) -> float:
    """
    底背离买点评分 → 0-8分
    是=8，否=0
    """
    return 8 if is_divergence else 0


def _score_tech_chip(chip_data: dict) -> float:
    """
    筹码集中度评分 → 0-7分
    90%集中度<15%=7分，15-25%=4分，>25%=0分
    """
    if not chip_data:
        return 2  # 无数据给低分
    
    concentration_90 = chip_data.get('concentration_90', 999)
    
    if concentration_90 < 15:
        return 7
    elif concentration_90 <= 25:
        return 4
    else:
        return 0


def score_tech_dimension(kline_df, is_divergence: bool = False,
                          chip_data: dict = None) -> dict:
    """
    技术维度综合评分（满分35分）
    
    返回: {'score': float, 'max': 35, 'details': dict}
    """
    score_macd = _score_tech_macd(kline_df)
    score_vol = _score_tech_volume(kline_df)
    score_div = _score_tech_divergence(is_divergence)
    score_chip = _score_tech_chip(chip_data)
    
    total = score_macd + score_vol + score_div + score_chip
    
    return {
        'score': total,
        'max': 35,
        'details': {
            'MACD': score_macd,
            '成交量': score_vol,
            '底背离': score_div,
            '筹码': score_chip,
        }
    }


# ════════════════════════════════════════════════════════
#  趋势维度评分
# ════════════════════════════════════════════════════════

def _score_trend_resonance(resonance_score: int) -> float:
    """
    三层共振得分 → 0-15分
    +3=15, +2=12, +1=8, 0=5, -1=2, -2/-3=0
    """
    mapping = {
        3: 15, 2: 12, 1: 8, 0: 5, -1: 2, -2: 0, -3: 0,
    }
    return mapping.get(resonance_score, 0)


def _score_trend_ma20(close: float, ma20: float) -> float:
    """
    股价是否在MA20上方 → 0-5分
    在MA20上方=5分，在MA20下方=0分
    """
    if ma20 <= 0:
        return 2  # 数据不足
    return 5 if close > ma20 else 0


def _score_trend_20d_return(ret_20d: float) -> float:
    """
    20日涨跌幅评分 → 0-10分
    正收益且幅度适中得高分：
    - +5%~+15%（温和上涨）→ 10分
    - +15%~+30%（较强上涨）→ 8分
    - 0%~+5%（微涨）→ 6分
    - +30%以上（过热风险）→ 4分
    - -5%~0%（微跌）→ 3分
    - -10%~-5%（下跌）→ 1分
    - <-10%（大跌）→ 0分
    """
    if ret_20d > 0.30:
        return 4
    elif ret_20d > 0.15:
        return 8
    elif ret_20d > 0.05:
        return 10
    elif ret_20d > 0:
        return 6
    elif ret_20d > -0.05:
        return 3
    elif ret_20d > -0.10:
        return 1
    else:
        return 0


def score_trend_dimension(resonance_score: int, close: float = 0,
                           ma20: float = 0, ret_20d: float = 0) -> dict:
    """
    趋势维度综合评分（满分30分）
    
    返回: {'score': float, 'max': 30, 'details': dict}
    """
    score_res = _score_trend_resonance(resonance_score)
    score_ma20 = _score_trend_ma20(close, ma20)
    score_ret = _score_trend_20d_return(ret_20d)
    
    total = score_res + score_ma20 + score_ret
    
    return {
        'score': total,
        'max': 30,
        'details': {
            '三层共振': score_res,
            'MA20上方': score_ma20,
            '20日涨幅': score_ret,
        }
    }


# ════════════════════════════════════════════════════════
#  综合评分主函数
# ════════════════════════════════════════════════════════

def calculate_stock_score(stock_data: dict, kline_df=None,
                           multi_period: dict = None,
                           resonance_score: int = 0,
                           is_divergence: bool = False) -> dict:
    """
    计算单只候选股的3维综合评分
    
    参数:
        stock_data: 候选股数据 dict (含 close, pct_change, chip, individual_net_flow, ...)
        kline_df: 日线K线 DataFrame
        multi_period: 多周期资金流数据
        resonance_score: 三层共振得分 (-3~+3)
        is_divergence: 是否处于底背离买点
    
    返回: {
        'total_score': float,        # 综合得分
        'max_score': 100,            # 满分
        'capital_score': dict,       # 资金维度
        'tech_score': dict,          # 技术维度
        'trend_score': dict,         # 趋势维度
        'grade': str,                # 等级 (S/A/B/C/D)
    }
    """
    if not config.SCORING_ENABLED:
        return {'total_score': 0, 'max_score': 100, 'grade': 'N/A',
                'capital_score': {}, 'tech_score': {}, 'trend_score': {}}
    
    close = stock_data.get('close', 0)
    chip = stock_data.get('chip', {})
    individual_net_flow = stock_data.get('individual_net_flow')
    
    # ── 资金维度 ──
    cap_score = score_capital_dimension(
        multi_period=multi_period or {},
        individual_net_flow=individual_net_flow,
    )
    
    # ── 技术维度 ──
    tech_score = score_tech_dimension(
        kline_df=kline_df,
        is_divergence=is_divergence,
        chip_data=chip,
    )
    
    # ── 趋势维度 ──
    # 计算MA20和20日涨跌幅
    ma20 = 0
    ret_20d = 0
    if kline_df is not None and len(kline_df) >= 21:
        close_arr = kline_df['close'].values.astype(float) if hasattr(kline_df, 'values') else np.array(kline_df['close'], dtype=float)
        if len(close_arr) >= 20:
            ma20 = float(np.mean(close_arr[-20:]))
        if len(close_arr) >= 21 and close_arr[-21] > 0:
            ret_20d = float((close_arr[-1] - close_arr[-21]) / close_arr[-21])
    
    trend_score = score_trend_dimension(
        resonance_score=resonance_score,
        close=close,
        ma20=ma20,
        ret_20d=ret_20d,
    )
    
    # ── 加权综合评分 ──
    w_cap = config.SCORING_WEIGHT_CAPITAL
    w_tech = config.SCORING_WEIGHT_TECH
    w_trend = config.SCORING_WEIGHT_TREND
    
    total_score = (
        cap_score['score'] / cap_score['max'] * w_cap * 100 +
        tech_score['score'] / tech_score['max'] * w_tech * 100 +
        trend_score['score'] / trend_score['max'] * w_trend * 100
    )
    total_score = round(total_score, 1)
    
    # 等级评定
    if total_score >= 80:
        grade = 'S'
    elif total_score >= 65:
        grade = 'A'
    elif total_score >= 50:
        grade = 'B'
    elif total_score >= 35:
        grade = 'C'
    else:
        grade = 'D'
    
    return {
        'total_score': total_score,
        'max_score': 100,
        'capital_score': cap_score,
        'tech_score': tech_score,
        'trend_score': trend_score,
        'grade': grade,
    }


def batch_calculate_scores(candidates: list, multi_period: dict,
                            resonance_scores: dict, kline_cache: dict = None,
                            divergence_symbols: set = None) -> list:
    """
    批量计算候选股综合评分并排序
    
    参数:
        candidates: 候选股列表
        multi_period: {code: {'3d': ..., 'sedimentation_rate': ..., ...}}
        resonance_scores: {code: {'resonance_score': int, ...}}
        kline_cache: {symbol: DataFrame} 已有K线缓存
        divergence_symbols: 处于底背离的股票symbol集合
    
    返回: 在candidates基础上增加score字段，按评分降序排列
    """
    if not config.SCORING_ENABLED:
        return candidates
    
    if divergence_symbols is None:
        divergence_symbols = set()
    
    if kline_cache is None:
        kline_cache = {}
    
    log.info(f"  [评分] 计算{len(candidates)}只候选股综合评分")
    
    # 收集所有3日净流入用于百分位排名
    all_3d_flows = []
    for code, mp in multi_period.items():
        flow_3d = mp.get('3d', 0)
        if flow_3d != 0:
            all_3d_flows.append(flow_3d)
    
    import data_fetcher as df_module
    
    for cand in candidates:
        code = cand.get('code', '')
        symbol = cand.get('symbol', '')
        
        # 获取K线（优先用缓存）
        kline = kline_cache.get(symbol)
        if kline is None:
            try:
                kline = df_module.get_kline(symbol, scale=240, datalen=150)
            except Exception:
                kline = None
        
        # 多周期数据
        mp = multi_period.get(code, {})
        
        # 三层共振得分
        res = resonance_scores.get(code, {})
        res_score = res.get('resonance_score', 0)
        
        # 底背离标记
        is_div = symbol in divergence_symbols
        
        # 计算评分
        score_result = calculate_stock_score(
            stock_data=cand,
            kline_df=kline,
            multi_period=mp,
            resonance_score=res_score,
            is_divergence=is_div,
        )
        
        # 将3日净流入百分位评分补入（需要全局数据）
        if all_3d_flows:
            cap_details = score_result.get('capital_score', {}).get('details', {})
            net_flow_3d = mp.get('3d', 0)
            score_3d = _score_capital_3d_flow(net_flow_3d, all_3d_flows)
            cap_details['3日净流入'] = score_3d
            # 重新计算资金维度总分
            new_cap_total = score_3d + cap_details.get('沉淀率', 0) + cap_details.get('当日净流入', 0)
            score_result['capital_score']['score'] = new_cap_total
            # 重新计算综合总分
            w_cap = config.SCORING_WEIGHT_CAPITAL
            w_tech = config.SCORING_WEIGHT_TECH
            w_trend = config.SCORING_WEIGHT_TREND
            total = (
                new_cap_total / 35 * w_cap * 100 +
                score_result['tech_score']['score'] / 35 * w_tech * 100 +
                score_result['trend_score']['score'] / 30 * w_trend * 100
            )
            score_result['total_score'] = round(total, 1)
            # 重新评级
            if total >= 80:
                score_result['grade'] = 'S'
            elif total >= 65:
                score_result['grade'] = 'A'
            elif total >= 50:
                score_result['grade'] = 'B'
            elif total >= 35:
                score_result['grade'] = 'C'
            else:
                score_result['grade'] = 'D'
        
        cand['score'] = score_result
        
        log.info(f"    {cand.get('name', code)}: "
                f"综合{score_result['total_score']:.1f}分({score_result['grade']}) "
                f"资金{score_result.get('capital_score', {}).get('score', 0):.0f}/35 "
                f"技术{score_result.get('tech_score', {}).get('score', 0):.0f}/35 "
                f"趋势{score_result.get('trend_score', {}).get('score', 0):.0f}/30")
    
    # 按综合评分降序排列
    candidates.sort(key=lambda x: x.get('score', {}).get('total_score', 0), reverse=True)
    
    log.info(f"  [评分] 完成, TOP3: {[(c.get('name', ''), c.get('score', {}).get('total_score', 0)) for c in candidates[:3]]}")
    
    return candidates
