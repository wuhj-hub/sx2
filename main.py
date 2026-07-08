#!/usr/bin/env python3
"""
双弦投资系统 v2.2 — 主入口
==================================
逻辑链弦(月线牛市+日线突破V3.0) × 资金流弦(七步复盘+板块全景+多周期验证)
市场温度计(五维评估) + 三层共振评分 + 资金沉淀率 + 主线军捕获器 + AND门控

每日收盘后1小时(16:00)运行，生成双弦日报并推送。
GitHub Actions 定时触发(cron: 0 8 * * 1-5) → PushPlus+Server酱双通道推微信。
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
from data_fetcher import get_market_temperature, batch_get_chip_distribution, get_concept_sector_stocks
from scoring import batch_calculate_scores
from reporter import generate_daily_report, generate_push_content
from push import push_report
from monthly_pool import update_pool


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def run_shuangxian_v2(target_date: str = None) -> dict:
    """
    双弦系统v2.1完整运行流程
    
    0. 市场温度计（五维评估）
    1. 逻辑链弦：月线牛市 + 日线突破 → 候选股
    2. 资金流弦：七步复盘 + 板块全景 + 多周期验证 → 资金流确认
    3. AND门控：两弦共振 → 操作信号
    4. 生成报告 + 推送
    """
    log = logging.getLogger("shuangxian")
    log.info("=" * 60)
    log.info(f"双弦投资系统 v2.2 启动 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)
    
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')
    
    # ── 第零步：市场温度计 ─────────────────────────────
    log.info(">>> 市场温度计 <<<")
    temperature = None
    if config.THERMOMETER_ENABLED:
        try:
            temperature = get_market_temperature()
            log.info(f"  市场温度: {temperature.get('score', 'N/A')}/100 {temperature.get('emoji', '')}{temperature.get('zone', '')}")
        except Exception as e:
            log.error(f"  温度计计算失败: {e}")
            temperature = None
    
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
    
    # ── 第1.1步：概念板块成分股获取 ─────────────────────
    concept_map = {}
    concept_stocks = {}
    if config.CONCEPT_ENABLED:
        log.info(">>> 概念板块成分股获取 <<<")
        try:
            concept_map, concept_stocks = get_concept_sector_stocks()
            log.info(f"  概念板块: {len(concept_stocks)}个, 映射{len(concept_map)}只股票")
            # 为候选股补充概念板块属性
            for cand in candidates:
                symbol = cand.get('symbol', '')
                if symbol in concept_map:
                    cand['concept'] = concept_map[symbol]
                else:
                    cand['concept'] = ''
            # 也为底背离信号补充概念
            for div in logic_result.get('divergence_signals', []):
                symbol = div.get('symbol', '')
                if symbol in concept_map:
                    div['concept'] = concept_map[symbol]
                else:
                    div['concept'] = ''
            # 保存到logic_result供后续使用
            logic_result['concept_map'] = concept_map
            logic_result['concept_stocks'] = concept_stocks
        except Exception as e:
            log.error(f"  概念板块获取失败: {e}")
    
    # ── 第1.5步：筹码集中度分析 ────────────────────────
    if config.CHIP_ENABLED and candidates:
        log.info(">>> 筹码集中度分析 <<<")
        try:
            candidates = batch_get_chip_distribution(candidates)
            chip_concentrated = sum(1 for c in candidates if c.get('chip', {}).get('chip_concentrated'))
            log.info(f"  筹码分析完成: {len(candidates)}只, 其中{chip_concentrated}只筹码集中")
        except Exception as e:
            log.error(f"  筹码分析失败: {e}")
    
    # ── 第二步：资金流弦 ──────────────────────────────
    log.info(">>> 资金流弦：七步复盘 + 板块全景 + 多周期验证 + 三层共振 + 主线军 <<<")
    try:
        flow_result = run_flow_scan(logic_candidates=candidates, temperature=temperature)
    except Exception as e:
        log.error(f"资金流弦执行异常: {e}")
        flow_result = {
            'breath': {'status': '数据缺失', 'amount_ratio': 0, 'action': '无法判断'},
            'index_direction': {'direction': '数据缺失', 'action': '无法判断'},
            'sector_flow': {'hot_sectors': [], 'cold_sectors': [], 'sector_net_flow': {}},
            'individual_flow': {'individual_net_flow': {}, 'top_inflow': []},
            'multi_period': {},
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
    
    # ── 第2.5步：3维综合评分排序（v2.2新增）──────────
    if config.SCORING_ENABLED and gated:
        log.info(">>> 候选股3维综合评分 <<<")
        try:
            multi_period = flow_result.get('multi_period', {})
            resonance_scores = flow_result.get('resonance_scores', {})
            # 收集底背离的symbol
            divergence_symbols = set()
            for div in logic_result.get('divergence_signals', []):
                if div.get('symbol'):
                    divergence_symbols.add(div['symbol'])
            
            gated = batch_calculate_scores(
                candidates=gated,
                multi_period=multi_period,
                resonance_scores=resonance_scores,
                kline_cache={},
                divergence_symbols=divergence_symbols,
            )
            # 更新回flow_result
            flow_result['and_gate']['gated_candidates'] = gated
            log.info(f"  评分排序完成: TOP {gated[0].get('name','')}={gated[0].get('score',{}).get('total_score',0):.1f}分" if gated else "  无候选股")
        except Exception as e:
            log.error(f"  评分计算失败: {e}")
    
    # ── 第2.6步：月度股池更新 ──────────────────────────────
    monthly_pool_data = {}
    if config.MONTHLY_POOL_ENABLED:
        log.info(">>> 月度股池更新 <<<")
        try:
            divergence_signals = logic_result.get('divergence_signals', [])
            monthly_pool_data = update_pool(
                gated_candidates=gated,
                divergence_signals=divergence_signals,
                today_str=target_date,
            )
            log.info(f"  月度股池: {len(monthly_pool_data)}只")
        except Exception as e:
            log.error(f"  月度股池更新失败: {e}")
    
    # ── 第三步：生成报告 ──────────────────────────────
    log.info(">>> 生成报告 <<<")
    try:
        report_path = generate_daily_report(logic_result, flow_result, temperature=temperature, monthly_pool_data=monthly_pool_data)
        log.info(f"  报告已生成: {report_path}")
    except Exception as e:
        log.error(f"  报告生成失败: {e}")
        report_path = None
    
    # ── 第四步：推送 ──────────────────────────────────
    try:
        title, content = generate_push_content(logic_result, flow_result, temperature=temperature, monthly_pool_data=monthly_pool_data)
        push_report(report_path=report_path, title=title, content=content)
    except Exception as e:
        log.error(f"  推送失败: {e}")
    
    # ── 完成 ──────────────────────────────────────────
    temp_str = f"温度{temperature['score']}/100" if temperature else "温度N/A"
    log.info("=" * 60)
    log.info(f"双弦系统v2.2完成 — {temp_str} — 逻辑链{len(candidates)}只 → 共振{len(gated)}只")
    log.info("=" * 60)
    
    return {
        'report_path': report_path,
        'logic_candidates': len(candidates),
        'gated_candidates': len(gated),
        'logic_result': logic_result,
        'flow_result': flow_result,
        'temperature': temperature,
        'monthly_pool_data': monthly_pool_data,
    }


def main():
    parser = argparse.ArgumentParser(description='双弦投资系统v2.2')
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
    temp = result.get('temperature')
    temp_str = f"🌡️{temp['score']}/100{temp.get('emoji','')}" if temp else ""
    print(f"\n📊 双弦系统v2.2: {temp_str} 逻辑链{logic}只 → 共振{gated}只")
    if result.get('report_path'):
        print(f"📄 报告: {result['report_path']}")
    
    return result


if __name__ == '__main__':
    main()
