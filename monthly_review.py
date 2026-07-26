#!/usr/bin/env python3
"""
双弦投资系统 · 月度自检机制 (monthly_review.py)
==============================================
功能：每周末/月末运行，回顾本月运行情况，验证效果，提出改进建议

检查项：
1. 系统运行健康状况（运行次数、是否异常）
2. 股池轮动状况（新增/移除变化）
3. 评分分布合理性
4. 各维度评分有效性
5. 改进建议

用法：
    python3 monthly_review.py                    # 自检当前月
    python3 monthly_review.py --full             # 全量自检（含跨月对比）
    python3 monthly_review.py --month 2026-06    # 指定月份
"""

import json, os, sys
from datetime import datetime, date
from pathlib import Path

# ============================================================
# 配置
# ============================================================

POOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pools")
LOG_DIR = POOL_DIR
SKILL_DIR = str(Path(__file__).parent.parent)


def load_pool(ym: str) -> list:
    """加载指定月份股池"""
    fp = os.path.join(POOL_DIR, f"pool_{ym}.json")
    if not os.path.exists(fp):
        return []
    try:
        with open(fp, "r") as f:
            data = json.load(f)
        return data.get("entries", [])
    except:
        return []


def load_logs() -> list[dict]:
    """加载所有运行日志"""
    if not os.path.exists(LOG_DIR):
        return []
    logs = []
    for f in sorted(os.listdir(LOG_DIR)):
        if f.startswith("run_log_") and f.endswith(".json"):
            try:
                with open(os.path.join(LOG_DIR, f), "r") as fp:
                    logs.append(json.load(fp))
            except:
                pass
    return logs


def check_health() -> dict:
    """检查系统运行健康状况"""
    logs = load_logs()
    today = date.today()
    ym = today.strftime("%Y-%m")
    
    # 本月运行统计
    this_month_logs = [l for l in logs if l.get("date", "").startswith(ym)]
    
    issues = []
    suggestions = []
    score = 100

    # 检查运行次数
    if len(this_month_logs) == 0:
        issues.append("❌ 本月尚未运行过")
        score -= 30
    elif len(this_month_logs) < 5:
        issues.append(f"⚠️ 本月仅运行{len(this_month_logs)}次，建议每日盘后运行")
        score -= 10

    # 检查温度分布
    temps = [l.get("temperature", 50) for l in this_month_logs]
    if temps:
        avg_temp = sum(temps) / len(temps)
        issues.append(f"📊 本月平均温度: {avg_temp:.0f}/100")
        if avg_temp < 40:
            suggestions.append("💡 冷市持续，建议关注猛兽信号(SSV/VAD)突破门控的标的")
        elif avg_temp > 70:
            suggestions.append("💡 热市运行，可适当降低门控阈值增加标的")

    # 检查通过率
    total_gate = sum(1 for l in this_month_logs if l.get("gate1", False))
    total_signals = sum(l.get("signals", 0) for l in this_month_logs)
    if total_gate > 0 and total_signals == 0:
        issues.append("❌ 门控通过但无信号进入股池，检查评分阈值")
        score -= 15
    elif total_gate == 0 and len(this_month_logs) > 10:
        suggestions.append("💡 连续低温，冷市模式下猛兽信号门控生效中")

    return {
        "score": max(0, score),
        "run_count": len(this_month_logs),
        "avg_temperature": round(sum(temps)/len(temps), 1) if temps else 0,
        "gate_pass_count": total_gate,
        "total_signals": total_signals,
        "issues": issues,
        "suggestions": suggestions,
    }


def check_pool_quality(ym: str = None) -> dict:
    """检查股池质量"""
    if ym is None:
        ym = date.today().strftime("%Y-%m")
    
    entries = load_pool(ym)
    issues = []
    suggestions = []
    score = 100

    if not entries:
        return {"score": 0, "count": 0, "issues": ["本月无股池数据"], "suggestions": [], "avg_score": 0}

    count = len(entries)
    scores = [e.get("score", 0) for e in entries]
    avg_score = sum(scores) / count if count else 0
    
    types = {}
    for e in entries:
        t = e.get("signal_type", "未知")
        types[t] = types.get(t, 0) + 1

    # 评分分布
    high = sum(1 for s in scores if s >= 60)
    mid = sum(1 for s in scores if 40 <= s < 60)
    low = sum(1 for s in scores if s < 40)

    issues.append(f"📊 股池 {count}只 | 均分{avg_score:.1f} | "
                  f"高分{high}只 | 中分{mid}只 | 低分{low}只")
    issues.append(f"📊 类型: {' | '.join([f'{k}{v}只' for k,v in types.items()])}")

    if low > count * 0.5:
        issues.append("⚠️ 低分股占比过高(>50%)，建议提高评分门槛")
        score -= 15
        suggestions.append("💡 考虑将score_threshold从50提升到55")
    
    if types.get("低吸", 0) > types.get("共振", 0) * 2:
        suggestions.append("💡 低吸股数量远超共振股，可能是大盘偏冷，关注RS_D/伏击线信号质量")

    return {
        "score": max(0, score),
        "count": count,
        "avg_score": round(avg_score, 1),
        "distribution": {"high": high, "mid": mid, "low": low},
        "types": types,
        "issues": issues,
        "suggestions": suggestions,
    }


def check_cross_month(ym: str = None) -> dict:
    """跨月对比检查"""
    if ym is None:
        ym = date.today().strftime("%Y-%m")
    
    year, month = ym.split("-")
    prev_y, prev_m = int(year), int(month) - 1
    if prev_m == 0:
        prev_y -= 1
        prev_m = 12
    prev_key = f"{prev_y:04d}-{prev_m:02d}"
    
    current = load_pool(ym)
    prev = load_pool(prev_key)
    
    if not prev:
        return {"has_prev": False, "message": "上月无数据，首次运行"}
    
    curr_codes = set(e["code"] for e in current)
    prev_codes = set(e["code"] for e in prev)
    
    new_count = len(curr_codes - prev_codes)
    removed_count = len(prev_codes - curr_codes)
    retained = curr_codes & prev_codes
    
    turnover = new_count / len(prev) * 100 if len(prev) > 0 else 0
    
    issues = []
    suggestions = []
    
    issues.append(f"📊 本月 {len(current)}只 vs 上月 {len(prev)}只")
    issues.append(f"📊 新增{new_count}只 | 移除{removed_count}只 | 留存{len(retained)}只")
    issues.append(f"📊 轮动率: {turnover:.0f}%")
    
    if turnover > 80:
        suggestions.append("💡 轮动率过高(>80%)，股池稳定性不足，可能是市场风格切换快")
    elif turnover < 20 and new_count < 3:
        suggestions.append("💡 轮动率过低(<20%)，系统可能过度保守，检查门控阈值")
    
    return {
        "has_prev": True,
        "prev_month": prev_key,
        "prev_count": len(prev),
        "current_count": len(current),
        "new_count": new_count,
        "removed_count": removed_count,
        "retained_count": len(retained),
        "turnover": round(turnover, 1),
        "issues": issues,
        "suggestions": suggestions,
    }


def generate_review(ym: str = None, full: bool = False) -> str:
    """生成月度自检报告"""
    if ym is None:
        ym = date.today().strftime("%Y-%m")
    
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    lines = []
    lines.append("=" * 45)
    lines.append(f"🔍 双弦投资系统 · 月度自检报告")
    lines.append(f"  月份: {ym}  |  生成: {today_str}")
    lines.append("=" * 45)
    
    # 1. 系统健康检查
    lines.append("\n🏥 一、系统运行健康")
    lines.append("-" * 35)
    health = check_health()
    lines.append(f"   健康评分: {health['score']}/100")
    if health['run_count'] > 0:
        lines.append(f"   本月运行: {health['run_count']}次 | "
                     f"平均温度: {health['avg_temperature']}/100 | "
                     f"门控通过: {health['gate_pass_count']}次 | "
                     f"信号数: {health['total_signals']}条")
    for issue in health.get("issues", []):
        lines.append(f"   {issue}")
    for sug in health.get("suggestions", []):
        lines.append(f"   {sug}")
    
    # 2. 股池质量检查
    lines.append("\n📦 二、股池质量评估")
    lines.append("-" * 35)
    quality = check_pool_quality(ym)
    if quality['count'] > 0:
        d = quality['distribution']
        lines.append(f"   质量评分: {quality['score']}/100")
        lines.append(f"   均分 {quality['avg_score']} | "
                     f"高分{d['high']} | 中分{d['mid']} | 低分{d['low']}")
    for issue in quality.get("issues", []):
        lines.append(f"   {issue}")
    for sug in quality.get("suggestions", []):
        lines.append(f"   {sug}")
    
    # 3. 跨月轮动分析
    if full:
        lines.append("\n🔄 三、跨月轮动分析")
        lines.append("-" * 35)
        cross = check_cross_month(ym)
        if cross.get("has_prev"):
            for issue in cross.get("issues", []):
                lines.append(f"   {issue}")
            for sug in cross.get("suggestions", []):
                lines.append(f"   {sug}")
        else:
            lines.append(f"   {cross['message']}")
    else:
        lines.append("\n🔄 三、跨月轮动分析 (使用 --full 查看)")
    
    # 4. 综合改进建议
    lines.append("\n💡 四、综合改进建议")
    lines.append("-" * 35)
    all_suggestions = (health.get("suggestions", []) + 
                       quality.get("suggestions", []))
    if full:
        cross = check_cross_month(ym)
        all_suggestions += cross.get("suggestions", [])
    
    if all_suggestions:
        for i, sug in enumerate(all_suggestions, 1):
            lines.append(f"   {i}. {sug}")
    else:
        lines.append("   系统运行正常，暂无改进建议")
    
    # 5. 行动清单
    lines.append("\n📋 五、行动清单")
    lines.append("-" * 35)
    actions = []
    
    # 根据检查结果自动生成行动项
    if health['score'] < 60:
        actions.append("🔴 优先修复健康问题")
    if quality.get('avg_score', 100) < 45:
        actions.append("🟡 调高评分门槛至55分")
    if health.get('run_count', 0) < 5:
        actions.append("🟡 设置每日定时运行（盘后16:00）")
    
    if not actions:
        # 默认行动项
        if quality.get('count', 0) > 0:
            actions.append("🟢 关注本月股池中评分≥60的标的")
        actions.append("🟢 下次运行时验证猛兽信号(G点/伏击线/RS_D)准确率")
        actions.append("🟢 下月初对比本月股池实际表现")
    
    for action in actions:
        lines.append(f"   {action}")
    
    lines.append("\n" + "=" * 45)
    return "\n".join(lines)


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    full = "--full" in sys.argv
    ym = None
    for i, arg in enumerate(sys.argv):
        if arg == "--month" and i + 1 < len(sys.argv):
            ym = sys.argv[i + 1]
    
    print(generate_review(ym, full))
