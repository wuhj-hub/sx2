"""
猛兽体系 v3.0 — 核心计算函数 (sx2 版)
======================================
基于猛兽派选股公众号全部公式，纯 numpy 实现，不依赖 westock
适配 akshare/tushare 数据源 (需提供 close/high/low/volume DataFrame)

函数清单:
  calc_vad()    — VAD中周期动量指标 (N=14)
  calc_ovs()    — OVS短周期动量指标 (N1=2, N2=4, M=15)
  calc_ssv()    — SSV量价加权强度 (N=200)
  calc_rs_d()   — RS_D背离值低吸 (N=5/4双参数)
  score_vad()   — VAD评分 (0-12)
  score_ovs()   — OVS评分 (0-10)
  score_ssv()   — SSV评分 (0-8)
  score_rsd()   — RS_D评分 (0-5)
  score_beast() — 四维合并评分 (0-35)
"""

import numpy as np
import logging

log = logging.getLogger("shuangxian.beast_scoring")


# ============================================================
#  工具函数
# ============================================================

def _ensure_array(series):
    """确保数据为 numpy 数组"""
    if hasattr(series, 'values'):
        return series.values.astype(float)
    return np.array(series, dtype=float)


# ============================================================
#  VAD中周期动量指标 (源自威廉姆斯成交量累积派发线)
#  参数: N=14
# ============================================================

def calc_vad(closes, highs, lows, amounts, n=14):
    """
    VAD = SUM(BSR*AMO,N)/10000000
    BSR = (C-REF(C,1))/(HI-LW), HI=MAX(H,REF(C,1)), LW=MIN(L,REF(C,1))
    """
    if len(closes) < n + 2:
        return 0
    
    c, h, l, a = map(_ensure_array, [closes, highs, lows, amounts])
    ret = np.diff(c)
    hi = np.maximum(h[1:], c[:-1])
    lw = np.minimum(l[1:], c[:-1])
    denom = np.where(hi - lw != 0, hi - lw, 1)
    bsr = ret / denom
    vad_vals = bsr * a[1:]
    
    if len(vad_vals) < n:
        return 0
    return float(np.sum(vad_vals[-n:]) / 10000000)


def score_vad(closes, highs, lows, amounts, n=14):
    """VAD评分 0-12分"""
    vad = calc_vad(closes, highs, lows, amounts, n)
    if vad > 8: return 12
    elif vad > 5: return 10
    elif vad > 3: return 8
    elif vad > 1: return 6
    elif vad > 0: return 4
    elif vad > -3: return 2
    else: return 0


# ============================================================
#  OVS短周期动量指标 (涨幅×成交金额)
#  参数: N1=2, N2=4, M=15
# ============================================================

def calc_ovs(closes, amounts, n1=2, n2=4, m=15):
    """
    PV2 = SUM(BSR*ZF*AMO/MA(AMO,N1),N1)*100
    PV3 = SUM(ZF*AMO/LLV(AMO,M),N2)*100  (向量化优化版)
    OV3 = SUM(ZF*AMO,N2)/10060000
    """
    if len(closes) < max(n1, n2, m) + 2:
        return {"pv2": 0, "pv3": 0, "ov3": 0}
    
    c, a = map(_ensure_array, [closes, amounts])
    zf = np.diff(c) / np.maximum(c[:-1], 1e-10)
    zf = np.where(np.isfinite(zf), zf, 0)
    
    if len(zf) < max(n1, n2, m):
        return {"pv2": 0, "pv3": 0, "ov3": 0}
    
    # ★ 向量化 PV3 = SUM(ZF*AMO/LLV(AMO,M),N2)*100
    # LLV(AMO,M) = pandas rolling min, 向后看M天
    import pandas as pd
    amo_series = pd.Series(a)
    llv = amo_series.rolling(window=m, min_periods=1).min().values
    llv = np.where(llv > 0, llv, 1)
    # zf 比 a 短1个元素 (diff)
    pv3_vals = zf * a[1:] / llv[1:]
    pv3 = float(np.sum(pv3_vals[-n2:]) * 100) if len(pv3_vals) >= n2 else 0
    
    # ★ 向量化 OV3 = SUM(ZF*AMO,N2)/10060000
    ov3 = float(np.sum(zf[-n2:] * a[-n2:]) / 10060000) if len(zf) >= n2 else 0
    
    return {"pv3": round(pv3, 2), "ov3": round(ov3, 2)}


def score_ovs(closes, amounts, n2=4, m=15):
    """OVS评分 0-10分"""
    ovs = calc_ovs(closes, amounts, n1=2, n2=n2, m=m)
    pv3 = ovs["pv3"]
    ov3 = ovs["ov3"]
    score = 0
    if pv3 > 40: score += 5
    elif pv3 > 20: score += 3
    elif pv3 > 10: score += 1
    if ov3 > 30: score += 5
    elif ov3 > 20: score += 3
    elif ov3 > 10: score += 1
    return min(10, score)


# ============================================================
#  SSV量价加权强度 (N=200)
# ============================================================

def calc_ssv(closes, amounts, n=200):
    """
    VWAP = SUM(AMO*C,N)/SUM(AMO,N)
    STDD = SQRT(SUM(POW((C-VWAP),2),N)/(N-1))
    SSV1 = (C-VWAP)/VWAP*500
    SSV2 = (C-VWAP)/STDD*100
    """
    if len(closes) < min(n, 20):
        return {"ssv2": 0}
    
    c, a = map(_ensure_array, [closes, amounts])
    n_actual = min(n, len(c))
    c_seg, a_seg = c[-n_actual:], a[-n_actual:]
    
    vwap = np.sum(c_seg * a_seg) / np.sum(a_seg) if np.sum(a_seg) > 0 else 0
    if vwap == 0:
        return {"ssv2": 0}
    
    variance = np.sum((c_seg - vwap) ** 2) / (n_actual - 1)
    stdd = np.sqrt(variance) if variance > 0 else 1
    
    ssv2 = (c_seg[-1] - vwap) / stdd * 100
    return {"ssv2": round(float(ssv2), 2)}


def score_ssv(closes, amounts, n=200):
    """SSV评分 0-8分"""
    ssv = calc_ssv(closes, amounts, n)
    ssv2 = ssv["ssv2"]
    if ssv2 > 100: return 8
    elif ssv2 > 50: return 6
    elif ssv2 > 0: return 4
    elif ssv2 > -50: return 2
    else: return 0


# ============================================================
#  RS_D背离值 (双参数 N=5/4)
# ============================================================

def calc_rs_d(closes, idx_closes, n=5):
    """
    RS = CLOSE/INDEXC
    RR = SLOPE(RS,N)/RS*1000
    XL_I = SLOPE(IND,N)/IND*1000
    XL_C = SLOPE(C,N)/C*1000
    DR = XL_I - XL_C
    BS=15(阈值)
    """
    if len(closes) < n + 2 or len(idx_closes) < n + 2:
        return {"dr": 0}
    
    c, ic = map(_ensure_array, [closes, idx_closes])
    min_len = min(len(c), len(ic))
    c, ic = c[-min_len:], ic[-min_len:]
    
    rs = c / ic
    x = np.arange(n)
    
    def _slope(y):
        if len(y) < n or np.std(y[-n:]) == 0:
            return 0
        return float(np.polyfit(x, y[-n:], 1)[0])
    
    rs_slope = _slope(rs)
    if rs[-1] == 0: return {"dr": 0}
    # 简化: 直接用RS斜率 * 1000 作为偏离度量
    dr = rs_slope / rs[-1] * 1000 if rs[-1] != 0 else 0
    return {"dr": round(float(dr), 2)}


def score_rsd(closes, idx_closes=None):
    """RS_D评分 0-5分（双参数N=5/4）"""
    if idx_closes is None or len(idx_closes) < 10:
        return 0
    dr5 = calc_rs_d(closes, idx_closes, 5)["dr"]
    dr4 = calc_rs_d(closes, idx_closes, 4)["dr"]
    
    if abs(dr5) < 15 or abs(dr4) < 15:
        if dr5 > 0: return 5  # 个股跑赢大盘+低吸区
        return 3               # 低吸区
    elif abs(dr5) < 25 or abs(dr4) < 25:
        return 2
    return 0


# ============================================================
#  猛兽四维综合评分 (0-35分)
# ============================================================

def score_beast(kline_df, index_df=None):
    """
    猛兽四维综合评分: VAD(0-12) + OVS(0-10) + SSV(0-8) + RS_D(0-5)
    返回: {'score': int, 'max': 35, 'details': dict}
    """
    if kline_df is None or len(kline_df) < 30:
        return {'score': 0, 'max': 35, 'details': {}, 'values': {}}
    
    closes = kline_df['close'].values
    highs = kline_df['high'].values
    lows = kline_df['low'].values
    
    # amount 可能不存在，用 close*volume 估算
    if 'amount' in kline_df.columns:
        amounts = kline_df['amount'].values
    elif 'volume' in kline_df.columns:
        amounts = closes * kline_df['volume'].values
    else:
        amounts = closes * 1  # fallback
    
    # 各维度评分
    vad_s = score_vad(closes, highs, lows, amounts)
    ovs_s = score_ovs(closes, amounts)
    ssv_s = score_ssv(closes, amounts)
    
    vad_val = calc_vad(closes, highs, lows, amounts)
    ssv_val = calc_ssv(closes, amounts)
    
    # RS_D需要大盘数据
    rsd_s = 0
    if index_df is not None and len(index_df) > 10:
        idx_closes = index_df['close'].values if 'close' in index_df.columns else np.array([])
        rsd_s = score_rsd(closes, idx_closes)
    
    total = vad_s + ovs_s + ssv_s + rsd_s
    
    return {
        'score': total,
        'max': 35,
        'details': {
            'VAD': vad_s,
            'OVS': ovs_s,
            'SSV': ssv_s,
            'RS_D': rsd_s,
        },
        'values': {
            'vad': round(float(vad_val), 2),
            'ssv2': round(float(ssv_val['ssv2']), 2),
        }
    }
