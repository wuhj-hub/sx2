"""
资金流实盘复盘脚本 — 报告生成
==================================
将七步复盘、六层滤网、三重确认的结果合并为 Markdown 日报。
"""

import os
from datetime import datetime

import config


def generate_report(step_results: dict, filter_results: dict,
                    confirm_results: dict, output_dir: str = None) -> str:
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    lines = []
    lines.append(f"# 资金流实盘日报 — {date_str}")
    lines.append(f"> 生成时间: {date_str} {time_str}")
    lines.append(f"> 方法论: 七步复盘SOP + 六层滤网 + 三重确认")
    lines.append("")
    step1 = step_results.get('step1', {})
    if step1.get('alert'):
        lines.append("## 🚨 核心提醒")
        lines.append("")
        lines.append(f"**{step1['alert']}**")
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("## 一、七步复盘")
    lines.append("")
    lines.append("### 1. 全市场呼吸检查")
    lines.append("")
    lines.append(f"- **状态**: {step1.get('status', 'N/A')}")
    lines.append(f"- **今日成交额**: {step1.get('today_amount', 0):,.0f}")
    lines.append(f"- **20日均值**: {step1.get('avg20_amount', 0):,.0f}")
    lines.append(f"- **比值**: {step1.get('amount_ratio', 0):.2%}")
    lines.append(f"- **操作**: {step1.get('action', 'N/A')}")
    lines.append("")
    step2 = step_results.get('step2', {})
    lines.append("### 2. 三指数方向判断")
    lines.append("")
    lines.append(f"- **方向**: {step2.get('direction', 'N/A')}")
    lines.append(f"- **操作**: {step2.get('action', 'N/A')}")
    indices = step2.get('indices')
    if indices is not None and not indices.empty:
        lines.append("")
        lines.append("| 日期 | 上证收盘 | 上证涨跌 | 深证收盘 | 深证涨跌 | 全A替代收盘 | 全A替代涨跌 |")
        lines.append("|------|---------|---------|---------|---------|-----------|-----------|")
        for _, row in indices.tail(3).iterrows():
            lines.append(
                f"| {row.get('日期', '')} "
                f"| {row.get('上证收盘', 0):.2f} "
                f"| {row.get('上证涨跌', 0):.2%} "
                f"| {row.get('深证收盘', 0):.2f} "
                f"| {row.get('深证涨跌', 0):.2%} "
                f"| {row.get('全A替代收盘', 0):.2f} "
                f"| {row.get('全A替代涨跌', 0):.2%} |"
            )
    lines.append("")
    step3 = step_results.get('step3', {})
    lines.append("### 3. ETF申赎检查")
    lines.append("")
    lines.append(f"- {step3.get('summary', '无数据')}")
    signals = step3.get('signals', [])
    if signals:
        for s in signals[:5]:
            lines.append(f"  - {s}")
    lines.append("")
    step4 = step_results.get('step4', {})
    lines.append("### 4. 板块资金流热力图")
    lines.append("")
    hot = step4.get('hot_sectors', [])
    cold = step4.get('cold_sectors', [])
    if hot:
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
        lines.append("| 板块 | 主力净流出(亿) | 涨跌幅(%) |")
        lines.append("|------|--------------|----------|")
        for s in cold[:3]:
            lines.append(f"| {s['name']} | {s['net_flow']:.2f} | {s['pct']:.2f} |")
        lines.append("")
    warnings = step4.get('warnings', [])
    if warnings:
        lines.append("**预警:**")
        for w in warnings[:3]:
            lines.append(f"- {w}")
        lines.append("")
    step5 = step_results.get('step5', {})
    lines.append("### 5. 个股资金流扫描")
    lines.append("")
    watch = step5.get('watch_list', [])
    top_in = step5.get('top_inflow', [])
    if watch:
        lines.append("**⚠️ 资金流减速警惕:**")
        lines.append("")
        for s in watch[:5]:
            lines.append(f"- {s.get('name', '')}({s.get('code', '')}): 净流入{s.get('net_flow', 0):.2f}亿, 加速度{s.get('accel', 0):.2f}")
        lines.append("")
    if top_in:
        lines.append("**主力净流入 TOP5:**")
        lines.append("")
        for s in top_in[:5]:
            lines.append(f"- {s.get('name', '')}({s.get('code', '')}): 净流入{s.get('net_flow', 0):.2f}亿, 涨跌{s.get('pct', 0):.2f}%")
        lines.append("")
    step6 = step_results.get('step6', {})
    lines.append("### 6. 融资融券异常扫描")
    lines.append("")
    anomaly = step6.get('total_anomaly', False)
    lines.append(f"- **总量异常**: {'⚠️ 是' if anomaly else '否'}")
    detail = step6.get('total_detail', {})
    if detail:
        lines.append(f"  - 今日融资余额: {detail.get('today_balance', 0):,.0f}")
        lines.append(f"  - 日变化: {detail.get('today_change', 0):,.0f}")
        lines.append(f"  - 20日均值变化: {detail.get('mean_change', 0):,.0f}")
    divs = step6.get('stock_divergence', [])
    if divs:
        lines.append("- **个股背离(价格新高+融资下降):**")
        for d in divs[:5]:
            lines.append(f"  - {d}")
    lines.append("")
    step7 = step_results.get('step7', {})
    lines.append("### 7. 三句话复盘小结")
    lines.append("")
    lines.append(f"1. **市场态度**: {step7.get('market_attitude', 'N/A')}")
    lines.append(f"2. **关键信号**: {step7.get('key_signal', 'N/A')}")
    lines.append(f"3. **明日操作**: {step7.get('tomorrow_action', 'N/A')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、六层滤网筛选")
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
        lines.append("| 代码 | 名称 | 涨跌幅% | 净流入 | 市值(亿) | 换手率 | 标记 |")
        lines.append("|------|------|--------|-------|---------|-------|------|")
        for c in candidates:
            flags = ', '.join(c.get('flags', []))
            if not flags:
                flags = c.get('human_check', '')
            lines.append(
                f"| {c.get('code', '')} "
                f"| {c.get('name', '')} "
                f"| {c.get('pct', 0):.2f} "
                f"| {c.get('net_flow', 0):.2f} "
                f"| {c.get('market_cap', '-')} "
                f"| {c.get('turnover', '-')} "
                f"| {flags} |"
            )
        lines.append("")
    else:
        lines.append("*今日无候选标的通过六层滤网*")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 三、三重确认择时")
    lines.append("")
    c1 = confirm_results.get('confirm1', {})
    c2 = confirm_results.get('confirm2', {})
    c3 = confirm_results.get('confirm3', {})
    lines.append(f"| 确认维度 | 结果 | 详情 |")
    lines.append(f"|---------|------|------|")
    lines.append(f"| 第一重: 全市场资金流 | {'✅ 通过' if c1.get('pass') else '❌ 不通过'} | {c1.get('detail', '')} |")
    lines.append(f"| 第二重: 机构资金方向 | {'✅ 通过' if c2.get('pass') else '❌ 不通过'} | {c2.get('detail', '')} |")
    lines.append(f"| 第三重: 微观资金结构 | {'✅ 通过' if c3.get('pass') else '❌ 不通过'} | {c3.get('detail', '')} |")
    lines.append("")
    if confirm_results.get('all_pass'):
        lines.append("**🎯 三重确认全部通过，可果断调整仓位**")
    else:
        lines.append("**三重确认未全部通过，不调整仓位**")
    lines.append(f"- 操作建议: {confirm_results.get('action', '不调整仓位')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📌 方法论提醒")
    lines.append("")
    lines.append("> **慢** — 任何信号出来后，多等一天。避免大多数陷阱，平均年化多赚3-5个百分点。")
    lines.append("> **规则** — 三重确认、六层滤网、七步复盘，雷打不动。规则亮绿灯前，绝不动手。")
    lines.append("")
    lines.append("*本报告由资金流实盘复盘脚本自动生成，不构成投资建议。*")
    if output_dir is None:
        output_dir = config.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{config.REPORT_PREFIX}_{date_str.replace('-', '')}.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return filepath


def generate_cold_alert(step1: dict) -> str:
    if step1.get('status') == '冷区':
        return (
            "🚨 冷区预警\n"
            f"今日成交额/20日均值 = {step1.get('amount_ratio', 0):.2%}\n"
            "冷区。今日没有信号触发。按规则不动。"
        )
    return ""
