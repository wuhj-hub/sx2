"""
双弦投资系统 v2.0 — 报告生成 + 推送
====================================
整合逻辑链弦 + 资金流弦 + AND门控，生成每日报告并推送
"""

import os
import json
from datetime import datetime

import config


def generate_daily_report(logic_result: dict, flow_result: dict) -> str:
    """生成双弦系统v2.0每日报告"""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    
    lines = []
    lines.append(f"# 双弦系统日报 — {date_str}")
    lines.append(f"> 生成时间: {date_str} {time_str}")
    lines.append(f"> 逻辑链弦(月线牛市+日线突破V3.0) × 资金流弦(七步复盘) → AND门控")
    lines.append("")
    
    # ── 逻辑链弦 ──────────────────────────────────────
    lines.append("## 一、逻辑链弦：月线牛市 + 日线突破")
    lines.append("")
    
    mk = logic_result.get('month_key', '')
    bull_count = logic_result.get('monthly_bull_count', 0)
    sig_count = logic_result.get('signal_count', 0)
    sig_summary = logic_result.get('signal_summary', {})
    candidates = logic_result.get('candidates', [])
    leading_ind = logic_result.get('leading_industries', [])
    
    lines.append(f"### 月线牛市状态 ({mk})")
    lines.append(f"- 月线牛市股票: **{bull_count}只**")
    lines.append("")
    
    # 领涨行业
    if leading_ind:
        lines.append("### 领涨行业排序")
        lines.append("")
        lines.append("| 排名 | 行业 | 牛市占比 |")
        lines.append("|------|------|---------|")
        for i, (ind, ratio) in enumerate(leading_ind[:10]):
            bar = '█' * int(ratio * 10) + '░' * (10 - int(ratio * 10))
            lines.append(f"| {i+1} | {ind} | {ratio:.0%} {bar} |")
        lines.append("")
    
    # 日线信号
    sig_desc = {
        'limit_up': '涨停', 'new_high_vol': '放量新高', 'new_high': '半年新高'
    }
    lines.append(f"### 日线突破信号 ({sig_count}个)")
    lines.append("")
    if sig_summary:
        for st, cnt in sig_summary.items():
            lines.append(f"- {sig_desc.get(st, st)}: {cnt}个")
    lines.append("")
    
    # 候选股列表
    if candidates:
        lines.append("### 逻辑链候选股（领涨行业优先排序）")
        lines.append("")
        lines.append("| 代码 | 名称 | 行业 | 信号类型 | 涨跌幅% | 行业牛市占比 |")
        lines.append("|------|------|------|---------|--------|------------|")
        for c in candidates:
            st_desc = sig_desc.get(c.get('signal_type', ''), c.get('signal_type', ''))
            lines.append(
                f"| {c.get('code', '')} "
                f"| {c.get('name', '')} "
                f"| {c.get('industry', '')} "
                f"| {st_desc} "
                f"| {c.get('pct_change', 0):.2f} "
                f"| {c.get('ind_bull_ratio', 0):.0%} |"
            )
        lines.append("")
    else:
        lines.append("*今日无逻辑链候选股*")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # ── 资金流弦 ──────────────────────────────────────
    lines.append("## 二、资金流弦：七步复盘")
    lines.append("")
    
    breath = flow_result.get('breath', {})
    index_dir = flow_result.get('index_direction', {})
    sector_flow = flow_result.get('sector_flow', {})
    individual_flow = flow_result.get('individual_flow', {})
    
    # 呼吸检查
    lines.append("### 1. 市场呼吸检查")
    lines.append(f"- **状态**: {breath.get('status', 'N/A')}")
    lines.append(f"- **成交额比**: {breath.get('amount_ratio', 0):.2%}")
    lines.append(f"- **操作**: {breath.get('action', 'N/A')}")
    lines.append("")
    
    # 三指数
    lines.append("### 2. 三指数方向")
    lines.append(f"- **方向**: {index_dir.get('direction', 'N/A')}")
    lines.append(f"- **判断**: {index_dir.get('action', 'N/A')}")
    lines.append("")
    
    # 板块资金流
    hot = sector_flow.get('hot_sectors', [])
    cold = sector_flow.get('cold_sectors', [])
    lines.append("### 3. 板块资金流")
    if hot:
        lines.append("")
        lines.append("**热门板块 TOP5:**")
        lines.append("")
        lines.append("| 板块 | 主力净流入(亿) | 涨跌幅(%) |")
        lines.append("|------|--------------|----------|")
        for s in hot[:5]:
            lines.append(f"| {s['name']} | {s['net_flow']:.2f} | {s['pct']:.2f} |")
        lines.append("")
    if cold:
        lines.append("**冷门板块 TOP3:**")
        lines.append("")
        for s in cold[:3]:
            lines.append(f"- {s['name']}: 净流出{abs(s['net_flow']):.2f}亿")
        lines.append("")
    
    # 个股资金流
    top_in = individual_flow.get('top_inflow', [])
    if top_in:
        lines.append("### 4. 主力净流入 TOP5")
        lines.append("")
        for s in top_in[:5]:
            lines.append(f"- {s.get('name', '')}({s.get('code', '')}): 净流入{s.get('net_flow', 0)/1e8:.2f}亿, 涨跌{s.get('pct', 0):.2f}%")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # ── AND门控 ──────────────────────────────────────
    lines.append("## 三、AND门控：两弦共振")
    lines.append("")
    
    gate = flow_result.get('and_gate', {})
    gate_summary = gate.get('gate_summary', {})
    gated = gate.get('gated_candidates', [])
    rejected = gate.get('rejected_candidates', [])
    
    lines.append(f"### 门控状态")
    lines.append(f"- 市场门控: {'✅ 通过' if gate_summary.get('market_ok') else '❌ 冷区'}")
    lines.append(f"- 逻辑链候选: {gate_summary.get('total_candidates', 0)}只")
    lines.append(f"- 两弦共振: **{gate_summary.get('gated_count', 0)}只** ✅")
    lines.append(f"- 未通过: {gate_summary.get('rejected_count', 0)}只 ❌")
    lines.append("")
    
    # 共振候选股
    if gated:
        lines.append("### 🎯 两弦共振候选股（可操作）")
        lines.append("")
        lines.append("| 代码 | 名称 | 行业 | 信号 | 涨跌幅% | 行业牛市占比 | 板块净流入 | 个股净流入 |")
        lines.append("|------|------|------|-----|--------|------------|----------|----------|")
        sig_desc = {'limit_up': '涨停', 'new_high_vol': '放量新高', 'new_high': '半年新高'}
        for c in gated:
            st_desc = sig_desc.get(c.get('signal_type', ''), c.get('signal_type', ''))
            ind_flow = c.get('individual_net_flow')
            ind_flow_str = f"{ind_flow/1e8:.2f}亿" if ind_flow is not None else 'N/A'
            sec_flow = c.get('sector_net_flow', 0)
            lines.append(
                f"| {c.get('code', '')} "
                f"| {c.get('name', '')} "
                f"| {c.get('industry', '')} "
                f"| {st_desc} "
                f"| {c.get('pct_change', 0):.2f} "
                f"| {c.get('ind_bull_ratio', 0):.0%} "
                f"| {sec_flow:.2f}亿 "
                f"| {ind_flow_str} |"
            )
        lines.append("")
        
        # 操作建议
        lines.append("### 📋 操作建议")
        lines.append("")
        for c in gated:
            name = c.get('name', c.get('code', ''))
            st = sig_desc.get(c.get('signal_type', ''), '')
            industry = c.get('industry', '')
            lines.append(f"- **{name}** ({st}, {industry}):")
            lines.append(f"  - 买入价: 次日开盘价（T+1执行）")
            lines.append(f"  - 止损: MA20保底 + 最高点回撤8%移动止盈")
            lines.append(f"  - 退出: 月线转熊 或 最长持有60日")
        lines.append("")
    else:
        lines.append("*今日无两弦共振候选股 — 不操作*")
        lines.append("")
        if rejected:
            lines.append("### 未通过门控的候选股")
            lines.append("")
            for c in rejected[:5]:
                name = c.get('name', c.get('code', ''))
                reasons = ', '.join(c.get('reject_reasons', []))
                lines.append(f"- {name}: {reasons}")
            lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # ── 方法论 ──────────────────────────────────────
    lines.append("## 📌 双弦系统方法论")
    lines.append("")
    lines.append("> **逻辑链弦**: 月线牛市定方向 + 领涨行业优先 + 日线突破定入场")
    lines.append("> **资金流弦**: 市场非冷区 + 板块资金正流入 + 个股主力正流入")
    lines.append("> **AND门控**: 两弦信号对齐才操作，缺一不可")
    lines.append("> **止损**: MA20保底 + 8%移动止盈 + 月线转熊退出 + 60日最长持有")
    lines.append("")
    lines.append("*本报告由双弦投资系统v2.0自动生成，不构成投资建议。*")
    
    # 保存
    output_dir = config.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{config.REPORT_PREFIX}_{date_str.replace('-', '')}.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return filepath


def generate_push_content(logic_result: dict, flow_result: dict) -> tuple:
    """
    生成推送内容（标题 + 正文）
    返回: (title, content)
    """
    date_str = datetime.now().strftime('%Y-%m-%d')
    gate = flow_result.get('and_gate', {})
    gated = gate.get('gated_candidates', [])
    breath = flow_result.get('breath', {})
    gate_summary = gate.get('gate_summary', {})
    
    sig_desc = {'limit_up': '涨停', 'new_high_vol': '放量新高', 'new_high': '半年新高'}
    
    if breath.get('status') == '冷区':
        title = f"🚨 双弦日报 — 冷区不动"
    elif gated:
        names = [c.get('name', c.get('code', '')) for c in gated[:5]]
        title = f"🎯 双弦共振 — {len(gated)}只可操作 ({', '.join(names)})"
    else:
        title = f"📊 双弦日报 — 无共振信号"
    
    # 正文
    lines = []
    lines.append(f"**{date_str} 双弦系统日报**")
    lines.append("")
    
    # 逻辑链摘要
    bull_count = logic_result.get('monthly_bull_count', 0)
    sig_count = logic_result.get('signal_count', 0)
    sig_summary = logic_result.get('signal_summary', {})
    leading_ind = logic_result.get('leading_industries', [])[:5]
    
    lines.append(f"**逻辑链**: 月线牛市{bull_count}只, 日线信号{sig_count}个")
    if sig_summary:
        parts = [f"{sig_desc.get(k,k)}{v}个" for k, v in sig_summary.items()]
        lines.append(f"  信号: {', '.join(parts)}")
    if leading_ind:
        ind_str = ', '.join([f"{ind}{r:.0%}" for ind, r in leading_ind[:5]])
        lines.append(f"  领涨: {ind_str}")
    lines.append("")
    
    # 资金流摘要
    lines.append(f"**资金流**: 市场{breath.get('status', 'N/A')}, 成交额比{breath.get('amount_ratio', 0):.2%}")
    hot = flow_result.get('sector_flow', {}).get('hot_sectors', [])[:3]
    if hot:
        lines.append(f"  热门: {', '.join([s['name'] for s in hot])}")
    lines.append("")
    
    # AND门控结果
    lines.append(f"**AND门控**: 共振{gate_summary.get('gated_count', 0)}只, 未通过{gate_summary.get('rejected_count', 0)}只")
    lines.append("")
    
    if gated:
        lines.append("**🎯 共振候选股:**")
        for c in gated:
            st = sig_desc.get(c.get('signal_type', ''), '')
            lines.append(f"  - {c.get('name', c.get('code', ''))} | {st} | {c.get('industry', '')} | 涨跌{c.get('pct_change', 0):.1f}%")
        lines.append("")
        lines.append("⚠️ 次日开盘价买入(T+1), MA20止损+8%移动止盈+月线转熊退出")
    else:
        lines.append("今日无共振信号，不操作。")
    
    content = '\n'.join(lines)
    return title, content
