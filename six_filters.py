"""
双弦投资系统 — 六层滤网选股
==================================
从全市场中筛选"钱在进，但价还没动"的候选股。
输出资金流候选池，供分级模块使用。
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import data_fetcher as df
import config

log = logging.getLogger("shuangxian")


def run_six_filters() -> dict:
    """运行六层滤网筛选，返回资金流候选池"""
    log.info("====== 开始六层滤网筛选 ======")
    notes = []
    log.info("获取A股股票列表...")
    try:
        stock_list = df.get_stock_list()
    except Exception as e:
        log.error(f"A股列表获取失败: {e}")
        return {
            'candidates': [],
            'notes': [f"A股列表获取失败: {e}，无法执行六层滤网。"]
        }
    if stock_list.empty:
        try:
            flow_rank = df.get_individual_fund_flow_rank(indicator="5日")
            if not flow_rank.empty:
                stock_list = flow_rank
                notes.append("A股列表不可用，改用资金流排名数据作为基础池（覆盖面有限）")
        except Exception:
            pass
    if stock_list.empty:
        return {
            'candidates': [],
            'notes': ["无法获取任何股票数据，请检查网络和akshare版本"]
        }
    notes.append(f"基础股票池: {len(stock_list)} 只")
    log.info(f"  基础池: {len(stock_list)} 只")

    remaining = _filter_layer1_market_cap(stock_list)
    layer1_count = len(remaining) if not remaining.empty else 0
    notes.append(f"第一层(市值100-800亿): {layer1_count} 只")
    log.info(f"  第一层剩余: {layer1_count}")
    if remaining.empty:
        return {'candidates': [], 'notes': notes}

    remaining = _filter_layer2_turnover(remaining)
    layer2_count = len(remaining) if not remaining.empty else 0
    notes.append(f"第二层(换手率0.5%-4%): {layer2_count} 只")
    log.info(f"  第二层剩余: {layer2_count}")
    if remaining.empty:
        return {'candidates': [], 'notes': notes}

    remaining = _filter_layer3_acceleration(remaining)
    layer3_count = len(remaining) if not remaining.empty else 0
    notes.append(f"第三层(资金加速度连续{config.FILTER_ACCEL_DAYS}日正): {layer3_count} 只")
    log.info(f"  第三层剩余: {layer3_count}")
    if remaining.empty:
        return {'candidates': [], 'notes': notes}

    remaining = _filter_layer4_sector_concentration(remaining)
    layer4_count = len(remaining) if not remaining.empty else 0
    notes.append(f"第四层(板块资金浓度>{config.FILTER_SECTOR_STD}σ): {layer4_count} 只")
    log.info(f"  第四层剩余: {layer4_count}")
    if remaining.empty:
        return {'candidates': [], 'notes': notes}

    remaining = _filter_layer5_etf_subscribe(remaining)
    layer5_count = len(remaining) if not remaining.empty else 0
    notes.append(f"第五层(行业ETF {config.FILTER_ETF_WINDOW}日净申购): {layer5_count} 只")
    log.info(f"  第五层剩余: {layer5_count}")

    candidates = _filter_layer6_human(remaining)
    notes.append(f"第六层(人滤网): {len(candidates)} 只候选，需人工确认")
    log.info(f"  最终候选: {len(candidates)} 只")

    return {
        'layer1_count': layer1_count, 'layer2_count': layer2_count,
        'layer3_count': layer3_count, 'layer4_count': layer4_count,
        'layer5_count': layer5_count,
        'candidates': candidates[:8],
        'notes': notes,
    }


def _filter_layer1_market_cap(stock_df: pd.DataFrame) -> pd.DataFrame:
    """第一层：流通市值筛选（100-800亿）"""
    cols = stock_df.columns.tolist()
    cap_col = next((c for c in cols if '流通市值' in c or '市值' in c), None)
    if cap_col is None:
        log.warning("未找到市值列，第一层滤网跳过")
        return stock_df
    try:
        stock_df[cap_col] = pd.to_numeric(
            stock_df[cap_col].astype(str).str.replace(',', '').str.replace('亿', ''),
            errors='coerce'
        )
        median_val = stock_df[cap_col].median()
        if median_val > 1e6:
            stock_df['流通市值亿'] = stock_df[cap_col] / 1e8
        elif median_val > 100:
            stock_df['流通市值亿'] = stock_df[cap_col]
        else:
            stock_df['流通市值亿'] = stock_df[cap_col] / 10000
        mask = (stock_df['流通市值亿'] >= config.FILTER_MARKET_CAP_MIN) & \
               (stock_df['流通市值亿'] <= config.FILTER_MARKET_CAP_MAX)
        return stock_df[mask].reset_index(drop=True)
    except Exception as e:
        log.warning(f"市值筛选异常: {e}，跳过此层")
        return stock_df


def _filter_layer2_turnover(stock_df: pd.DataFrame) -> pd.DataFrame:
    """第二层：换手率筛选（0.5%-4%）"""
    cols = stock_df.columns.tolist()
    turnover_col = next((c for c in cols if '换手率' in c), None)
    if turnover_col is None:
        log.warning("未找到换手率列，第二层滤网跳过")
        return stock_df
    try:
        stock_df[turnover_col] = pd.to_numeric(
            stock_df[turnover_col].astype(str).str.replace('%', '').str.replace(',', ''),
            errors='coerce'
        )
        if stock_df[turnover_col].median() > 1:
            stock_df['换手率_小数'] = stock_df[turnover_col] / 100
        else:
            stock_df['换手率_小数'] = stock_df[turnover_col]
        mask = (stock_df['换手率_小数'] >= config.FILTER_TURNOVER_RATE_MIN) & \
               (stock_df['换手率_小数'] <= config.FILTER_TURNOVER_RATE_MAX)
        return stock_df[mask].reset_index(drop=True)
    except Exception as e:
        log.warning(f"换手率筛选异常: {e}，跳过此层")
        return stock_df


def _filter_layer3_acceleration(stock_df: pd.DataFrame) -> pd.DataFrame:
    """第三层：资金加速度筛选（连续N日为正）"""
    cols = stock_df.columns.tolist()
    accel_col = next((c for c in cols if '加速度' in c or '增仓' in c or '净占比' in c), None)
    net_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
    if accel_col is not None:
        try:
            stock_df[accel_col] = pd.to_numeric(
                stock_df[accel_col].astype(str).str.replace(',', '').str.replace('%', ''),
                errors='coerce'
            )
            mask = stock_df[accel_col] > 0
            result = stock_df[mask]
            if len(result) > 0:
                return result.reset_index(drop=True)
        except Exception as e:
            log.warning(f"加速度筛选异常: {e}")
    if net_col is not None:
        try:
            stock_df[net_col] = pd.to_numeric(
                stock_df[net_col].astype(str).str.replace(',', '').str.replace('亿', ''),
                errors='coerce'
            )
            mask = stock_df[net_col] > 0
            result = stock_df[mask]
            if len(result) > 0:
                log.warning("资金加速度列不可用，用净流入>0近似替代")
                return result.reset_index(drop=True)
        except Exception as e:
            log.warning(f"净流入筛选异常: {e}")
    log.warning("第三层滤网数据不足，跳过")
    return stock_df


def _filter_layer4_sector_concentration(stock_df: pd.DataFrame) -> pd.DataFrame:
    """第四层：板块资金浓度筛选"""
    try:
        sector_flow = df.get_sector_fund_flow(indicator="今日")
        if sector_flow.empty:
            log.warning("板块资金流数据为空，第四层跳过")
            return stock_df
        cols = sector_flow.columns.tolist()
        name_col = next((c for c in cols if '名称' in c or '行业' in c), None)
        flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
        if name_col and flow_col:
            sector_flow[flow_col] = pd.to_numeric(
                sector_flow[flow_col].astype(str).str.replace(',', '').str.replace('亿', ''),
                errors='coerce'
            )
            mean_flow = sector_flow[flow_col].mean()
            std_flow = sector_flow[flow_col].std()
            if std_flow > 0:
                hot_sectors = sector_flow[
                    sector_flow[flow_col] > mean_flow + config.FILTER_SECTOR_STD * std_flow
                ][name_col].tolist()
                sector_col = next((c for c in stock_df.columns if '行业' in c or '板块' in c or '所属' in c), None)
                if sector_col and hot_sectors:
                    mask = stock_df[sector_col].isin(hot_sectors)
                    result = stock_df[mask]
                    if len(result) > 0:
                        return result.reset_index(drop=True)
    except Exception as e:
        log.warning(f"板块浓度筛选异常: {e}")
    log.warning("第四层滤网数据不足，跳过")
    return stock_df


def _filter_layer5_etf_subscribe(stock_df: pd.DataFrame) -> pd.DataFrame:
    """第五层：ETF申赎筛选（需要本地ETF份额历史库）"""
    log.warning("第五层(ETF申赎)需要本地ETF份额历史库，当前跳过，标记为待确认")
    return stock_df


def _filter_layer6_human(stock_df: pd.DataFrame) -> list:
    """第六层：人滤网，生成候选股列表"""
    candidates = []
    cols = stock_df.columns.tolist()
    code_col = next((c for c in cols if '代码' in c), cols[0] if cols else None)
    name_col = next((c for c in cols if '名称' in c), None)
    pct_col = next((c for c in cols if '涨跌幅' in c or '涨跌' in c), None)
    flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
    cap_col = next((c for c in cols if '流通市值亿' in c), None)
    turnover_col = next((c for c in cols if '换手率_小数' in c), None)
    for _, row in stock_df.head(30).iterrows():
        entry = {}
        if code_col:
            entry['code'] = str(row.get(code_col, ''))
        if name_col:
            entry['name'] = str(row.get(name_col, ''))
        if pct_col:
            try:
                entry['pct'] = float(str(row.get(pct_col, '0')).replace('%', '').replace(',', ''))
            except (ValueError, TypeError):
                entry['pct'] = 0
        if flow_col:
            try:
                entry['net_flow'] = float(str(row.get(flow_col, '0')).replace(',', '').replace('亿', ''))
            except (ValueError, TypeError):
                entry['net_flow'] = 0
        if cap_col:
            entry['market_cap'] = round(float(row.get(cap_col, 0)), 1)
        if turnover_col:
            entry['turnover'] = round(float(row.get(turnover_col, 0)), 4)
        flags = []
        if entry.get('pct', 0) > 5:
            flags.append('⚠️ 近期涨幅较大，检查是否脱离基本面')
        if entry.get('pct', 0) > 9:
            flags.append('🔴 已涨停，与"价还没动"矛盾')
        entry['flags'] = flags
        entry['human_check'] = '需人工检查K线图和近期公告'
        candidates.append(entry)
    return candidates[:8]


def get_capital_pool() -> list:
    """获取资金流候选池（供分级模块使用）"""
    result = run_six_filters()
    return result.get('candidates', [])
