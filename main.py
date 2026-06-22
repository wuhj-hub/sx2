#!/usr/bin/env python3
"""
双弦投资系统 v2.0 — 主入口
==================================
逻辑链弦(月线牛市+日线突破V3.0) × 资金流弦(七步复盘)
AND门控：两弦信号对齐才推送操作信号

每日收盘后(15:30+)运行，生成双弦日报并推送。
GitHub Actions 定时触发 → Server酱推微信。
"""

import sys
import os
import logging
import argparse
from datetime import datetime

# 将脚本所在目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from logic_chain import run_logic_scan
from flow_chain import run_flow_scan
from reporter import generate_daily_report, generate_push_content
from push import push_report


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def run_shuangxian_v2(target_date: str = None) -> dict:
    """
    双弦系统v2.0完整运行流程
    
    1. 逻辑链弦：月线牛市 + 日线突破 → 候选股
    2. 资金流弦：七步复盘 → 资金流确认
    3. AND门控：两弦共振 → 操作信号
    4. 生成报告 + 推送
    """
    log = logging.getLogger("shuangxian")
    log.info("=" * 60)
    log.info(f"双弦投资系统 v2.0 启动 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)
    
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')
    
    # ── 第一步：逻辑链弦 ──────────────────────────────
    log.info(">>> 逻辑链弦：月线牛市 + 日线突破 <<<")
    try:
        logic_result = run_logic_scan(target_date)
    except Exception as e:
        log.error(f"逻辑链弦执行异常: {e}")
        logic_result = {
            'date': target_date, 'monthly_bull_count': 0,
            'signal_count': 0, 'signal_summary': {},
            'candidates': [], 'industry_status': {},
            'leading_industries': [],
        }
    
    candidates = logic_result.get('candidates', [])
    log.info(f"  逻辑链输出: {len(candidates)}只候选股")
    
    # ── 第二步：资金流弦 ──────────────────────────────
    log.info(">>> 资金流弦：七步复盘 + AND门控 <<<")
    try:
        flow_result = run_flow_scan(logic_candidates=candidates)
    except Exception as e:
        log.error(f"资金流弦执行异常: {e}")
        flow_result = {
            'breath': {'status': '数据缺失', 'amount_ratio': 0, 'action': '无法判断'},
            'index_direction': {'direction': '数据缺失', 'action': '无法判断'},
            'sector_flow': {'hot_sectors': [], 'cold_sectors': [], 'sector_net_flow': {}},
            'individual_flow': {'individual_net_flow': {}, 'top_inflow': []},
            'and_gate': {
                'gated_candidates': [], 'rejected_candidates': candidates,
                'gate_summary': {
                    'market_ok': False, 'total_candidates': len(candidates),
                    'gated_count': 0, 'rejected_count': len(candidates),
                }
            },
        }
    
    gated = flow_result.get('and_gate', {}).get('gated_candidates', [])
    log.info(f"  AND门控: {len(gated)}只共振")
    
    # ── 第三步：生成报告 ──────────────────────────────
    log.info(">>> 生成报告 <<<")
    try:
        report_path = generate_daily_report(logic_result, flow_result)
        log.info(f"  报告已生成: {report_path}")
    except Exception as e:
        log.error(f"  报告生成失败: {e}")
        report_path = None
    
    # ── 第四步：推送 ──────────────────────────────────
    try:
        title, content = generate_push_content(logic_result, flow_result)
        push_report(report_path=report_path, title=title, content=content)
    except Exception as e:
        log.error(f"  推送失败: {e}")
    
    # ── 完成 ──────────────────────────────────────────
    log.info("=" * 60)
    log.info(f"双弦系统v2.0完成 — 逻辑链{len(candidates)}只 → 共振{len(gated)}只")
    log.info("=" * 60)
    
    return {
        'report_path': report_path,
        'logic_candidates': len(candidates),
        'gated_candidates': len(gated),
        'logic_result': logic_result,
        'flow_result': flow_result,
    }


def main():
    parser = argparse.ArgumentParser(description='双弦投资系统v2.0')
    parser.add_argument('--date', type=str, default=None, help='目标日期 YYYY-MM-DD，默认今天')
    parser.add_argument('--output-dir', type=str, default=None, help='报告输出目录')
    parser.add_argument('--cache-dir', type=str, default=None, help='缓存目录')
    parser.add_argument('--verbose', action='store_true', help='详细日志')
    args = parser.parse_args()
    
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    
    if args.output_dir:
        config.OUTPUT_DIR = args.output_dir
    if args.cache_dir:
        config.CACHE_DIR = args.cache_dir
    
    result = run_shuangxian_v2(target_date=args.date)
    
    gated = result.get('gated_candidates', 0)
    logic = result.get('logic_candidates', 0)
    print(f"\n📊 双弦系统v2.0: 逻辑链{logic}只 → 共振{gated}只")
    if result.get('report_path'):
        print(f"📄 报告: {result['report_path']}")
    
    return result


if __name__ == '__main__':
    main()
