"""
双弦投资系统 v2.0 — 资金流弦：七步复盘 + AND门控
==================================================
资金流弦负责"什么时候动手"的二次确认：
1. 市场呼吸检查（非冷区）
2. 板块资金流（候选股所属板块资金净流入>0）
3. 个股资金流（候选股当日主力净流入>0）
4. 三重确认可选

AND门控：逻辑链候选股 + 资金流确认 → 两弦共振 → 推送操作信号
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime

import data_fetcher as df
import config

log = logging.getLogger("shuangxian.flow")


# 申万行业名 → Sina板块名 映射
# 两者不完全一致，需要做映射才能匹配资金流数据
SW_TO_SINA = {
    '钢铁': '钢铁行业',
    '采掘': '石油行业',
    '石油石化': '石油行业',
    '房地产': '房地产',
    '化工': '化工行业',
    '休闲服务': '酒店旅游',
    '社会服务': '酒店旅游',
    '交通运输': '交通运输',
    '计算机': '电子信息',
    '电气设备': '发电设备',
    '医药生物': '生物制药',
    '机械设备': '机械行业',
    '非银金融': '金融行业',
    '煤炭': '煤炭行业',
    '汽车': '汽车制造',
    '传媒': '传媒娱乐',
    '有色金属': '有色金属',
    '纺织服装': '纺织行业',
    '环保': '环保行业',
    '电子': '电子器件',
    '轻工制造': '印刷包装',
    '综合': '综合行业',
    '通信': '宽带提速',
    '国防军工': '国防军工',
    '食品饮料': '食品行业',
    '家用电器': '家电行业',
    '银行': '金融行业',
    '建筑材料': '建材行业',
    '建筑装饰': '建筑装饰',
    '商贸零售': '商业百货',
    '农林牧渔': '农牧饲渔',
    '公用事业': '电力行业',
}


def _map_industry_to_sina(sw_industry: str) -> str:
    """申万行业名 → Sina板块名"""
    return SW_TO_SINA.get(sw_industry, sw_industry)


# ════════════════════════════════════════════════════════
#  七步复盘（精简版，只保留AND门控需要的）
# ════════════════════════════════════════════════════════

def step1_breath_check() -> dict:
    """全市场呼吸检查"""
    log.info("  [资金流弦] 第一步：呼吸检查")
    try:
        data = df.get_market_turnover()
    except Exception as e:
        log.error(f"  成交额数据获取失败: {e}")
        return {'status': '数据缺失', 'amount_ratio': 0, 'action': '无法判断'}
    
    ratio = data['amount_ratio']
    if ratio < config.BREATH_TURNOVER_RATIO:
        status = "冷区"
        action = "不开新仓"
    elif ratio > 1.3:
        status = "偏热"
        action = "警惕过热"
    else:
        status = "正常"
        action = "可按信号操作"
    
    result = {
        'status': status,
        'today_amount': data['today_amount'],
        'avg20_amount': data['avg20_amount'],
        'amount_ratio': round(ratio, 4),
        'action': action,
    }
    log.info(f"  市场状态: {status}, 成交额比: {ratio:.2%}")
    return result


def step2_index_direction() -> dict:
    """三指数方向"""
    log.info("  [资金流弦] 第二步：三指数方向")
    try:
        indices = df.get_three_indices(days=5)
    except Exception as e:
        log.error(f"  三指数获取失败: {e}")
        return {'direction': '数据缺失', 'action': '无法判断'}
    
    if indices.empty:
        return {'direction': '数据缺失', 'action': '无法判断'}
    
    last = indices.iloc[-1]
    sh_chg = last.get('上证涨跌', 0)
    sz_chg = last.get('深证涨跌', 0)
    qa_chg = last.get('全A替代涨跌', 0)
    
    all_up = sh_chg > 0 and sz_chg > 0 and qa_chg > 0
    all_down = sh_chg < 0 and sz_chg < 0 and qa_chg < 0
    
    if all_up:
        direction = "同涨"
        action = "方向积极"
    elif all_down:
        direction = "同跌"
        action = "方向消极"
    else:
        direction = "分歧"
        action = "方向不明"
    
    log.info(f"  三指方向: {direction}")
    return {'direction': direction, 'action': action}


def step3_sector_flow() -> dict:
    """板块资金流热力图"""
    log.info("  [资金流弦] 第三步：板块资金流")
    try:
        sector_flow = df.get_sector_fund_flow(indicator="今日")
    except Exception as e:
        log.warning(f"  板块资金流获取失败: {e}")
        return {'hot_sectors': [], 'cold_sectors': [], 'sector_net_flow': {}}
    
    if sector_flow.empty:
        return {'hot_sectors': [], 'cold_sectors': [], 'sector_net_flow': {}}
    
    # 构建板块净流入映射（Sina返回元，转亿）
    sector_net_flow = {}
    cols = sector_flow.columns.tolist()
    name_col = next((c for c in cols if '名称' in c or '行业' in c), cols[1] if len(cols) > 1 else None)
    flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
    pct_col = next((c for c in cols if '涨跌幅' in c or '涨跌' in c), None)
    
    hot = []
    cold = []
    
    if name_col and flow_col:
        for _, row in sector_flow.iterrows():
            name = str(row.get(name_col, ''))
            net_flow = 0
            try:
                net_flow = float(str(row.get(flow_col, '0')).replace(',', '').replace('亿', ''))
            except (ValueError, TypeError):
                pass
            pct = 0
            if pct_col:
                try:
                    pct = float(str(row.get(pct_col, '0')).replace('%', '').replace(',', ''))
                except (ValueError, TypeError):
                    pass
            
            # Sina净流入单位统一是元，转亿
            net_flow_yi = net_flow / 1e8
            sector_net_flow[name] = net_flow_yi
            entry = {'name': name, 'net_flow': net_flow_yi, 'pct': pct}
            if net_flow > 0:
                hot.append(entry)
            else:
                cold.append(entry)
    
    hot = sorted(hot, key=lambda x: x['net_flow'], reverse=True)[:10]
    cold = sorted(cold, key=lambda x: x['net_flow'])[:10]
    
    log.info(f"  热门板块 TOP3: {[s['name'] for s in hot[:3]]}")
    
    return {
        'hot_sectors': hot,
        'cold_sectors': cold,
        'sector_net_flow': sector_net_flow,
    }


def step4_individual_flow(codes: list = None) -> dict:
    """个股资金流扫描（只扫描逻辑链候选股）"""
    log.info("  [资金流弦] 第四步：个股资金流")
    try:
        rank = df.get_individual_fund_flow_rank(indicator="今日")
    except Exception as e:
        log.warning(f"  个股资金流获取失败: {e}")
        return {'individual_net_flow': {}, 'top_inflow': []}
    
    if rank.empty:
        return {'individual_net_flow': {}, 'top_inflow': []}
    
    # 构建个股净流入映射
    cols = rank.columns.tolist()
    code_col = next((c for c in cols if '代码' in c), cols[0])
    name_col = next((c for c in cols if '名称' in c), None)
    flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
    pct_col = next((c for c in cols if '涨跌幅' in c), None)
    
    individual_net_flow = {}
    top_inflow = []
    
    for _, row in rank.head(200).iterrows():
        code = str(row.get(code_col, ''))
        name = str(row.get(name_col, ''))
        net_flow = 0
        try:
            net_flow = float(str(row.get(flow_col, '0')).replace(',', ''))
        except (ValueError, TypeError):
            pass
        pct = 0
        if pct_col:
            try:
                pct = float(str(row.get(pct_col, '0')).replace('%', '').replace(',', ''))
            except (ValueError, TypeError):
                pass
        
        individual_net_flow[code] = {
            'name': name,
            'net_flow': net_flow,
            'pct': pct,
        }
        
        if net_flow > 0:
            top_inflow.append({'code': code, 'name': name, 'net_flow': net_flow, 'pct': pct})
    
    top_inflow = sorted(top_inflow, key=lambda x: x['net_flow'], reverse=True)[:20]
    log.info(f"  个股资金流: {len(individual_net_flow)}只, 净流入>0: {len(top_inflow)}只")
    
    return {
        'individual_net_flow': individual_net_flow,
        'top_inflow': top_inflow,
    }


# ════════════════════════════════════════════════════════
#  AND门控
# ════════════════════════════════════════════════════════

def run_and_gate(logic_candidates: list, breath: dict, sector_data: dict, 
                 individual_data: dict) -> dict:
    """
    AND门控：逻辑链候选股 × 资金流确认
    
    门控条件（全部满足才标记为"共振"）：
    1. 市场非冷区
    2. 候选股所属板块当日资金净流入>0
    3. 候选股当日主力净流入>0
    
    返回: {
        'gated_candidates': [...],  # 通过门控的候选股
        'rejected_candidates': [...],  # 未通过的（含拒绝原因）
        'gate_summary': {...},
    }
    """
    log.info("=== AND门控 ===")
    
    # 条件1: 市场非冷区
    market_ok = breath.get('status', '') != '冷区'
    market_note = f"市场={breath.get('status', '未知')}"
    if market_ok:
        log.info(f"  ✅ 门控1(市场): {market_note}")
    else:
        log.info(f"  ❌ 门控1(市场): {market_note} — 冷区不操作")
    
    gated = []
    rejected = []
    
    for cand in logic_candidates:
        code = cand.get('code', '')
        industry = cand.get('industry', '未知')
        reject_reasons = []
        
        # 门控1: 市场非冷区
        if config.GATE_MARKET_NORMAL and not market_ok:
            reject_reasons.append('冷区')
        
        # 门控2: 板块资金净流入>0
        if config.GATE_SECTOR_MATCH:
            # 用映射表将申万行业名转为Sina板块名
            sina_industry = _map_industry_to_sina(industry)
            sector_net = sector_data.get('sector_net_flow', {}).get(sina_industry, None)
            # 如果精确匹配失败，尝试模糊匹配（行业名包含关系）
            if sector_net is None and sina_industry:
                for sina_name, net_val in sector_data.get('sector_net_flow', {}).items():
                    if sina_industry in sina_name or sina_name in sina_industry:
                        sector_net = net_val
                        break
            if sector_net is not None and sector_net <= 0:
                reject_reasons.append(f'{industry}({sina_industry})板块资金净流出({abs(sector_net):.2f}亿)')
            elif sector_net is None:
                reject_reasons.append(f'{industry}板块数据缺失')
        
        # 门控3: 个股主力净流入>0
        if config.GATE_INDIVIDUAL_FLOW:
            ind_info = individual_data.get('individual_net_flow', {}).get(code, None)
            if ind_info is not None:
                if ind_info['net_flow'] <= 0:
                    reject_reasons.append(f'主力净流出({abs(ind_info["net_flow"])/1e8:.2f}亿)')
                else:
                    cand['individual_net_flow'] = ind_info['net_flow']
                    cand['individual_pct'] = ind_info['pct']
            else:
                # 个股不在资金流排名中(可能成交额较小)，不阻塞
                cand['individual_net_flow'] = None
                cand['individual_pct'] = None
        
        if reject_reasons:
            cand['reject_reasons'] = reject_reasons
            rejected.append(cand)
        else:
            # 补充板块资金流信息
            sector_net = sector_data.get('sector_net_flow', {}).get(_map_industry_to_sina(industry), 0)
            cand['sector_net_flow'] = sector_net
            cand['resonance'] = True
            gated.append(cand)
    
    log.info(f"  门控结果: ✅ {len(gated)}只共振, ❌ {len(rejected)}只未通过")
    
    return {
        'gated_candidates': gated,
        'rejected_candidates': rejected,
        'gate_summary': {
            'market_ok': market_ok,
            'market_status': breath.get('status', '未知'),
            'total_candidates': len(logic_candidates),
            'gated_count': len(gated),
            'rejected_count': len(rejected),
        },
    }


# ════════════════════════════════════════════════════════
#  资金流弦主流程
# ════════════════════════════════════════════════════════

def run_flow_scan(logic_candidates: list = None) -> dict:
    """
    资金流弦扫描 + AND门控
    logic_candidates: 逻辑链弦输出的候选股列表
    
    返回: {
        'breath': dict,
        'index_direction': dict,
        'sector_flow': dict,
        'individual_flow': dict,
        'and_gate': dict,
    }
    """
    log.info("=== 资金流弦扫描 ===")
    
    # 七步复盘（精简版）
    breath = step1_breath_check()
    index_dir = step2_index_direction()
    sector_flow = step3_sector_flow()
    
    # 个股资金流（如果逻辑链有候选股，优先关注它们）
    candidate_codes = [c.get('code', '') for c in (logic_candidates or [])]
    individual_flow = step4_individual_flow(codes=candidate_codes)
    
    # AND门控
    gate_result = {
        'gated_candidates': [],
        'rejected_candidates': [],
        'gate_summary': {
            'market_ok': breath.get('status', '') != '冷区',
            'market_status': breath.get('status', '未知'),
            'total_candidates': 0,
            'gated_count': 0,
            'rejected_count': 0,
        }
    }
    if logic_candidates:
        gate_result = run_and_gate(logic_candidates, breath, sector_flow, individual_flow)
    
    return {
        'breath': breath,
        'index_direction': index_dir,
        'sector_flow': sector_flow,
        'individual_flow': individual_flow,
        'and_gate': gate_result,
    }
