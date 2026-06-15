"""
资金流实盘复盘脚本 — 七步复盘核心逻辑
===================================
每步产出一段结构化结果，最终由 reporter.py 合并为报告。
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime

import data_fetcher as df
import config

log = logging.getLogger("shuangxian")


def step1_breath_check() -> dict:
    log.info("=== 第一步：全市场呼吸检查 ===")
    try:
        data = df.get_market_turnover()
    except Exception as e:
        log.error(f"成交额数据获取失败: {e}")
        return {
            'status': '数据缺失',
            'today_amount': 0, 'avg20_amount': 0, 'amount_ratio': 0,
            'alert': f"数据获取失败: {e}",
            'action': '无法判断，请手动检查',
        }
    ratio = data['amount_ratio']
    if ratio < config.BREATH_TURNOVER_RATIO:
        status = "冷区"
        alert = "🚨 冷区。今日没有信号触发。按规则不动。"
        action = "不开新仓，按规则不动"
    elif ratio > 1.3:
        status = "偏热"
        alert = None
        action = "警惕过热，只卖不买"
    else:
        status = "正常"
        alert = None
        action = "可按信号正常操作"
    result = {
        'status': status,
        'today_amount': data['today_amount'],
        'avg20_amount': data['avg20_amount'],
        'amount_ratio': round(ratio, 4),
        'alert': alert,
        'action': action,
    }
    log.info(f"  市场状态: {status}，成交额比: {ratio:.2%}")
    return result


def step2_index_direction() -> dict:
    log.info("=== 第二步：三指数方向判断 ===")
    try:
        indices = df.get_three_indices(days=5)
    except Exception as e:
        log.error(f"三指数数据获取失败: {e}")
        return {'direction': '数据缺失', 'indices': pd.DataFrame(), 'action': '无法判断'}
    if indices.empty:
        return {'direction': '数据缺失', 'indices': indices, 'action': '无法判断'}
    last = indices.iloc[-1]
    sh_chg = last.get('上证涨跌', 0)
    sz_chg = last.get('深证涨跌', 0)
    qa_chg = last.get('全A替代涨跌', 0)
    if len(indices) >= 2:
        today_vol = float(indices.iloc[-1].get('上证收盘', 0))
        yesterday_vol = float(indices.iloc[-2].get('上证收盘', 0))
        volume_up = today_vol > yesterday_vol
    else:
        volume_up = False
    all_up = sh_chg > 0 and sz_chg > 0 and qa_chg > 0
    all_down = sh_chg < 0 and sz_chg < 0 and qa_chg < 0
    sh_up_others_down = sh_chg > 0 and (sz_chg < 0 or qa_chg < 0)
    if all_up and volume_up:
        direction = "同涨放量"
        action = "仓位可偏重，等待三重确认"
    elif sh_up_others_down:
        direction = "权重护盘"
        action = "小票失血，不动"
    elif all_down:
        direction = "同跌"
        action = "减仓或观望"
    else:
        direction = "分歧"
        action = "方向不明，不动"
    log.info(f"  三指方向: {direction}")
    return {'direction': direction, 'indices': indices, 'action': action}


def step3_etf_check() -> dict:
    log.info("=== 第三步：ETF申赎检查 ===")
    signals = []
    try:
        etf_data = df.get_etf_scale_changes()
    except Exception as e:
        log.warning(f"ETF数据获取失败: {e}")
        return {'signals': [], 'summary': f"ETF数据获取失败: {e}"}
    if etf_data.empty:
        return {'signals': [], 'summary': '无ETF份额数据'}
    summary = f"获取到 {len(etf_data)} 只ETF数据。需建立本地ETF份额历史库后才能做完整的申赎信号分析。"
    return {'signals': signals, 'summary': summary}


def step4_sector_heatmap() -> dict:
    log.info("=== 第四步：板块资金流热力图 ===")
    try:
        sector_flow = df.get_sector_fund_flow(indicator="今日")
    except Exception as e:
        log.warning(f"板块资金流获取失败: {e}")
        return {'hot_sectors': [], 'cold_sectors': [], 'warnings': [f"数据获取失败: {e}"]}
    if sector_flow.empty:
        return {'hot_sectors': [], 'cold_sectors': [], 'warnings': ['无板块资金流数据']}
    hot_sectors = []
    cold_sectors = []
    warnings = []
    cols = sector_flow.columns.tolist()
    name_col = next((c for c in cols if '名称' in c or '行业' in c), cols[1] if len(cols) > 1 else None)
    flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
    pct_col = next((c for c in cols if '涨跌幅' in c or '涨跌' in c), None)
    if flow_col is None:
        return {'hot_sectors': [], 'cold_sectors': [],
                'warnings': [f'列名不匹配，原始列: {cols}']}
    for _, row in sector_flow.iterrows():
        try:
            name = str(row.get(name_col, ''))
            net_flow = float(str(row.get(flow_col, '0')).replace(',', '').replace('亿', ''))
            pct = float(str(row.get(pct_col, '0')).replace('%', '').replace(',', '')) if pct_col else 0
            entry = {'name': name, 'net_flow': net_flow, 'pct': pct}
            if net_flow > 0:
                hot_sectors.append(entry)
                if net_flow > sector_flow[flow_col].describe().get('75%', 0) and abs(pct) < 1.5:
                    warnings.append(f"⚠️ {name}: 资金大幅流入但涨幅有限，可能透支未来")
            else:
                cold_sectors.append(entry)
        except (ValueError, TypeError):
            continue
    hot_sectors = sorted(hot_sectors, key=lambda x: x['net_flow'], reverse=True)[:10]
    cold_sectors = sorted(cold_sectors, key=lambda x: x['net_flow'])[:10]
    log.info(f"  热门板块 TOP3: {[s['name'] for s in hot_sectors[:3]]}")
    return {'hot_sectors': hot_sectors, 'cold_sectors': cold_sectors, 'warnings': warnings}


def step5_individual_scan() -> dict:
    log.info("=== 第五步：个股资金流扫描 ===")
    try:
        rank_today = df.get_individual_fund_flow_rank(indicator="今日")
        rank_5d = df.get_individual_fund_flow_rank(indicator="5日")
    except Exception as e:
        log.warning(f"个股资金流获取失败: {e}")
        return {'watch_list': [], 'top_inflow': []}
    if rank_today.empty:
        return {'watch_list': [], 'top_inflow': []}
    watch_list = []
    top_inflow = []
    cols = rank_today.columns.tolist()
    code_col = next((c for c in cols if '代码' in c), cols[0])
    name_col = next((c for c in cols if '名称' in c), cols[1] if len(cols) > 1 else None)
    flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
    pct_col = next((c for c in cols if '涨跌幅' in c), None)
    accel_col = next((c for c in cols if '加速度' in c or '增仓' in c), None)
    top100 = rank_today.head(config.STOCK_TOP_N)
    for _, row in top100.iterrows():
        try:
            entry = {
                'code': str(row.get(code_col, '')),
                'name': str(row.get(name_col, '')),
                'net_flow': float(str(row.get(flow_col, '0')).replace(',', '')),
                'pct': float(str(row.get(pct_col, '0')).replace('%', '').replace(',', '')) if pct_col else 0,
            }
            top_inflow.append(entry)
            if accel_col:
                accel = float(str(row.get(accel_col, '0')).replace(',', '').replace('%', ''))
                if accel < 0 and entry['net_flow'] > 0:
                    watch_list.append({**entry, 'accel': accel})
        except (ValueError, TypeError):
            continue
    log.info(f"  警惕个股数: {len(watch_list)}")
    return {'watch_list': watch_list[:20], 'top_inflow': top_inflow[:20]}


def step6_margin_scan() -> dict:
    log.info("=== 第六步：融资融券异常扫描 ===")
    total_anomaly = False
    total_detail = {}
    stock_divergence = []
    try:
        margin_sh = df.get_margin_sh(days=30)
        if not margin_sh.empty:
            margin_sh['融资余额'] = margin_sh['融资余额'].astype(float)
            margin_sh['日变化'] = margin_sh['融资余额'].diff()
            recent = margin_sh.tail(21)
            if len(recent) >= 3:
                today_change = float(recent.iloc[-1]['日变化'])
                mean_change = float(recent['日变化'].iloc[1:].mean())
                std_change = float(recent['日变化'].iloc[1:].std())
                if std_change > 0 and abs(today_change - mean_change) > config.MARGIN_ANOMALY_STD * std_change:
                    total_anomaly = True
                total_detail = {
                    'today_balance': float(recent.iloc[-1]['融资余额']),
                    'today_change': today_change,
                    'mean_change': mean_change,
                    'std_change': std_change,
                }
    except Exception as e:
        log.warning(f"融资融券上海数据获取失败: {e}")
    log.info(f"  融资融券总量异常: {total_anomaly}")
    return {
        'total_anomaly': total_anomaly,
        'total_detail': total_detail,
        'stock_divergence': stock_divergence,
    }


def step7_summary(step1: dict, step2: dict, step3: dict,
                  step4: dict, step5: dict, step6: dict) -> dict:
    log.info("=== 第七步：三句话复盘小结 ===")
    breath = step1.get('status', '数据缺失')
    direction = step2.get('direction', '数据缺失')
    if breath == '冷区' or direction == '同跌':
        attitude = '消极'
    elif breath == '过热':
        attitude = '中性偏谨慎'
    elif direction == '同涨放量':
        attitude = '积极'
    elif direction == '权重护盘':
        attitude = '中性'
    else:
        attitude = '中性'
    key_signals = []
    if step1.get('alert'):
        key_signals.append(step1['alert'])
    if step4.get('warnings'):
        key_signals.extend(step4['warnings'][:2])
    if step5.get('watch_list'):
        names = [s['name'] for s in step5['watch_list'][:3]]
        key_signals.append(f"资金流减速警惕: {', '.join(names)}")
    if step6.get('total_anomaly'):
        key_signals.append("融资余额日变化异常")
    key_signal = key_signals[0] if key_signals else '今日无明显异常信号'
    if attitude == '消极':
        action = '不开新仓，不调整仓位，等待市场信号恢复'
    elif attitude == '中性偏谨慎':
        action = '只卖不买，关注持仓止损位'
    elif attitude == '积极':
        action = '关注三重确认是否全部通过，通过则可适度加仓至目标仓位'
    else:
        action = '按当前仓位持有，不主动加减仓'
    return {
        'market_attitude': attitude,
        'key_signal': key_signal,
        'tomorrow_action': action,
    }
