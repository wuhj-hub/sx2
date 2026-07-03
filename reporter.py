"""
双弦投资系统 v2.1 — 报告生成 + 推送
====================================
整合逻辑链弦 + 资金流弦 + 市场温度计 + 板块资金全景 + 多周期资金验证
AND门控：两弦信号对齐才推送操作信号
"""

import os
import json
import logging
from datetime import datetime

import config

log = logging.getLogger("shuangxian.reporter")


def _filter_by_price(items: list, max_price: float = None) -> list:
    """按收盘价筛选 ≤ max_price 的股票"""
    if max_price is None:
        max_price = config.MAX_PRICE
    if max_price <= 0:
        return items  # 0 或负数表示不限制
    return [item for item in items if item.get('close', 0) > 0 and item.get('close', 0) <= max_price]


def _format_flow_yi(val):
    """格式化资金流数值为亿元显示"""
    if val is None:
        return "N/A"
    return f"{val/1e8:.2f}亿" if abs(val) >= 1e8 else f"{val/1e4:.1f}万"


def generate_daily_report(logic_result: dict, flow_result: dict, temperature: dict = None) -> str:
    """生成双弦系统v2.1每日报告"""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    
    lines = []
    lines.append(f"# 双弦系统日报 — {date_str}")
    lines.append(f"> 生成时间: {date_str} {time_str}")
    lines.append(f"> 逻辑链弦(月线牛市+日线突破V3.0+底背离买点) × 资金流弦(七步复盘+板块全景+多周期验证+三层共振+主线军) → AND门控")
    lines.append("")
    
    # ── 市场温度计 ──────────────────────────────────────
    if temperature and temperature.get('score') is not None:
        score = temperature['score']
        emoji = temperature.get('emoji', '')
        zone = temperature.get('zone', '')
        sub = temperature.get('sub_scores', {})
        
        lines.append(f"## 🌡️ 市场温度：{score}/100 {emoji} {zone}")
        lines.append("")
        if sub:
            sub_parts = [f"{k}+{v}" for k, v in sub.items()]
            lines.append(f"  动量{sub.get('动量',0)} | 量能{sub.get('量能',0)} | MACD{sub.get('MACD',0)} | 短期{sub.get('短期趋势',0)} | 中期{sub.get('中期趋势',0)}")
            lines.append("")
            # 补充参考数据
            extras = []
            if temperature.get('deviation') is not None:
                extras.append(f"MA20偏离 {temperature['deviation']:+.1f}%")
            if temperature.get('vol_ratio') is not None:
                extras.append(f"量比 {temperature['vol_ratio']:.2f}")
            if temperature.get('ret_5d') is not None:
                extras.append(f"5日涨跌 {temperature['ret_5d']:+.1f}%")
            if temperature.get('ret_20d') is not None:
                extras.append(f"20日涨跌 {temperature['ret_20d']:+.1f}%")
            if extras:
                lines.append(f"  {'  |  '.join(extras)}")
                lines.append("")
        
        # 温度提示
        if score >= 80:
            lines.append("> 🔥 市场过热，注意追高风险，谨慎追涨")
        elif score >= 60:
            lines.append("> ☀️ 市场趋势良好，可按信号正常操作")
        elif score >= 40:
            lines.append("> 🌤️ 市场结构性行情，精选个股、控制仓位")
        elif score >= 20:
            lines.append("> 🌧️ 市场偏弱，谨慎操作，轻仓为主")
        else:
            lines.append("> 🧊 市场冰点，逆向思维者可关注超跌机会")
        lines.append("")
        lines.append("---")
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
    
    # 价格筛选
    candidates = _filter_by_price(candidates)
    
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
    
    # 候选股列表（含多周期资金验证+沉淀率+三层共振列）
    multi_period = flow_result.get('multi_period', {})
    resonance_scores = flow_result.get('resonance_scores', {})
    
    if candidates:
        lines.append("### 逻辑链候选股（领涨行业优先排序）")
        lines.append("")
        lines.append("| 代码 | 名称 | 行业 | 信号类型 | 现价 | 涨跌幅% | 行业牛市占比 | 共振分 | 沉淀率 | 资金验证 |")
        lines.append("|------|------|------|---------|------|--------|------------|--------|--------|----------|")
        for c in candidates:
            st_desc = sig_desc.get(c.get('signal_type', ''), c.get('signal_type', ''))
            code = c.get('code', '')
            mp = multi_period.get(code, {})
            mp_signal = mp.get('signal', '')
            # 资金验证摘要
            mp_str = f"3D:{_format_flow_yi(mp.get('3d', 0))} 5D:{_format_flow_yi(mp.get('5d', 0))} 20D:{_format_flow_yi(mp.get('20d', 0))} {mp_signal}"
            # 沉淀率
            sed_rate = mp.get('sedimentation_rate', 0)
            sed_str = f"{sed_rate:.1%}" if sed_rate > 0 else "N/A"
            # 三层共振分
            res = resonance_scores.get(code, {})
            res_str = f"{res.get('resonance_score', 0):+d} {res.get('label', '')}"
            
            lines.append(
                f"| {code} "
                f"| {c.get('name', '')} "
                f"| {c.get('industry', '')} "
                f"| {st_desc} "
                f"| {c.get('close', 0):.2f} "
                f"| {c.get('pct_change', 0):.2f} "
                f"| {c.get('ind_bull_ratio', 0):.0%} "
                f"| {res_str} "
                f"| {sed_str} "
                f"| {mp_str} |"
            )
        lines.append("")
    else:
        lines.append("*今日无逻辑链候选股*")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # ── 底背离买点 ──────────────────────────────────────
    divergence_signals = logic_result.get('divergence_signals', [])
    div_count = logic_result.get('divergence_count', 0)
    
    lines.append("## 二、底背离买点信号")
    lines.append("")
    # 价格筛选
    divergence_signals = _filter_by_price(divergence_signals)
    if divergence_signals:
        lines.append(f"在月线牛市股票中发现 **{len(divergence_signals)}只** 出现日线MACD底背离（趋势回踩买点，股价≤{config.MAX_PRICE}元）：")
        lines.append("")
        lines.append("| 代码 | 名称 | 行业 | 背离低点日期 | 现价 | 前低 | 当前低 | 回升% | 间距(天) | 行业牛市占比 |")
        lines.append("|------|------|------|------------|------|------|--------|-------|---------|------------|")
        for d in divergence_signals:
            lines.append(
                f"| {d.get('code', '')} "
                f"| {d.get('name', '')} "
                f"| {d.get('industry', '')} "
                f"| {d.get('date', '')} "
                f"| {d.get('close', 0):.2f} "
                f"| {d.get('prev_low', 0):.2f} "
                f"| {d.get('divergence_low', 0):.2f} "
                f"| {d.get('recovery_pct', 0):.1f}% "
                f"| {d.get('gap_days', 0)} "
                f"| {d.get('ind_bull_ratio', 0):.0%} |"
            )
        lines.append("")
        lines.append("> 💡 底背离 = 价格创新低但MACD未新低，下跌动能衰竭，叠加月线牛市背景 → 趋势回踩买点")
    else:
        lines.append("*今日无底背离信号*")
    lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # ── 资金流弦 ──────────────────────────────────────
    lines.append("## 三、资金流弦：七步复盘 + 板块全景")
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
    
    # ── 板块资金全景（新功能）──
    heatmap_df = sector_flow.get('heatmap')
    hot = sector_flow.get('hot_sectors', [])
    cold = sector_flow.get('cold_sectors', [])
    
    if heatmap_df is not None and not heatmap_df.empty:
        # 多周期全景模式
        lines.append("### 3. 板块资金全景（多周期控盘度排序）")
        lines.append("")
        lines.append("**🔥 资金流入 TOP 板块：**")
        lines.append("")
        lines.append("| 排名 | 板块 | 今日(亿) | 3日(亿) | 5日(亿) | 10日(亿) | 方向 |")
        lines.append("|------|------|---------|---------|---------|---------|------|")
        for i, s in enumerate(hot[:config.HEATMAP_TOP_N]):
            lines.append(
                f"| {i+1} "
                f"| {s['name']} "
                f"| {s['net_flow']:.2f} "
                f"| {s.get('d3', 0):.2f} "
                f"| {s.get('d5', 0):.2f} "
                f"| {s.get('d10', 0):.2f} "
                f"| {s.get('direction', '')} |"
            )
        lines.append("")
        if cold:
            lines.append("**❄️ 资金流出 TOP 板块：**")
            lines.append("")
            for s in cold[:5]:
                lines.append(f"- {s['name']}: 今日{s['net_flow']:.2f}亿 {s.get('direction', '')}")
            lines.append("")
    else:
        # 降级：只显示今日板块资金流
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
    lines.append("## 四、AND门控：两弦共振")
    lines.append("")
    
    gate = flow_result.get('and_gate', {})
    gate_summary = gate.get('gate_summary', {})
    gated = gate.get('gated_candidates', [])
    rejected = gate.get('rejected_candidates', [])
    
    # 价格筛选
    gated = _filter_by_price(gated)
    rejected = _filter_by_price(rejected)
    
    lines.append(f"### 门控状态")
    lines.append(f"- 市场门控: {'✅ 通过' if gate_summary.get('market_ok') else '❌ 冷区'}")
    lines.append(f"- 逻辑链候选: {gate_summary.get('total_candidates', 0)}只")
    lines.append(f"- 两弦共振: **{len(gated)}只** ✅（≤{config.MAX_PRICE}元）")
    lines.append(f"- 未通过: {len(rejected)}只 ❌")
    lines.append("")
    
    # 共振候选股（含多周期资金验证+沉淀率+三层共振）
    if gated:
        lines.append("### 🎯 两弦共振候选股（可操作）")
        lines.append("")
        lines.append("| 代码 | 名称 | 行业 | 信号 | 现价 | 涨跌幅% | 行业牛市占比 | 板块净流入 | 共振分 | 沉淀率 | 资金验证 |")
        lines.append("|------|------|------|-----|------|--------|------------|----------|--------|--------|----------|")
        sig_desc = {'limit_up': '涨停', 'new_high_vol': '放量新高', 'new_high': '半年新高'}
        for c in gated:
            st_desc = sig_desc.get(c.get('signal_type', ''), c.get('signal_type', ''))
            code = c.get('code', '')
            ind_flow = c.get('individual_net_flow')
            ind_flow_str = _format_flow_yi(ind_flow) if ind_flow is not None else 'N/A'
            sec_flow = c.get('sector_net_flow', 0)
            
            # 多周期资金验证
            mp = multi_period.get(code, {})
            mp_signal = mp.get('signal', '')
            mp_str = f"3D:{_format_flow_yi(mp.get('3d', 0))} 5D:{_format_flow_yi(mp.get('5d', 0))} 10D:{_format_flow_yi(mp.get('10d', 0))} 20D:{_format_flow_yi(mp.get('20d', 0))} {mp_signal}"
            # 沉淀率
            sed_rate = mp.get('sedimentation_rate', 0)
            sed_str = f"{sed_rate:.1%}" if sed_rate > 0 else "N/A"
            # 三层共振分
            res = resonance_scores.get(code, {})
            res_str = f"{res.get('resonance_score', 0):+d} {res.get('label', '')}"
            
            lines.append(
                f"| {code} "
                f"| {c.get('name', '')} "
                f"| {c.get('industry', '')} "
                f"| {st_desc} "
                f"| {c.get('close', 0):.2f} "
                f"| {c.get('pct_change', 0):.2f} "
                f"| {c.get('ind_bull_ratio', 0):.0%} "
                f"| {sec_flow:.2f}亿 "
                f"| {res_str} "
                f"| {sed_str} "
                f"| {mp_str} |"
            )
        lines.append("")
        
        # 操作建议
        lines.append("### 📋 操作建议")
        lines.append("")
        for c in gated:
            name = c.get('name', c.get('code', ''))
            st = sig_desc.get(c.get('signal_type', ''), '')
            industry = c.get('industry', '')
            code = c.get('code', '')
            mp = multi_period.get(code, {})
            mp_signal = mp.get('signal', '')
            
            lines.append(f"- **{name}** ({st}, {industry}):")
            lines.append(f"  - 买入价: 次日开盘价（T+1执行）")
            lines.append(f"  - 止损: MA20保底 + 最高点回撤8%移动止盈")
            lines.append(f"  - 退出: 月线转熊 或 最长持有60日")
            lines.append(f"  - 资金验证: {mp_signal}")
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
    
    # ── 主线军捕获器（v2.2新增）──
    main_line_dragons = flow_result.get('main_line_dragons', [])
    
    lines.append("## 五、主线军捕获器：近期启动板块 + 龙头")
    lines.append("")
    
    if main_line_dragons:
        lines.append(f"扫描近{config.DRAGON_LOOKBACK_DAYS}日资金持续流入的启动板块，按沉淀率识别板块内龙头（≤{config.MAX_PRICE}元）：")
        lines.append("")
        
        for i, sector in enumerate(main_line_dragons[:config.DRAGON_TOP_SECTORS]):
            sector_name = sector.get('sector', '')
            net_flow_3d = sector.get('net_flow_3d', 0) / 1e8  # 万元→亿
            pct_3d = sector.get('pct_3d', 0)
            leaders = sector.get('leaders', [])
            
            lines.append(f"### {'🏆' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '📊'} {sector_name}")
            lines.append(f"- 3日净流入: **{net_flow_3d:+.2f}亿** | 3日涨跌: {pct_3d:+.1f}%")
            lines.append("")
            
            if leaders:
                # 过滤≤MAX_PRICE
                filtered_leaders = [l for l in leaders if l.get('close', 0) <= config.MAX_PRICE and l.get('close', 0) > 0]
                if not filtered_leaders:
                    filtered_leaders = leaders[:3]  # 没有≤10元的，展示前3
                
                lines.append("| 排名 | 代码 | 名称 | 现价 | 涨跌幅% | 3D净流入 | 沉淀率 |")
                lines.append("|------|------|------|------|--------|---------|--------|")
                for j, l in enumerate(filtered_leaders[:3]):
                    lines.append(
                        f"| {j+1} "
                        f"| {l.get('code', '')} "
                        f"| {l.get('name', '')} "
                        f"| {l.get('close', 0):.2f} "
                        f"| {l.get('pct_change', 0):.2f} "
                        f"| {_format_flow_yi(l.get('net_flow_3d', 0))} "
                        f"| **{l.get('sedimentation_rate', 0):.1%}** |"
                    )
                lines.append("")
            else:
                lines.append("*板块内龙头数据获取中...*\n")
    else:
        lines.append("*今日无近期启动板块*")
    lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # ── 方法论 ──────────────────────────────────────
    lines.append("## 📌 双弦系统方法论")
    lines.append("")
    lines.append("> **逻辑链弦**: 月线牛市定方向 + 领涨行业优先 + 日线突破定入场 + 底背离找回踩买点")
    lines.append("> **资金流弦**: 市场非冷区 + 板块资金正流入 + 个股主力正流入 + 多周期资金验证")
    lines.append("> **市场温度**: 五维评估(动量+量能+MACD+短期趋势+中期趋势) → 0-100分量化市场冷暖")
    lines.append("> **资金沉淀率**: 3日主力净流入/3日总成交额 → 区分真进场vs假拉升")
    lines.append("> **三层共振**: 大盘+板块+个股三层趋势同向评分(-3~+3) → 高胜率介入")
    lines.append("> **主线军捕获器**: 近N日启动板块+板块内龙头(沉淀率排序) → 锁定主线方向")
    lines.append("> **AND门控**: 两弦信号对齐才操作，缺一不可")
    lines.append("> **止损**: MA20保底 + 8%移动止盈 + 月线转熊退出 + 60日最长持有")
    lines.append("")
    lines.append("*本报告由双弦投资系统v2.2自动生成，不构成投资建议。*")
    
    # 保存
    output_dir = config.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{config.REPORT_PREFIX}_{date_str.replace('-', '')}.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return filepath


def generate_push_content(logic_result: dict, flow_result: dict, temperature: dict = None) -> tuple:
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
    
    divergence_signals = logic_result.get('divergence_signals', [])
    multi_period = flow_result.get('multi_period', {})
    
    # 价格筛选（≤MAX_PRICE）
    gated = _filter_by_price(gated)
    divergence_signals = _filter_by_price(divergence_signals)
    
    # 标题逻辑
    if breath.get('status') == '冷区':
        title = f"🚨 双弦日报 — 冷区不动"
    elif gated:
        names = [c.get('name', c.get('code', '')) for c in gated[:5]]
        title = f"🎯 双弦共振 — {len(gated)}只可操作 ({', '.join(names)})"
    elif divergence_signals:
        div_names = [d.get('name', d.get('code', '')) for d in divergence_signals[:3]]
        title = f"🔻 双弦日报 — {len(divergence_signals)}只底背离 ({', '.join(div_names)})"
    else:
        title = f"📊 双弦日报 — 无共振信号"
    
    # 正文
    lines = []
    lines.append(f"**{date_str} 双弦系统日报 v2.2**")
    lines.append("")
    
    # ── 市场温度（推送首行）──
    if temperature and temperature.get('score') is not None:
        score = temperature['score']
        emoji = temperature.get('emoji', '')
        zone = temperature.get('zone', '')
        sub = temperature.get('sub_scores', {})
        lines.append(f"**🌡️ 市场温度：{score}/100 {emoji} {zone}**")
        if sub:
            sub_str = ' | '.join([f"{k}+{v}" for k, v in sub.items()])
            lines.append(f"  {sub_str}")
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
    
    # ── 板块资金全景摘要 ──
    sector_flow = flow_result.get('sector_flow', {})
    hot = sector_flow.get('hot_sectors', [])[:5]
    if hot:
        # 检查是否有 d3/d5/d10 多周期数据
        if hot[0].get('d3') is not None:
            lines.append("**📊 板块资金全景 TOP5：**")
            for s in hot:
                lines.append(f"  {s['name']}: 今日{s['net_flow']:+.2f}亿 3D:{s.get('d3',0):+.2f}亿 5D:{s.get('d5',0):+.2f}亿 10D:{s.get('d10',0):+.2f}亿 {s.get('direction', '')}")
        else:
            lines.append(f"**板块资金**: 热门: {', '.join([s['name'] + f'({s['net_flow']:+.1f}亿)' for s in hot])}")
        lines.append("")
    
    # 底背离摘要
    if divergence_signals:
        lines.append(f"**🔻 底背离买点**: {len(divergence_signals)}只月线牛市股出现日线MACD底背离（≤{config.MAX_PRICE}元）")
        for d in divergence_signals[:5]:
            lines.append(f"  - {d.get('name', d.get('code', ''))} | {d.get('industry', '')} | ¥{d.get('close', 0):.2f} | 回升{d.get('recovery_pct', 0):.1f}% | 间距{d.get('gap_days', 0)}天")
        lines.append("")
    
    # 资金流摘要
    lines.append(f"**资金流**: 市场{breath.get('status', 'N/A')}, 成交额比{breath.get('amount_ratio', 0):.2%}")
    lines.append("")
    
    # AND门控结果
    lines.append(f"**AND门控**: 共振{gate_summary.get('gated_count', 0)}只, 未通过{gate_summary.get('rejected_count', 0)}只")
    lines.append("")
    
    if gated:
        resonance_scores = flow_result.get('resonance_scores', {})
        lines.append("**🎯 共振候选股（含资金验证+沉淀率+共振分）:**")
        for c in gated:
            st = sig_desc.get(c.get('signal_type', ''), '')
            code = c.get('code', '')
            mp = multi_period.get(code, {})
            mp_signal = mp.get('signal', '')
            mp_str = f"3D:{_format_flow_yi(mp.get('3d', 0))} 5D:{_format_flow_yi(mp.get('5d', 0))} 10D:{_format_flow_yi(mp.get('10d', 0))} 20D:{_format_flow_yi(mp.get('20d', 0))} {mp_signal}"
            # 沉淀率
            sed_rate = mp.get('sedimentation_rate', 0)
            sed_str = f"沉淀率{sed_rate:.1%}" if sed_rate > 0 else ""
            # 三层共振分
            res = resonance_scores.get(code, {})
            res_str = f"共振{res.get('resonance_score', 0):+d} {res.get('label', '')}"
            
            lines.append(f"  - {c.get('name', code)} | {st} | {c.get('industry', '')} | ¥{c.get('close', 0):.2f} | 涨跌{c.get('pct_change', 0):.1f}%")
            detail_parts = [f"资金验证: {mp_str}"]
            if sed_str:
                detail_parts.append(sed_str)
            if res_str:
                detail_parts.append(res_str)
            lines.append(f"    {' | '.join(detail_parts)}")
        lines.append("")
        
        # 主线军摘要
        main_line_dragons = flow_result.get('main_line_dragons', [])
        if main_line_dragons:
            lines.append(f"**🏆 主线板块**: {', '.join([s.get('sector', '') for s in main_line_dragons[:3]])}")
            if main_line_dragons[0].get('leaders'):
                top_leader = main_line_dragons[0]['leaders'][0]
                lines.append(f"  龙头: {top_leader.get('name', '')} 沉淀率{top_leader.get('sedimentation_rate', 0):.1%}")
            lines.append("")
        
        lines.append("⚠️ 次日开盘价买入(T+1), MA20止损+8%移动止盈+月线转熊退出")
    elif divergence_signals:
        lines.append("今日无共振信号，但有底背离买点值得关注：")
        lines.append("  底背离信号可作为逢低布局参考，建议结合资金流人工确认后操作")
    else:
        lines.append("今日无共振信号，无底背离信号，不操作。")
    
    content = '\n'.join(lines)
    return title, content
