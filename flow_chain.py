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
    """板块资金流热力图（增强版：多周期全景 + 概念板块）"""
    log.info("  [资金流弦] 第三步：板块资金流（多周期全景+概念板块）")
    
    # 尝试获取多周期板块资金流（行业）
    heatmap_df = pd.DataFrame()
    if config.HEATMAP_ENABLED:
        try:
            heatmap_df = df.get_sector_flow_multi_period()
        except Exception as e:
            log.warning(f"  多周期板块资金流获取失败: {e}")
    
    # 如果多周期获取失败，降级到单周期
    if heatmap_df.empty:
        log.info("  降级到单周期板块资金流...")
        try:
            sector_flow = df.get_sector_fund_flow(indicator="今日")
        except Exception as e:
            log.warning(f"  板块资金流获取失败: {e}")
            return {'hot_sectors': [], 'cold_sectors': [], 'sector_net_flow': {}, 
                    'heatmap': pd.DataFrame(), 'concept_hot': [], 'concept_cold': [],
                    'concept_net_flow': {}}
        
        if sector_flow.empty:
            return {'hot_sectors': [], 'cold_sectors': [], 'sector_net_flow': {}, 
                    'heatmap': pd.DataFrame(), 'concept_hot': [], 'concept_cold': [],
                    'concept_net_flow': {}}
        
        # 构建板块净流入映射
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
                
                net_flow_yi = net_flow / 1e8
                sector_net_flow[name] = net_flow_yi
                entry = {'name': name, 'net_flow': net_flow_yi, 'pct': pct}
                if net_flow > 0:
                    hot.append(entry)
                else:
                    cold.append(entry)
        
        hot = sorted(hot, key=lambda x: x['net_flow'], reverse=True)[:10]
        cold = sorted(cold, key=lambda x: x['net_flow'])[:10]
        
        # ── 概念板块资金流（补充）──
        concept_hot, concept_cold, concept_net_flow = _get_concept_flow_data()
        
        log.info(f"  热门板块 TOP3: {[s['name'] for s in hot[:3]]}")
        
        return {
            'hot_sectors': hot,
            'cold_sectors': cold,
            'sector_net_flow': sector_net_flow,
            'heatmap': pd.DataFrame(),
            'concept_hot': concept_hot,
            'concept_cold': concept_cold,
            'concept_net_flow': concept_net_flow,
        }
    
    # 多周期数据成功，从中提取各字段
    sector_net_flow = {}
    hot = []
    cold = []
    
    for _, row in heatmap_df.iterrows():
        name = str(row.get('名称', ''))
        # 今日净流入（元→亿）
        today_flow = float(row.get('今日_净流入', 0)) / 1e8
        pct = float(row.get('今日_涨跌', 0))
        direction = row.get('方向', '➖')
        total_flow = float(row.get('累计净流入', 0)) / 1e8
        
        sector_net_flow[name] = today_flow
        
        # 3/5/10日数据
        d3 = float(row.get('3日_净流入', 0)) / 1e8
        d5 = float(row.get('5日_净流入', 0)) / 1e8
        d10 = float(row.get('10日_净流入', 0)) / 1e8
        
        entry = {
            'name': name, 'net_flow': today_flow, 'pct': pct,
            'd3': d3, 'd5': d5, 'd10': d10, 'total': total_flow, 'direction': direction,
        }
        if today_flow > 0:
            hot.append(entry)
        else:
            cold.append(entry)
    
    hot = sorted(hot, key=lambda x: x['net_flow'], reverse=True)[:config.HEATMAP_TOP_N]
    cold = sorted(cold, key=lambda x: x['net_flow'])[:5]
    
    # ── 概念板块资金流（补充）──
    concept_hot, concept_cold, concept_net_flow = _get_concept_flow_data()
    
    log.info(f"  热门板块 TOP3: {[s['name'] for s in hot[:3]]}")
    if concept_hot:
        log.info(f"  热门概念 TOP3: {[s['name'] for s in concept_hot[:3]]}")
    
    return {
        'hot_sectors': hot,
        'cold_sectors': cold,
        'sector_net_flow': sector_net_flow,
        'heatmap': heatmap_df,
        'concept_hot': concept_hot,
        'concept_cold': concept_cold,
        'concept_net_flow': concept_net_flow,
    }


def _get_concept_flow_data() -> tuple:
    """获取概念板块资金流数据，返回 (hot, cold, net_flow_map)"""
    concept_hot = []
    concept_cold = []
    concept_net_flow = {}
    
    if not config.CONCEPT_ENABLED:
        return concept_hot, concept_cold, concept_net_flow
    
    try:
        concept_df = df.get_concept_sector_fund_flow()
        if concept_df is not None and not concept_df.empty:
            for _, row in concept_df.iterrows():
                name = str(row.get('名称', ''))
                net_flow_raw = float(row.get('净流入', 0))
                pct = float(row.get('涨跌幅', 0))
                # 统一转换为亿元
                if abs(net_flow_raw) > 1e10:
                    net_flow_yi = net_flow_raw / 1e8
                elif abs(net_flow_raw) > 1e6:
                    net_flow_yi = net_flow_raw / 1e8
                else:
                    net_flow_yi = net_flow_raw  # 可能已经是亿
                
                concept_net_flow[name] = net_flow_yi
                entry = {'name': name, 'net_flow': net_flow_yi, 'pct': pct}
                if net_flow_yi > 0:
                    concept_hot.append(entry)
                else:
                    concept_cold.append(entry)
            
            concept_hot.sort(key=lambda x: x['net_flow'], reverse=True)
            concept_cold.sort(key=lambda x: x['net_flow'])
            log.info(f"  [概念] 资金流入{len(concept_hot)}个, 流出{len(concept_cold)}个")
    except Exception as e:
        log.warning(f"  [概念] 资金流获取失败: {e}")
    
    return concept_hot, concept_cold, concept_net_flow


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
#  个股多周期资金验证
# ════════════════════════════════════════════════════════

def step5_multi_period_flow(candidates: list) -> dict:
    """
    获取候选股的多周期(3/5/10/20日)主力净流入
    返回: {code: {'3d': float, '5d': float, '10d': float, '20d': float, 'signal': str}}
    """
    if not config.MULTI_PERIOD_ENABLED or not candidates:
        return {}
    
    log.info(f"  [多周期] 获取{len(candidates)}只候选股的多周期资金流")
    result = {}
    
    for cand in candidates:
        code = cand.get('code', '')
        if not code:
            continue
        try:
            periods = df.get_stock_fund_flow_periods(code)
            # 判断方向信号
            vals = [periods.get(f'{d}d', 0) for d in config.MULTI_PERIOD_DAYS]
            if all(v > 0 for v in vals):
                signal = '📈'  # 全部流入
            elif all(v < 0 for v in vals):
                signal = '📉'  # 全部流出
            elif vals[0] > 0 and vals[-1] < 0:
                signal = '⚡'  # 短期新进场
            elif vals[0] < 0 and vals[-1] > 0:
                signal = '🔄'  # 短期流出但长期仍在流入
            else:
                signal = '⚠️'  # 混合
            
            periods['signal'] = signal
            result[code] = periods
            log.info(f"    {cand.get('name', code)}: 3D={periods['3d']/1e8:.2f}亿 20D={periods['20d']/1e8:.2f}亿 {signal}")
        except Exception as e:
            log.warning(f"    {code} 多周期获取失败: {e}")
            result[code] = {f'{d}d': 0 for d in config.MULTI_PERIOD_DAYS}
            result[code]['signal'] = '❓'
    
    return result


# ════════════════════════════════════════════════════════
#  三层共振评分
# ════════════════════════════════════════════════════════

def calc_three_layer_resonance(temperature: dict, sector_flow: dict, 
                                candidates: list, multi_period: dict) -> dict:
    """
    三层共振评分：大盘 + 板块 + 个股 三层趋势同向打分
    每层: +1(向上) / 0(中性) / -1(向下)
    总分: -3 ~ +3
    
    大盘层: 温度计>=60 → +1, 40-59 → 0, <40 → -1
    板块层: 候选股所属板块3日/5日净流入>0 → +1, 混合 → 0, 全流出 → -1
    个股层: 个股3日/5日/10日主力净流入>0 → +1, 混合 → 0, 全流出 → -1
    
    返回: {code: {'market_layer': int, 'sector_layer': int, 'stock_layer': int,
                  'resonance_score': int, 'label': str}}
    """
    if not config.RESONANCE_ENABLED or not candidates:
        return {}
    
    log.info("  [共振分] 计算三层共振评分")
    
    # ── 大盘层 ──
    market_layer = 0
    if temperature and temperature.get('score') is not None:
        score = temperature['score']
        if score >= 60:
            market_layer = 1
        elif score < 40:
            market_layer = -1
        else:
            market_layer = 0
    
    # ── 板块层 & 个股层 ──
    result = {}
    sector_net_flow = sector_flow.get('sector_net_flow', {})
    concept_net_flow = sector_flow.get('concept_net_flow', {})
    
    for cand in candidates:
        code = cand.get('code', '')
        industry = cand.get('industry', '')
        sina_industry = _map_industry_to_sina(industry)
        concept = cand.get('concept', '')  # 概念板块名
        
        # 板块层：看所属板块3日/5日净流入
        sector_layer = 0
        # 从hot_sectors获取板块多周期数据
        hot_sectors = sector_flow.get('hot_sectors', [])
        cold_sectors = sector_flow.get('cold_sectors', [])
        concept_hot = sector_flow.get('concept_hot', [])
        concept_cold = sector_flow.get('concept_cold', [])
        
        sector_found = False
        # 先在行业板块中查找
        for s in hot_sectors + cold_sectors:
            if s.get('name') == sina_industry or sina_industry in s.get('name', ''):
                d3 = s.get('d3', 0)
                d5 = s.get('d5', 0)
                if d3 > 0 and d5 > 0:
                    sector_layer = 1
                elif d3 < 0 and d5 < 0:
                    sector_layer = -1
                else:
                    sector_layer = 0
                sector_found = True
                break
        
        # 行业板块未找到，尝试概念板块
        if not sector_found and concept:
            for s in concept_hot + concept_cold:
                if concept in s.get('name', '') or s.get('name', '') in concept:
                    net = s.get('net_flow', 0)
                    if net > 0:
                        sector_layer = 1
                    elif net < 0:
                        sector_layer = -1
                    sector_found = True
                    break
        
        # 如果板块全景数据中没有，用今日净流入判断
        if not sector_found:
            # 先查行业净流入
            net = sector_net_flow.get(sina_industry, 0)
            if net > 0:
                sector_layer = 1
            elif net < 0:
                sector_layer = -1
            # 再查概念净流入（如果有）
            if concept and sector_layer == 0:
                cnet = concept_net_flow.get(concept, 0)
                if cnet > 0:
                    sector_layer = 1
                elif cnet < 0:
                    sector_layer = -1
        
        # ── 个股层 ──
        stock_layer = 0
        mp = multi_period.get(code, {})
        vals = [mp.get('3d', 0), mp.get('5d', 0), mp.get('10d', 0)]
        if all(v > 0 for v in vals):
            stock_layer = 1
        elif all(v < 0 for v in vals):
            stock_layer = -1
        
        # ── 汇总 ──
        resonance_score = market_layer + sector_layer + stock_layer
        
        if resonance_score >= 2:
            label = '🟢强共振'
        elif resonance_score == 1:
            label = '🟡偏多'
        elif resonance_score == 0:
            label = '⚪中性'
        elif resonance_score == -1:
            label = '🟠偏空'
        else:
            label = '🔴逆势'
        
        result[code] = {
            'market_layer': market_layer,
            'sector_layer': sector_layer,
            'stock_layer': stock_layer,
            'resonance_score': resonance_score,
            'label': label,
        }
        log.info(f"    {cand.get('name', code)}: 大盘{market_layer:+d} + 板块{sector_layer:+d} + 个股{stock_layer:+d} = {resonance_score} {label}")
    
    return result


# ════════════════════════════════════════════════════════
#  主线军捕获器（集成步骤）
# ════════════════════════════════════════════════════════

def step6_main_line_dragon() -> list:
    """
    主线军捕获器：扫描近期启动板块 + 识别板块内龙头
    调用 data_fetcher.get_main_line_sectors()
    """
    if not config.DRAGON_ENABLED:
        return []
    
    log.info("  [资金流弦] 第六步：主线军捕获器")
    try:
        main_lines = df.get_main_line_sectors(lookback_days=config.DRAGON_LOOKBACK_DAYS)
        log.info(f"  主线军: {len(main_lines)}个启动板块")
        return main_lines
    except Exception as e:
        log.error(f"  主线军捕获器失败: {e}")
        return []


# ════════════════════════════════════════════════════════
#  资金沉淀率综合榜单（v2.2新增）
# ════════════════════════════════════════════════════════

def build_sedimentation_rank(logic_candidates: list, multi_period: dict,
                              main_line_dragons: list) -> list:
    """
    资金沉淀率综合榜单：
    合并 逻辑链候选股 + 主线军成分股，去重后按沉淀率降序排 TOP N
    
    返回: [
        {
            'code': str, 'name': str, 'industry': str,
            'close': float, 'pct_change': float,
            'sedimentation_rate': float,
            'net_flow_3d': float,
            'source': str,  # '逻辑链' / '主线军' / '逻辑链+主线军'
            'sector': str,  # 主线军所属板块（如有）
        }, ...
    ]
    """
    if not config.SED_RANK_ENABLED:
        return []
    
    log.info("  [沉淀榜] 构建资金沉淀率综合榜单")
    
    # 用 dict 去重，key = code
    stock_map = {}
    
    # ── 来源1：逻辑链候选股（从 multi_period 中取沉淀率）──
    for cand in logic_candidates:
        code = cand.get('code', '')
        if not code:
            continue
        mp = multi_period.get(code, {})
        sed_rate = mp.get('sedimentation_rate', 0)
        if sed_rate > 0:
            stock_map[code] = {
                'code': code,
                'name': cand.get('name', ''),
                'industry': cand.get('industry', ''),
                'close': cand.get('close', 0),
                'pct_change': cand.get('pct_change', 0),
                'sedimentation_rate': sed_rate,
                'net_flow_3d': mp.get('3d', 0),
                'source': '逻辑链',
                'sector': '',
            }
    
    # ── 来源2：主线军成分股（从 leaders 中取沉淀率）──
    for sector in main_line_dragons:
        sector_name = sector.get('sector', '')
        for leader in sector.get('leaders', []):
            code = leader.get('code', '')
            if not code:
                continue
            sed_rate = leader.get('sedimentation_rate', 0)
            if sed_rate > 0:
                if code in stock_map:
                    # 已有，标记来源为两者
                    stock_map[code]['source'] = '逻辑链+主线军'
                    # 如果主线军的沉淀率更高则更新
                    if sed_rate > stock_map[code]['sedimentation_rate']:
                        stock_map[code]['sedimentation_rate'] = sed_rate
                        stock_map[code]['net_flow_3d'] = leader.get('net_flow_3d', 0)
                    if not stock_map[code]['sector']:
                        stock_map[code]['sector'] = sector_name
                else:
                    stock_map[code] = {
                        'code': code,
                        'name': leader.get('name', ''),
                        'industry': '',
                        'close': leader.get('close', 0),
                        'pct_change': leader.get('pct_change', 0),
                        'sedimentation_rate': sed_rate,
                        'net_flow_3d': leader.get('net_flow_3d', 0),
                        'source': '主线军',
                        'sector': sector_name,
                    }
    
    # 按沉淀率降序排序
    ranked = sorted(stock_map.values(), key=lambda x: x['sedimentation_rate'], reverse=True)
    ranked = ranked[:config.SED_RANK_TOP_N]
    
    log.info(f"  [沉淀榜] 合并去重{len(stock_map)}只, TOP{len(ranked)}只入榜")
    if ranked:
        log.info(f"  [沉淀榜] 榜首: {ranked[0]['name']}({ranked[0]['code']}) 沉淀率{ranked[0]['sedimentation_rate']:.1%} 来源:{ranked[0]['source']}")
    
    return ranked


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
            # 如果行业板块未匹配，尝试概念板块
            concept = cand.get('concept', '')
            concept_net = None
            if sector_net is None and concept:
                concept_net = sector_data.get('concept_net_flow', {}).get(concept, None)
                # 模糊匹配概念板块
                if concept_net is None:
                    for cname, cnet_val in sector_data.get('concept_net_flow', {}).items():
                        if concept in cname or cname in concept:
                            concept_net = cnet_val
                            break
            
            # 判断：行业或概念板块任一净流入>0即通过
            if sector_net is not None and sector_net > 0:
                pass  # 行业板块净流入，通过
            elif concept_net is not None and concept_net > 0:
                pass  # 概念板块净流入，通过
            elif sector_net is not None and sector_net <= 0 and (concept_net is None or concept_net <= 0):
                reject_reasons.append(f'{industry}({sina_industry})板块资金净流出({abs(sector_net):.2f}亿)')
            elif sector_net is None and concept_net is not None and concept_net <= 0:
                reject_reasons.append(f'{concept}概念板块资金净流出({abs(concept_net):.2f}亿)')
            elif sector_net is None and concept_net is None:
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

def run_flow_scan(logic_candidates: list = None, temperature: dict = None) -> dict:
    """
    资金流弦扫描 + AND门控 + 三层共振 + 主线军捕获
    logic_candidates: 逻辑链弦输出的候选股列表
    temperature: 市场温度数据（用于三层共振评分）
    
    返回: {
        'breath': dict,
        'index_direction': dict,
        'sector_flow': dict,
        'individual_flow': dict,
        'multi_period': dict,
        'resonance_scores': dict,
        'main_line_dragons': list,
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
    
    # 多周期资金验证（对候选股）
    multi_period = {}
    if logic_candidates:
        multi_period = step5_multi_period_flow(logic_candidates)
    
    # ── 三层共振评分（v2.2新增）──
    resonance_scores = {}
    if logic_candidates:
        resonance_scores = calc_three_layer_resonance(
            temperature=temperature,
            sector_flow=sector_flow,
            candidates=logic_candidates,
            multi_period=multi_period,
        )
    
    # ── 主线军捕获器（v2.2新增）──
    main_line_dragons = step6_main_line_dragon()
    
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
    
    # ── 资金沉淀率综合榜单（v2.2新增）──
    sedimentation_rank = build_sedimentation_rank(
        logic_candidates=logic_candidates or [],
        multi_period=multi_period,
        main_line_dragons=main_line_dragons,
    )
    
    return {
        'breath': breath,
        'index_direction': index_dir,
        'sector_flow': sector_flow,
        'individual_flow': individual_flow,
        'multi_period': multi_period,
        'resonance_scores': resonance_scores,
        'main_line_dragons': main_line_dragons,
        'sedimentation_rank': sedimentation_rank,
        'and_gate': gate_result,
    }
