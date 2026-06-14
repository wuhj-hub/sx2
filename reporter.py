"""
双弦投资系统 — 报告生成
==================================
将七步复盘、六层滤网、三重确认、逻辑链候选池、A/B/C分级、持仓里程碑等
合并为完整的双弦系统日报。
"""

import os
from datetime import datetime
from typing import Dict, List

import config


def generate_report(step_results: Dict,
                  filter_results: Dict,
                  confirm_results: Dict,
                  grading_result: Dict,
                  circuit_results: List[Dict],
                  output_dir: str = None) -> str:
    """生成完整的双弦系统日报"""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    
    lines = []
    
    # 头部
    lines.append(f"# 双弦投资系统日报 — {date_str}")
    lines.append(f"> 生成时间: {date_str} {time_str}")
    lines.append(f"> 核心理念: 逻辑链(买什么) + 资金流(何时买) = 双线AND门控")
    lines.append("")
    
    # 系统状态概览
    system_status = _get_system_status(step_results, confirm_results, circuit_results)
    lines.append("## 📊 系统状态概览")
    lines.append("")
    lines.append(f"- **当前阶段**: {system_status['stage']}")
    lines.append(f"- **市场态度**: {step_results.get('step7', {}).get('market_attitude', 'N/A')}")
    lines.append(f"- **三重确认**: {'✅ 全部通过' if confirm_results.get('all_pass') else '❌ 未全部通过'}")
    
    # 熔断状态
    if circuit_results:
        hard_count = sum(1 for r in circuit_results if r['circuit_result']['status'] == 'hard')
        soft_count = sum(1 for r in circuit_results if r['circuit_result']['status'] == 'soft')
        if hard_count > 0:
            lines.append(f"- **熔断状态**: 🔴 {hard_count}只硬熔断, 🟡 {soft_count}只软熔断")
        elif soft_count > 0:
            lines.append(f"- **熔断状态**: 🟡 {soft_count}只软熔断")
        else:
            lines.append(f"- **熔断状态**: 🟢 全部正常")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 一、七步复盘
    lines.append("## 一、七步复盘 SOP")
    lines.append("")
    lines.append(_format_step1(step_results.get('step1', {})))
    lines.append("")
    lines.append(_format_step2(step_results.get('step2', {})))
    lines.append("")
    lines.append(_format_step4(step_results.get('step4', {})))
    lines.append("")
    lines.append(_format_step5(step_results.get('step5', {})))
    lines.append("")
    lines.append("### 复盘小结")
    lines.append("")
    step7 = step_results.get('step7', {})
    lines.append(f"1. **市场态度**: {step7.get('market_attitude', 'N/A')}")
    lines.append(f"2. **关键信号**: {step7.get('key_signal', 'N/A')}")
    lines.append(f"3. **明日操作**: {step7.get('tomorrow_action', 'N/A')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 二、逻辑链候选池
    lines.append("## 二、逻辑链候选池")
    lines.append("")
    lines.append(_format_logic_pool(grading_result))
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 三、A/B/C级标的分级
    lines.append("## 三、标的分级结果")
    lines.append("")
    lines.append(_format_grading(grading_result))
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 四、六层滤网筛选
    lines.append("## 四、资金流候选池 (六层滤网)")
    lines.append("")
    notes = filter_results.get('notes', [])
    if notes:
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")
    candidates = filter_results.get('candidates', [])
    if candidates:
        lines.append("**候选标的:**")
        lines.append("")
        lines.append("| 代码 | 名称 | 涨跌幅% | 净流入 | 标记 |")
        lines.append("|------|------|--------|-------|------|")
        for c in candidates[:10]:
            flags = ', '.join(c.get('flags', [])) or c.get('human_check', '')
            lines.append(
                f"| {c.get('code', '')} "
                f"| {c.get('name', '')} "
                f"| {c.get('pct', 0):.2f} "
                f"| {c.get('net_flow', 0):.2f} "
                f"| {flags} |"
            )
        lines.append("")
    else:
        lines.append("*今日无候选标的通过六层滤网*")
        lines.append("")
    lines.append("---")
    lines.append("")
    
    # 五、三重确认择时
    lines.append("## 五、三重确认择时")
    lines.append("")
    lines.append(_format_triple_confirm(confirm_results))
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 六、持仓里程碑状态
    lines.append("## 六、持仓里程碑+熔断状态")
    lines.append("")
    if circuit_results:
        lines.append(_format_circuit_status(circuit_results))
    else:
        lines.append("*暂无持仓数据*")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 七、操作建议
    lines.append("## 七、操作建议")
    lines.append("")
    lines.append(_format_action_suggestions(grading_result, circuit_results, confirm_results))
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 方法论提醒
    lines.append("## 📌 方法论提醒")
    lines.append("")
    lines.append("> **双弦AND门控**: 逻辑链(买什么) × 资金流(何时买)，两个条件都满足才动手。")
    lines.append("> **慢**: 任何信号出来后，多等一天。避免大多数陷阱。")
    lines.append("> **规则**: 三重确认、六层滤网、七步复盘、熔断机制，雷打不动。")
    lines.append("")
    lines.append("*本报告由双弦投资系统自动生成，不构成投资建议。*")
    
    # 保存报告
    if output_dir is None:
        output_dir = config.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"{config.REPORT_PREFIX}_{date_str.replace('-', '')}.md"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return filepath


def _get_system_status(step_results: Dict, confirm_results: Dict, 
                       circuit_results: List[Dict]) -> Dict:
    """获取系统状态"""
    step1 = step_results.get('step1', {})
    step7 = step_results.get('step7', {})
    all_pass = confirm_results.get('all_pass', False)
    
    hard_count = sum(1 for r in circuit_results if r['circuit_result']['status'] == 'hard')
    soft_count = sum(1 for r in circuit_results if r['circuit_result']['status'] == 'soft')
    
    if hard_count > 0:
        stage = "stage4_defense"
        stage_name = "🔴 防御期 (硬熔断)"
    elif soft_count > 0:
        stage = "stage4_defense"
        stage_name = "🟡 防御期 (软熔断)"
    elif step1.get('status') == '冷区':
        stage = "stage1_watch"
        stage_name = "🟢 观望期 (冷区)"
    elif all_pass:
        stage = "stage3_action"
        stage_name = "🎯 行动期 (三重确认通过)"
    elif step7.get('market_attitude') == '积极':
        stage = "stage2_prepare"
        stage_name = "👀 准备期 (积极信号)"
    else:
        stage = "stage1_watch"
        stage_name = "👀 观望期"
    
    return {'stage': stage, 'stage_name': stage_name}


def _format_step1(step1: dict) -> str:
    """格式化第一步结果"""
    lines = []
    lines.append(f"### 1. 全市场呼吸检查")
    lines.append("")
    lines.append(f"- **状态**: {step1.get('status', 'N/A')}")
    lines.append(f"- **成交额比**: {step1.get('amount_ratio', 0):.2%}")
    lines.append(f"- **操作**: {step1.get('action', 'N/A')}")
    if step1.get('alert'):
        lines.append(f"- **⚠️ 预警**: {step1['alert']}")
    return '\n'.join(lines)


def _format_step2(step2: dict) -> str:
    """格式化第二步结果"""
    lines = []
    lines.append(f"### 2. 三指数方向判断")
    lines.append("")
    lines.append(f"- **方向**: {step2.get('direction', 'N/A')}")
    lines.append(f"- **操作**: {step2.get('action', 'N/A')}")
    return '\n'.join(lines)


def _format_step4(step4: dict) -> str:
    """格式化第四步结果"""
    lines = []
    lines.append(f"### 3. 板块资金流")
    lines.append("")
    hot = step4.get('hot_sectors', [])
    if hot:
        lines.append("**热门板块 TOP5:**")
        lines.append("")
        lines.append("| 板块 | 净流入(亿) | 涨跌幅% |")
        lines.append("|------|----------|---------|")
        for s in hot[:5]:
            lines.append(f"| {s['name']} | {s['net_flow']:.2f} | {s['pct']:.2f} |")
        lines.append("")
    return '\n'.join(lines)


def _format_step5(step5: dict) -> str:
    """格式化第五步结果"""
    lines = []
    lines.append(f"### 4. 个股资金流")
    lines.append("")
    top_in = step5.get('top_inflow', [])
    if top_in:
        lines.append("**主力净流入 TOP5:**")
        lines.append("")
        for s in top_in[:5]:
            lines.append(f"- {s.get('name', '')}({s.get('code', '')}): {s.get('net_flow', 0):.2f}亿, {s.get('pct', 0):.2f}%")
        lines.append("")
    return '\n'.join(lines)


def _format_logic_pool(grading_result: Dict) -> str:
    """格式化逻辑链候选池"""
    summary = grading_result.get('summary', {})
    grade_a = grading_result.get('grade_a', [])
    grade_b = grading_result.get('grade_b', [])
    grade_c = grading_result.get('grade_c', [])
    
    lines = []
    lines.append(f"- 逻辑链池总计: {summary.get('total_logic_pool', 0)} 只")
    lines.append(f"- 资金流池总计: {summary.get('total_capital_pool', 0)} 只")
    lines.append(f"- 分级结果: A级{len(grade_a)}只, B级{len(grade_b)}只, C级{len(grade_c)}只")
    lines.append("")
    
    # 高优先级标的（国产化率低+专精特新）
    priority = [s for s in grade_a + grade_b 
                if s.get('localization_rate', 1) < 0.7 and s.get('specialized')]
    if priority:
        lines.append("**🎯 高优先级标的 (国产化率<70% + 专精特新):**")
        lines.append("")
        for s in priority[:5]:
            rate = s.get('localization_rate', 0)
            lines.append(f"- {s.get('code')} {s.get('name')} | {s.get('sector')} | 国产化率: {rate:.0%}")
        lines.append("")
    
    return '\n'.join(lines)


def _format_grading(grading_result: Dict) -> str:
    """格式化分级结果"""
    lines = []
    
    grade_a = grading_result.get('grade_a', [])
    grade_b = grading_result.get('grade_b', [])
    grade_c = grading_result.get('grade_c', [])
    
    # A级
    if grade_a:
        lines.append("**🎯 A级 (逻辑链+资金流共振):**")
        lines.append("")
        lines.append("| 代码 | 名称 | 赛道 | 国产化率 |")
        lines.append("|------|------|------|---------|")
        for s in grade_a:
            rate = s.get('localization_rate', 'N/A')
            if isinstance(rate, float):
                rate = f"{rate:.0%}"
            lines.append(f"| {s.get('code', '')} | {s.get('name', '')} | {s.get('sector', 'N/A')} | {rate} |")
        lines.append("")
    
    # B级
    if grade_b:
        lines.append("**👀 B级 (逻辑链确认,等待资金信号):**")
        lines.append("")
        for s in grade_b:
            rate = s.get('localization_rate', 0)
            lines.append(f"- {s.get('code')} {s.get('name')} | 国产化率: {rate:.0%}")
        lines.append("")
    
    # C级
    if grade_c:
        lines.append("**⚠️ C级 (资金流确认,需逻辑初判):**")
        lines.append("")
        for s in grade_c:
            need_check = s.get('need_logic_check', False)
            deadline = s.get('logic_check_deadline', 'N/A')
            lines.append(f"- {s.get('code')} {s.get('name')} | 需逻辑初判: {need_check} | 截止: {deadline[:10] if deadline else 'N/A'}")
        lines.append("")
    
    return '\n'.join(lines)


def _format_triple_confirm(confirm_results: Dict) -> str:
    """格式化三重确认结果"""
    lines = []
    
    c1 = confirm_results.get('confirm1', {})
    c2 = confirm_results.get('confirm2', {})
    c3 = confirm_results.get('confirm3', {})
    
    lines.append("| 确认维度 | 结果 | 详情 |")
    lines.append("|---------|------|------|")
    lines.append(f"| 第一重: 全市场资金流 | {'✅ 通过' if c1.get('pass') else '❌ 不通过'} | {c1.get('detail', '')} |")
    lines.append(f"| 第二重: 机构资金方向 | {'✅ 通过' if c2.get('pass') else '❌ 不通过'} | {c2.get('detail', '')} |")
    lines.append(f"| 第三重: 微观资金结构 | {'✅ 通过' if c3.get('pass') else '❌ 不通过'} | {c3.get('detail', '')} |")
    lines.append("")
    
    if confirm_results.get('all_pass'):
        lines.append("**🎯 三重确认全部通过，可果断调整仓位**")
    else:
        lines.append("**三重确认未全部通过，不调整仓位**")
    
    return '\n'.join(lines)


def _format_circuit_status(circuit_results: List[Dict]) -> str:
    """格式化熔断状态"""
    lines = []
    
    for r in circuit_results:
        p = r['position']
        cr = r['circuit_result']
        status = cr.get('status', 'normal')
        status_emoji = {'hard': '🔴', 'soft': '🟡', 'normal': '🟢'}.get(status, '⚪')
        
        lines.append(f"**{status_emoji} {p.get('name')}({p.get('code')})**")
        lines.append(f"- 持仓比例: {p.get('position_ratio', 0):.0%}")
        lines.append(f"- 买入价: {p.get('buy_price')} | 现价: {p.get('current_price', 'N/A')}")
        
        if cr.get('reason'):
            lines.append(f"- 状态原因:")
            for reason in cr['reason']:
                lines.append(f"  - {reason}")
        
        if cr.get('action'):
            lines.append(f"- **建议操作**: {cr['action'].get('message', '')}")
        
        lines.append("")
    
    return '\n'.join(lines)


def _format_action_suggestions(grading_result: Dict, 
                               circuit_results: List[Dict],
                               confirm_results: Dict) -> str:
    """格式化操作建议"""
    lines = []
    
    # 根据系统状态给出建议
    hard_positions = [r for r in circuit_results if r['circuit_result']['status'] == 'hard']
    soft_positions = [r for r in circuit_results if r['circuit_result']['status'] == 'soft']
    
    if hard_positions:
        lines.append("**🔴 紧急 - 硬熔断持仓:**")
        for r in hard_positions:
            p = r['position']
            lines.append(f"- {p.get('name')}: 建议减仓50%，3日内清仓")
        lines.append("")
    
    if soft_positions:
        lines.append("**🟡 注意 - 软熔断持仓:**")
        for r in soft_positions:
            p = r['position']
            lines.append(f"- {p.get('name')}: 冻结加仓，观察")
        lines.append("")
    
    # A级标的建议
    grade_a = grading_result.get('grade_a', [])
    if grade_a and confirm_results.get('all_pass'):
        lines.append("**🎯 可建仓A级标的 (三重确认通过):**")
        for s in grade_a:
            lines.append(f"- {s.get('code')} {s.get('name')} | {s.get('sector')}")
        lines.append("")
    
    # B级标的建议
    grade_b = grading_result.get('grade_b', [])
    if grade_b:
        lines.append("**👀 观察B级标的 (等待资金信号):**")
        for s in grade_b[:5]:
            lines.append(f"- {s.get('code')} {s.get('name')}")
        lines.append("")
    
    return '\n'.join(lines)


def generate_simple_report(step_results: Dict, grading_result: Dict) -> str:
    """生成简洁报告（三句话版本）"""
    step7 = step_results.get('step7', {})
    grade_a = grading_result.get('grade_a', [])
    
    lines = [
        f"📊 市场态度：{step7.get('market_attitude', '未知')}",
        f"📌 关键信号：{step7.get('key_signal', '无')}",
        f"📋 明日操作：{step7.get('tomorrow_action', '无')}",
    ]
    
    if grade_a:
        names = [s.get('name') for s in grade_a[:3]]
        lines.append(f"🎯 A级标的：{', '.join(names)}")
    
    return '\n'.join(lines)
