"""
双弦投资系统 v2.2 — 月度股票池管理
======================================
分两个独立股池：
  1. 共振股池：累积本月共振信号中股价≤MAX_PRICE的股票
  2. 底背离股池：累积本月底背离(低吸)信号中股价≤MAX_PRICE的股票

文件命名：
  monthly_pool_YYYYMM.json      (共振股池)
  monthly_div_pool_YYYYMM.json  (底背离股池)
"""

import os
import json
import logging
from datetime import datetime

import config

log = logging.getLogger("shuangxian.monthly_pool")


def _pool_dir() -> str:
    """获取股池目录绝对路径，自动创建"""
    pool_dir = config.MONTHLY_POOL_DIR
    if not os.path.isabs(pool_dir):
        pool_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), pool_dir)
    os.makedirs(pool_dir, exist_ok=True)
    return pool_dir


def _pool_filepath(year_month: str, pool_type: str = "resonance") -> str:
    """
    生成股池文件路径
    pool_type: "resonance"(共振) / "divergence"(底背离)
    """
    ym_compact = year_month.replace("-", "")
    prefix = "monthly_pool" if pool_type == "resonance" else "monthly_div_pool"
    return os.path.join(_pool_dir(), f"{prefix}_{ym_compact}.json")


def load_pool(year_month: str, pool_type: str = "resonance") -> dict:
    """加载指定月份的股池数据"""
    filepath = _pool_filepath(year_month, pool_type)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            log.info(f"  {pool_type}股池加载: {filepath} ({len(data)}只)")
            return data
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"  {pool_type}股池加载失败: {filepath}, {e}")
            return {}
    else:
        log.info(f"  {pool_type}股池新文件: {year_month}")
        return {}


def save_pool(year_month: str, pool_data: dict, pool_type: str = "resonance") -> str:
    """保存股池数据到JSON文件"""
    filepath = _pool_filepath(year_month, pool_type)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(pool_data, f, ensure_ascii=False, indent=2)
    log.info(f"  {pool_type}股池保存: {filepath} ({len(pool_data)}只)")
    return filepath


def _update_single_pool(pool_data: dict, signal_list: list, signal_tag: str,
                        today_str: str, price_threshold: float) -> dict:
    """通用单股池更新逻辑"""
    for item in signal_list:
        code = item.get('code', '')
        close = item.get('close', 0)
        if not code:
            continue
        if not (0 < close <= price_threshold):
            continue

        name = item.get('name', '')
        industry = item.get('industry', '')

        if code in pool_data:
            record = pool_data[code]
            record['last_seen'] = today_str
            record['count'] = record.get('count', 0) + 1
            if signal_tag not in record.get('signals', []):
                record.setdefault('signals', []).append(signal_tag)
            if industry and industry != '未知' and (not record.get('industry') or record.get('industry') == '未知'):
                record['industry'] = industry
            if name and (not record.get('name')):
                record['name'] = name
        else:
            pool_data[code] = {
                'code': code,
                'name': name,
                'first_seen': today_str,
                'last_seen': today_str,
                'count': 1,
                'industry': industry,
                'signals': [signal_tag],
            }
    return pool_data


def update_pool(gated_candidates: list, divergence_signals: list,
                today_str: str = None) -> dict:
    """
    更新月度股池（双股池：共振+底背离分离）

    参数:
        gated_candidates: AND门控通过的候选股列表（共振信号）
        divergence_signals: 底背离买点信号列表（低吸信号）
        today_str: 当日日期 "YYYY-MM-DD"

    返回:
        {
            "resonance": {code: record, ...},
            "divergence": {code: record, ...}
        }
    """
    if not config.MONTHLY_POOL_ENABLED:
        log.info("  月度股池: 已禁用")
        return {"resonance": {}, "divergence": {}}

    if today_str is None:
        today_str = datetime.now().strftime('%Y-%m-%d')

    year_month = today_str[:7]
    price_threshold = config.MAX_PRICE

    # ── 共振股池 ──
    res_pool = load_pool(year_month, "resonance")
    res_pool = _update_single_pool(res_pool, gated_candidates, "共振",
                                   today_str, price_threshold)
    save_pool(year_month, res_pool, "resonance")

    # ── 底背离股池 ──
    div_pool = load_pool(year_month, "divergence")
    div_pool = _update_single_pool(div_pool, divergence_signals, "低吸",
                                   today_str, price_threshold)
    save_pool(year_month, div_pool, "divergence")

    # 统计
    res_total = len(res_pool)
    div_total = len(div_pool)
    log.info(f"  月度股池更新: +{today_str}, 共振{res_total}只, 底背离{div_total}只")

    return {"resonance": res_pool, "divergence": div_pool}


def get_pool_sorted(year_month: str = None, pool_type: str = "resonance") -> list:
    """获取股池按count降序排列的列表"""
    if year_month is None:
        year_month = datetime.now().strftime('%Y-%m')

    pool_data = load_pool(year_month, pool_type)
    if not pool_data:
        return []

    return sorted(
        pool_data.values(),
        key=lambda x: (x.get('count', 0), x.get('last_seen', '')),
        reverse=True
    )
