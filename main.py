"""
资金流实盘复盘脚本 — 主入口
==================================
每天收盘后(15:30+)运行，生成资金流日报。
GitHub Actions 定时触发时自动推送到微信。
"""

import sys
import os
import logging
import argparse
from datetime import datetime

# 将脚本所在目录加入 path（确保扁平结构下 import 正常）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from steps import (
    step1_breath_check, step2_index_direction, step3_etf_check,
    step4_sector_heatmap, step5_individual_scan, step6_margin_scan,
    step7_summary,
)
from six_filters import run_six_filters
from triple_confirm import run_triple_confirm
from reporter import generate_report, generate_cold_alert
from push import push_report


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def run_daily_review(run_filters=True, run_confirm=True) -> dict:
    log = logging.getLogger("shuangxian")
    log.info("=" * 60)
    log.info(f"资金流实盘复盘开始 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)
    
    log.info(">>> 七步复盘SOP <<<")
    s1 = step1_breath_check()
    s2 = step2_index_direction()
    s3 = step3_etf_check()
    s4 = step4_sector_heatmap()
    s5 = step5_individual_scan()
    s6 = step6_margin_scan()
    s7 = step7_summary(s1, s2, s3, s4, s5, s6)
    
    step_results = {
        'step1': s1, 'step2': s2, 'step3': s3,
        'step4': s4, 'step5': s5, 'step6': s6, 'step7': s7,
    }
    
    filter_results = {'candidates': [], 'notes': ['未执行']}
    if run_filters:
        log.info(">>> 六层滤网筛选 <<<")
        try:
            filter_results = run_six_filters()
        except Exception as e:
            log.error(f"六层滤网执行异常: {e}")
            filter_results = {'candidates': [], 'notes': [f'执行异常: {e}']}
    
    confirm_results = {'confirm1': {}, 'confirm2': {}, 'confirm3': {}, 'all_pass': False, 'action': '未执行'}
    if run_confirm:
        log.info(">>> 三重确认择时 <<<")
        try:
            confirm_results = run_triple_confirm(s1, s2)
        except Exception as e:
            log.error(f"三重确认执行异常: {e}")
            confirm_results = {'confirm1': {}, 'confirm2': {}, 'confirm3': {}, 'all_pass': False, 'action': f'执行异常: {e}'}
    
    log.info(">>> 生成报告 <<<")
    try:
        report_path = generate_report(step_results, filter_results, confirm_results)
        log.info(f"报告已生成: {report_path}")
    except Exception as e:
        log.error(f"报告生成失败: {e}")
        report_path = None
    
    alert = generate_cold_alert(s1)
    if report_path:
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report_content = f.read()
        except Exception:
            report_content = ""
        push_report(report_path, alert, summary_text=report_content)
    
    log.info("=" * 60)
    log.info(f"复盘完成 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)
    
    return {
        'report_path': report_path,
        'alert': alert,
        'step_results': step_results,
        'filter_results': filter_results,
        'confirm_results': confirm_results,
    }


def main():
    parser = argparse.ArgumentParser(description='资金流实盘复盘脚本')
    parser.add_argument('--no-filters', action='store_true', help='跳过六层滤网（提速）')
    parser.add_argument('--no-confirm', action='store_true', help='跳过三重确认')
    parser.add_argument('--output-dir', type=str, default=None, help='报告输出目录')
    parser.add_argument('--verbose', action='store_true', help='详细日志')
    args = parser.parse_args()
    
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    
    if args.output_dir:
        config.OUTPUT_DIR = args.output_dir
    
    result = run_daily_review(
        run_filters=not args.no_filters,
        run_confirm=not args.no_confirm,
    )
    
    if result['alert']:
        print(f"\n{'='*60}")
        print(f"⚠️ 预警: {result['alert']}")
        print(f"{'='*60}\n")
    
    if result['report_path']:
        print(f"📄 报告路径: {result['report_path']}")
    
    return result


if __name__ == '__main__':
    main()
