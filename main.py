"""
双弦投资系统 — 主入口
==================================
整合所有模块的完整运行流程：
1. 运行七步复盘（steps）
2. 运行六层滤网（six_filters）→ 资金流候选池
3. 加载逻辑链候选池（logic_pool）→ 逻辑链候选池
4. A/B/C分级（grading）
5. 三重确认择时（triple_confirm）
6. 持仓里程碑检查+熔断判断（milestone）
7. 预警推送（alert）
8. 生成报告（reporter）
"""

import sys
import os
import logging
import argparse
from datetime import datetime

# 将脚本所在目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from steps import (
    step1_breath_check, step2_index_direction, step3_etf_check,
    step4_sector_heatmap, step5_individual_scan, step6_margin_scan,
    step7_summary,
)
from six_filters import run_six_filters
from triple_confirm import run_triple_confirm
from logic_pool import get_logic_pool
from grading import run_grading, get_action_suggestions
from milestone import run_milestone_check, get_circuit_summary
from alert import AlertSystem, generate_alerts, send_alerts
from reporter import generate_report, generate_simple_report
import push


def setup_logging(level=logging.INFO):
    """配置日志"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def run_full_review() -> dict:
    """
    运行完整的双弦投资系统复盘流程
    
    Returns:
        dict: 包含所有模块的执行结果
    """
    log = logging.getLogger("shuangxian")
    log.info("=" * 70)
    log.info(f"双弦投资系统开始运行 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("核心理念: 逻辑链(买什么) × 资金流(何时买) = 双线AND门控")
    log.info("=" * 70)
    
    results = {'success': True, 'errors': []}
    
    # ── 1. 七步复盘 SOP ──────────────────────────────────
    log.info("\n>>> 1. 七步复盘 SOP <<<")
    try:
        s1 = step1_breath_check()
        s2 = step2_index_direction()
        s3 = step3_etf_check()
        s4 = step4_sector_heatmap()
        s5 = step5_individual_scan()
        s6 = step6_margin_scan()
        s7 = step7_summary(s1, s2, s3, s4, s5, s6)
        
        results['step_results'] = {
            'step1': s1, 'step2': s2, 'step3': s3,
            'step4': s4, 'step5': s5, 'step6': s6, 'step7': s7,
        }
        log.info(f"  市场态度: {s7.get('market_attitude')}")
    except Exception as e:
        log.error(f"七步复盘执行异常: {e}")
        results['success'] = False
        results['errors'].append(f"七步复盘: {e}")
    
    # ── 2. 六层滤网 → 资金流候选池 ────────────────────────
    log.info("\n>>> 2. 六层滤网筛选 (资金流候选池) <<<")
    try:
        filter_results = run_six_filters()
        results['filter_results'] = filter_results
        capital_pool = filter_results.get('candidates', [])
        log.info(f"  资金流候选池: {len(capital_pool)} 只")
    except Exception as e:
        log.error(f"六层滤网执行异常: {e}")
        results['filter_results'] = {'candidates': [], 'notes': [f'执行异常: {e}']}
        results['errors'].append(f"六层滤网: {e}")
    
    # ── 3. 加载逻辑链候选池 ──────────────────────────────
    log.info("\n>>> 3. 加载逻辑链候选池 <<<")
    try:
        logic_pool = get_logic_pool()
        results['logic_pool'] = logic_pool
        log.info(f"  逻辑链候选池: {len(logic_pool)} 只")
    except Exception as e:
        log.error(f"逻辑链候选池加载异常: {e}")
        results['logic_pool'] = []
        results['errors'].append(f"逻辑链候选池: {e}")
    
    # ── 4. A/B/C分级 ─────────────────────────────────────
    log.info("\n>>> 4. A/B/C级标的分级 <<<")
    try:
        grading_result = run_grading()
        results['grading_result'] = grading_result
        summary = grading_result.get('summary', {})
        log.info(f"  分级结果: A级{summary.get('grade_a_count', 0)}只, "
                f"B级{summary.get('grade_b_count', 0)}只, "
                f"C级{summary.get('grade_c_count', 0)}只")
    except Exception as e:
        log.error(f"分级执行异常: {e}")
        results['grading_result'] = {'grade_a': [], 'grade_b': [], 'grade_c': [], 'summary': {}}
        results['errors'].append(f"分级: {e}")
    
    # ── 5. 三重确认择时 ──────────────────────────────────
    log.info("\n>>> 5. 三重确认择时 <<<")
    try:
        s1 = results.get('step_results', {}).get('step1', {})
        s2 = results.get('step_results', {}).get('step2', {})
        confirm_results = run_triple_confirm(s1, s2)
        results['confirm_results'] = confirm_results
        log.info(f"  三重确认: {'✅ 全部通过' if confirm_results.get('all_pass') else '❌ 未全部通过'}")
    except Exception as e:
        log.error(f"三重确认执行异常: {e}")
        results['confirm_results'] = {'confirm1': {}, 'confirm2': {}, 'confirm3': {}, 'all_pass': False}
        results['errors'].append(f"三重确认: {e}")
    
    # ── 6. 持仓里程碑检查+熔断判断 ────────────────────────
    log.info("\n>>> 6. 持仓里程碑检查+熔断判断 <<<")
    try:
        confirm_results = results.get('confirm_results', {})
        circuit_results = run_milestone_check(confirm_results)
        circuit_summary = get_circuit_summary(circuit_results)
        results['circuit_results'] = circuit_results
        results['circuit_summary'] = circuit_summary
        log.info(f"  熔断状态: 🔴{circuit_summary.get('hard', 0)}只, "
                f"🟡{circuit_summary.get('soft', 0)}只, "
                f"🟢{circuit_summary.get('normal', 0)}只")
    except Exception as e:
        log.error(f"持仓里程碑检查异常: {e}")
        results['circuit_results'] = []
        results['circuit_summary'] = {'total': 0, 'hard': 0, 'soft': 0, 'normal': 0}
        results['errors'].append(f"持仓里程碑: {e}")
    
    # ── 7. 预警推送 ──────────────────────────────────────
    log.info("\n>>> 7. 预警推送 <<<")
    try:
        alert_system = AlertSystem(push)
        alerts = alert_system.run_full_alert_check(
            results.get('step_results', {}),
            results.get('grading_result', {}),
            results.get('circuit_results', []),
            results.get('confirm_results', {})
        )
        results['alerts'] = alerts
        alert_system.send_alerts(alerts)
        log.info(f"  预警推送完成，共 {len(alerts)} 条")
    except Exception as e:
        log.error(f"预警推送异常: {e}")
        results['alerts'] = []
        results['errors'].append(f"预警推送: {e}")
    
    # ── 8. 生成报告 ──────────────────────────────────────
    log.info("\n>>> 8. 生成报告 <<<")
    try:
        report_path = generate_report(
            step_results=results.get('step_results', {}),
            filter_results=results.get('filter_results', {}),
            confirm_results=results.get('confirm_results', {}),
            grading_result=results.get('grading_result', {}),
            circuit_results=results.get('circuit_results', []),
        )
        results['report_path'] = report_path
        log.info(f"  报告已生成: {report_path}")
    except Exception as e:
        log.error(f"报告生成异常: {e}")
        results['report_path'] = None
        results['errors'].append(f"报告生成: {e}")
    
    # ── 完成 ──────────────────────────────────────────────
    log.info("\n" + "=" * 70)
    log.info(f"双弦投资系统运行完成 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if results['errors']:
        log.warning(f"部分模块执行异常: {results['errors']}")
    log.info("=" * 70)
    
    return results


def main():
    """主函数入口"""
    parser = argparse.ArgumentParser(
        description='双弦投资系统 — A股量化复盘自动化',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                 # 运行完整复盘
  python main.py --quick         # 快速模式(跳过资金流筛选)
  python main.py --verbose       # 详细日志
  python main.py --output-dir ./output  # 指定报告输出目录
        """
    )
    parser.add_argument('--quick', action='store_true', 
                       help='快速模式(跳过六层滤网筛选)')
    parser.add_argument('--output-dir', type=str, default=None,
                       help='报告输出目录')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='详细日志')
    parser.add_argument('--no-push', action='store_true',
                       help='不发送推送')
    
    args = parser.parse_args()
    
    # 配置日志级别
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    
    # 配置输出目录
    if args.output_dir:
        config.OUTPUT_DIR = args.output_dir
    
    # 运行完整复盘
    results = run_full_review()
    
    # 打印简要结果
    print("\n" + "=" * 60)
    print("📊 双弦投资系统 — 执行结果摘要")
    print("=" * 60)
    
    step7 = results.get('step_results', {}).get('step7', {})
    print(f"市场态度: {step7.get('market_attitude', '未知')}")
    print(f"关键信号: {step7.get('key_signal', '无')}")
    print(f"明日操作: {step7.get('tomorrow_action', '无')}")
    
    grading = results.get('grading_result', {}).get('summary', {})
    print(f"\n分级结果: A级{grading.get('grade_a_count', 0)}只, "
          f"B级{grading.get('grade_b_count', 0)}只, "
          f"C级{grading.get('grade_c_count', 0)}只")
    
    circuit = results.get('circuit_summary', {})
    print(f"熔断状态: 🔴{circuit.get('hard', 0)}只, "
          f"🟡{circuit.get('soft', 0)}只, "
          f"🟢{circuit.get('normal', 0)}只")
    
    if results.get('report_path'):
        print(f"\n📄 报告: {results['report_path']}")
    
    if results.get('errors'):
        print(f"\n⚠️ 异常: {results['errors']}")
    
    print("=" * 60)
    
    return results


if __name__ == '__main__':
    main()
