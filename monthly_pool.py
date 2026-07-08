"""
双弦投资系统 v2.2 — 月度股票池管理
======================================
累积本月所有共振+低吸信号中股价≤MAX_PRICE的股票，按月管理JSON文件。

数据结构：每个股票记录
{
    "code": "600519",
    "name": "贵州茅台",
    "first_seen": "2026-07-01",
    "last_seen": "2026-07-08",
    "count": 3,
    "industry": "食品饮料",
    "signals": ["共振", "低吸"]
}

文件命名：monthly_pool_YYYYMM.json
月初自动创建新文件，月末文件归档不动。
"""

import os
import json
import logging
from datetime import datetime

import config

log = logging.getLogger("shuangxian.monthly_pool")


def _pool_dir() -> str:
    """获取股池目录绝对路径，自动创建"""
    # MONTHLY_POOL_DIR 默认为 "./monthly_pool"，相对于系统目录
    pool_dir = config.MONTHLY_POOL_DIR
    if not os.path.isabs(pool_dir):
        pool_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), pool_dir)
    os.makedirs(pool_dir, exist_ok=True)
    return pool_dir


def _pool_filepath(year_month: str) -> str:
    """
    生成股池文件路径
    year_month: "2026-07" 格式
    """
    ym_compact = year_month.replace("-", "")  # "202607"
    filename = f"monthly_pool_{ym_compact}.json"
    return os.path.join(_pool_dir(), filename)


def load_pool(year_month: str) -> dict:
    """
    加载指定月份的股池数据

    参数:
        year_month: "2026-07" 格式

    返回:
        {code: {stock_record_dict}, ...}
        如果文件不存在返回空dict
    """
    filepath = _pool_filepath(year_month)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            log.info(f"  月度股池加载: {filepath} ({len(data)}只)")
            return data
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"  月度股池加载失败: {filepath}, {e}")
            return {}
    else:
        log.info(f"  月度股池新文件: {year_month}")
        return {}


def save_pool(year_month: str, pool_data: dict) -> str:
    """
    保存股池数据到JSON文件

    参数:
        year_month: "2026-07" 格式
        pool_data: {code: {stock_record_dict}, ...}

    返回:
        保存的文件路径
    """
    filepath = _pool_filepath(year_month)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(pool_data, f, ensure_ascii=False, indent=2)
    log.info(f"  月度股池保存: {filepath} ({len(pool_data)}只)")
    return filepath


def update_pool(gated_candidates: list, divergence_signals: list,
                today_str: str = None) -> dict:
    """
    更新月度股池：将当日共振和低吸信号中的低价股累积到股池

    参数:
        gated_candidates: AND门控通过的候选股列表（共振信号）
        divergence_signals: 底背离买点信号列表（低吸信号）
        today_str: 当日日期 "YYYY-MM-DD"，默认今天

    返回:
        更新后的股池数据 {code: {stock_record_dict}, ...}
    """
    if not config.MONTHLY_POOL_ENABLED:
        log.info("  月度股池: 已禁用")
        return {}

    if today_str is None:
        today_str = datetime.now().strftime('%Y-%m-%d')

    year_month = today_str[:7]  # "2026-07"
    price_threshold = config.MAX_PRICE

    # 加载当月已有数据
    pool_data = load_pool(year_month)

    # ── 处理共振信号 ──────────────────────────────────
    for cand in gated_candidates:
        code = cand.get('code', '')
        close = cand.get('close', 0)
        if not code:
            continue
        # 只保留股价≤MAX_PRICE的
        if not (0 < close <= price_threshold):
            continue

        name = cand.get('name', '')
        industry = cand.get('industry', '')

        if code in pool_data:
            # 已有记录：更新last_seen、count、信号类型
            record = pool_data[code]
            record['last_seen'] = today_str
            record['count'] = record.get('count', 0) + 1
            if '共振' not in record.get('signals', []):
                record.setdefault('signals', []).append('共振')
            # 更新行业（可能首次没有行业信息）
            if industry and industry != '未知' and (not record.get('industry') or record.get('industry') == '未知'):
                record['industry'] = industry
            # 更新名称（可能首次没有名称）
            if name and (not record.get('name')):
                record['name'] = name
        else:
            # 新增记录
            pool_data[code] = {
                'code': code,
                'name': name,
                'first_seen': today_str,
                'last_seen': today_str,
                'count': 1,
                'industry': industry,
                'signals': ['共振'],
            }

    # ── 处理低吸信号（底背离）──────────────────────────
    for div in divergence_signals:
        code = div.get('code', '')
        close = div.get('close', 0)
        if not code:
            continue
        # 只保留股价≤MAX_PRICE的
        if not (0 < close <= price_threshold):
            continue

        name = div.get('name', '')
        industry = div.get('industry', '')

        if code in pool_data:
            # 已有记录：更新last_seen、count、信号类型
            record = pool_data[code]
            record['last_seen'] = today_str
            record['count'] = record.get('count', 0) + 1
            if '低吸' not in record.get('signals', []):
                record.setdefault('signals', []).append('低吸')
            # 更新行业
            if industry and industry != '未知' and (not record.get('industry') or record.get('industry') == '未知'):
                record['industry'] = industry
            # 更新名称
            if name and (not record.get('name')):
                record['name'] = name
        else:
            # 新增记录
            pool_data[code] = {
                'code': code,
                'name': name,
                'first_seen': today_str,
                'last_seen': today_str,
                'count': 1,
                'industry': industry,
                'signals': ['低吸'],
            }

    # 保存
    save_pool(year_month, pool_data)

    # 统计
    total = len(pool_data)
    both_signals = sum(1 for r in pool_data.values() if len(r.get('signals', [])) >= 2)
    log.info(f"  月度股池更新: +{today_str}, 共{total}只(双信号{both_signals}只)")

    return pool_data


def get_pool_sorted(year_month: str = None) -> list:
    """
    获取股池按count降序排列的列表

    参数:
        year_month: "2026-07" 格式，默认当月

    返回:
        [stock_record_dict, ...] 按count降序排列
    """
    if year_month is None:
        year_month = datetime.now().strftime('%Y-%m')

    pool_data = load_pool(year_month)
    if not pool_data:
        return []

    sorted_list = sorted(
        pool_data.values(),
        key=lambda x: (x.get('count', 0), x.get('last_seen', '')),
        reverse=True
    )
    return sorted_list
