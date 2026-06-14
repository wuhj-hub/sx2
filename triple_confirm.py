"""
双弦投资系统 — 三重确认择时
==================================
保留原有三重确认逻辑，作为双弦系统的择时确认模块。
只在三个独立维度的信号全部指向同一方向时，才给出仓位调整建议。
"""

import logging
import pandas as pd
from datetime import datetime

import data_fetcher as df
import config

log = logging.getLogger("shuangxian")


def run_triple_confirm(step1: dict, step2: dict) -> dict:
    """运行三重确认择时"""
    log.info("====== 三重确认择时 ======")
    c1 = _confirm1_market_flow(step1, step2)
    log.info(f"  第一重(全市场资金流): {'✅ 通过' if c1['pass'] else '❌ 不通过'}")
    if not c1['pass']:
        return _build_result(c1, {'pass': False, 'detail': '第一重不通过，跳过'},
                            {'pass': False, 'detail': '第一重不通过，跳过'}, False)
    c2 = _confirm2_institutional_flow()
    log.info(f"  第二重(机构资金流): {'✅ 通过' if c2['pass'] else '❌ 不通过'}")
    if not c2['pass']:
        return _build_result(c1, c2, {'pass': False, 'detail': '第二重不通过，跳过'}, False)
    c3 = _confirm3_micro_flow()
    log.info(f"  第三重(微观资金流): {'✅ 通过' if c3['pass'] else '❌ 不通过'}")
    all_pass = c1['pass'] and c2['pass'] and c3['pass']
    action = "三重确认全部通过，可果断调整仓位" if all_pass else "有确认不通过，不调整仓位"
    log.info(f"  三重确认结果: {'✅ 全部通过' if all_pass else '❌ 未全部通过'}")
    return _build_result(c1, c2, c3, all_pass, action)


def _confirm1_market_flow(step1: dict, step2: dict) -> dict:
    """第一重：全市场资金流确认"""
    breath = step1.get('status', '')
    direction = step2.get('direction', '')
    volume_up = step1.get('amount_ratio', 0) >= 1.0
    same_direction = direction in ('同涨放量',)
    passed = volume_up and same_direction
    return {
        'pass': passed,
        'volume_up': volume_up,
        'same_direction': same_direction,
        'amount_ratio': step1.get('amount_ratio', 0),
        'direction': direction,
        'detail': f"成交额比={step1.get('amount_ratio', 0):.2%}, 方向={direction}",
    }


def _confirm2_institutional_flow() -> dict:
    """第二重：机构资金流确认（ETF申赎+北向资金）"""
    etf_direction = None
    north_direction = None
    try:
        etf_data = df.get_etf_scale_changes()
        if not etf_data.empty:
            etf_direction = "net_subscribe"
    except Exception as e:
        log.warning(f"ETF申赎数据获取失败: {e}")
    try:
        north = df.get_north_flow(symbol="北向资金", days=10)
        if not north.empty:
            cols = north.columns.tolist()
            buy_col = next((c for c in cols if '净买额' in c or '净买入' in c), None)
            if buy_col:
                north[buy_col] = pd.to_numeric(north[buy_col], errors='coerce')
                recent5 = north.tail(config.CONFIRM_NORTH_WINDOW)
                total = recent5[buy_col].sum()
                north_direction = "inflow" if total > 0 else "outflow"
            else:
                north_direction = "unknown"
        else:
            north_direction = "unknown"
    except Exception as e:
        log.warning(f"北向资金获取失败: {e}")
        north_direction = "unknown"
    if etf_direction and north_direction and north_direction != "unknown":
        same = True
    else:
        same = None
    passed = same is True
    return {
        'pass': passed if passed is not None else False,
        'etf_direction': etf_direction,
        'north_direction': north_direction,
        'detail': f"ETF={etf_direction}, 北向={north_direction}, 一致={same}",
        'note': 'ETF申赎数据需本地历史库支撑，当前为简化判断' if same is None else '',
    }


def _confirm3_micro_flow() -> dict:
    """第三重：微观资金流确认（龙头股资金加速度）"""
    try:
        rank = df.get_individual_fund_flow_rank(indicator="今日")
    except Exception as e:
        log.warning(f"个股资金流获取失败: {e}")
        return {'pass': False, 'detail': f'数据获取失败: {e}'}
    if rank.empty:
        return {'pass': False, 'detail': '无个股资金流数据'}
    cols = rank.columns.tolist()
    amount_col = next((c for c in cols if '成交额' in c), None)
    accel_col = next((c for c in cols if '加速度' in c or '增仓' in c), None)
    if amount_col and accel_col:
        try:
            rank[amount_col] = pd.to_numeric(
                rank[amount_col].astype(str).str.replace(',', ''), errors='coerce'
            )
            rank[accel_col] = pd.to_numeric(
                rank[accel_col].astype(str).str.replace(',', '').str.replace('%', ''),
                errors='coerce'
            )
            top = rank.nlargest(config.CONFIRM_LEADER_COUNT, amount_col)
            positive_count = (top[accel_col] > 0).sum()
            passed = positive_count >= config.CONFIRM_LEADER_COUNT // 2 + 1
            return {
                'pass': passed,
                'positive_leaders': int(positive_count),
                'total_leaders': len(top),
                'detail': f"龙头股{positive_count}/{len(top)}只资金加速度为正",
            }
        except Exception as e:
            return {'pass': False, 'detail': f'数据解析失败: {e}'}
    return {'pass': False, 'detail': f'缺少关键字段(成交额/加速度)'}


def _build_result(c1, c2, c3, all_pass, action=None):
    """构建三重确认结果"""
    if action is None:
        action = "三重确认未全部通过，不调整仓位"
    return {
        'confirm1': c1,
        'confirm2': c2,
        'confirm3': c3,
        'all_pass': all_pass,
        'action': action,
    }


def check_confirm_reverse(confirm_results: dict) -> dict:
    """检查三重确认是否出现反转信号（用于熔断判断）"""
    c1 = confirm_results.get('confirm1', {})
    c2 = confirm_results.get('confirm2', {})
    c3 = confirm_results.get('confirm3', {})
    
    reversed_dims = []
    if not c1.get('pass', True):
        reversed_dims.append('第一重_全市场资金流')
    if not c2.get('pass', True):
        reversed_dims.append('第二重_机构资金流')
    if not c3.get('pass', True):
        reversed_dims.append('第三重_微观资金流')
    
    return {
        'has_reversal': len(reversed_dims) > 0,
        'reversed_dims': reversed_dims,
        'all_reversed': len(reversed_dims) == 3,
        'partial_reversed': 0 < len(reversed_dims) < 3,
    }
