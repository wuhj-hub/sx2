"""
双弦投资系统 v2.0 — 数据获取层
==================================
Sina财经为主数据源（GitHub Actions稳定可用）
efinance/akshare/push2/datacenter-web/Tushare为备用降级链路
逻辑链数据(Sina K线) + 资金流数据(Sina板块/个股)

数据源优先级（按稳定性排序）：
  K线数据: Sina → efinance(push2his) → akshare
  行业映射: efinance(get_base_info) → akshare(逐行业) → Sina(板块节点)
  板块资金流: Sina → push2 → datacenter-web
  个股资金流: akshare → push2 → Tushare
"""

import time
import logging
import urllib.request
import urllib.parse
import json
import os
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# Python 3.13 兼容补丁
try:
    import pkgutil
    if not hasattr(pkgutil, 'ImpImporter'):
        pkgutil.ImpImporter = type('ImpImporter', (), {})
except Exception:
    pass

import akshare as ak

try:
    import efinance as ef
    HAS_EFINANCE = True
except ImportError:
    HAS_EFINANCE = False

# 东方财富行业名 → 申万行业名 映射
# efinance get_base_info 返回东财行业名(如"酿酒行业")，需映射回申万标准名
# 才能与 flow_chain.py 的 SW_TO_SINA（申万→Sina）对接
EM_TO_SW = {
    '酿酒行业': '食品饮料', '家电行业': '家用电器', '汽车制造': '汽车',
    '电子信息': '计算机', '电子器件': '电子', '生物制药': '医药生物',
    '机械行业': '机械设备', '化工行业': '化工', '钢铁行业': '钢铁',
    '房地产': '房地产', '金融行业': '非银金融', '石油行业': '石油石化',
    '煤炭行业': '煤炭', '有色金属': '有色金属', '纺织行业': '纺织服装',
    '建筑建材': '建筑材料', '建材行业': '建筑材料', '建筑装饰': '建筑装饰',
    '交通运输': '交通运输', '酒店旅游': '社会服务', '商业百货': '商贸零售',
    '农牧饲渔': '农林牧渔', '电力行业': '公用事业', '环保行业': '环保',
    '综合行业': '综合', '印刷包装': '轻工制造', '国防军工': '国防军工',
    '传媒娱乐': '传媒', '宽带提速': '通信', '银行': '银行',
    '发电设备': '电气设备', '保险': '非银金融', '证券': '非银金融',
    '多元金融': '非银金融', '采掘行业': '采掘', '旅游酒店': '社会服务',
    '文教休闲': '休闲服务', '工艺商品': '轻工制造', '农药兽药': '农林牧渔',
    '塑胶制品': '化工', '玻璃陶瓷': '建筑材料', '珠宝首饰': '轻工制造',
}

import config

log = logging.getLogger("shuangxian")


# ── 工具函数 ──────────────────────────────────────────────

def _safe_float(val, default=0.0):
    try:
        if val == '-' or val is None or val == '':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _retry(func, retries=3, delay=2, **kwargs):
    for i in range(retries):
        try:
            return func(**kwargs)
        except Exception as e:
            if i < retries - 1:
                log.warning(f"[重试 {i+1}/{retries}] {func.__name__} 失败: {e}")
                time.sleep(delay)
            else:
                log.error(f"[放弃] {func.__name__} 最终失败: {e}")
                raise


def _sina_request(url, timeout=15):
    """通用Sina请求，带超时和重试"""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://finance.sina.com.cn/',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode('utf-8')
    except Exception as e:
        log.debug(f"Sina请求失败: {url[:80]}... → {e}")
        return None


# ════════════════════════════════════════════════════════
#  逻辑链弦：K线数据（Sina为主）
# ════════════════════════════════════════════════════════

def get_sina_kline(symbol: str, scale: int = 240, datalen: int = 600) -> pd.DataFrame:
    """
    Sina财经K线数据
    scale: 240=日线, 60=60分钟
    symbol: sh000300, sz300750, sh600519 等
    """
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/=/"
           f"CN_MarketDataService.getKLineData?"
           f"symbol={symbol}&scale={scale}&datalen={datalen}")
    raw = _sina_request(url)
    if not raw:
        return pd.DataFrame()
    try:
        # jsonp格式: /*<script>...</script>*/=([...]);
        # 提取 [] 之间的JSON数组
        start = raw.index('[')
        end = raw.rindex(']') + 1
        data = json.loads(raw[start:end])
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        for c in ['open', 'high', 'low', 'close', 'volume']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        if 'day' in df.columns:
            df['day'] = pd.to_datetime(df['day'])
        df = df.sort_values('day').reset_index(drop=True)
        return df
    except Exception as e:
        log.warning(f"Sina K线解析失败 {symbol}: {e}")
        return pd.DataFrame()


def _efinance_kline(symbol: str, datalen: int = 600) -> pd.DataFrame:
    """
    efinance K线数据（Sina降级备用）
    底层用push2his.eastmoney.com，GitHub Actions通常可用
    
    symbol: sh600519 / sz300750 等
    返回格式与get_sina_kline一致
    """
    if not HAS_EFINANCE:
        return pd.DataFrame()
    try:
        # efinance用纯数字代码
        code = symbol[2:] if len(symbol) > 2 else symbol
        df = ef.stock.get_quote_history(code, klt=101, fqt=1)
        if df is None or df.empty:
            return pd.DataFrame()
        # 统一列名
        col_map = {
            '日期': 'day', '开盘': 'open', '收盘': 'close',
            '最高': 'high', '最低': 'low', '成交量': 'volume',
        }
        rename = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=rename)
        if 'day' in df.columns:
            df['day'] = pd.to_datetime(df['day'])
        for c in ['open', 'high', 'low', 'close', 'volume']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        # 只保留需要的列
        keep = [c for c in ['day', 'open', 'high', 'low', 'close', 'volume'] if c in df.columns]
        df = df[keep].sort_values('day').tail(datalen).reset_index(drop=True)
        return df
    except Exception as e:
        log.debug(f"efinance K线失败 {symbol}: {e}")
        return pd.DataFrame()


def get_kline(symbol: str, scale: int = 240, datalen: int = 600) -> pd.DataFrame:
    """
    统一K线获取入口（Sina → efinance → akshare 三级降级）
    scale: 240=日线（目前仅日线用于月线聚合和信号检测）
    symbol: sh600519 / sz300750 等
    datalen: 默认600根日线(~2.5年)，月线分析需~530天，日线信号需~130天
    """
    # 主源：Sina
    df = get_sina_kline(symbol, scale=scale, datalen=datalen)
    if not df.empty:
        return df
    
    # 降级1：efinance
    if scale == 240:  # 仅日线降级
        log.debug(f"  Sina K线失败 {symbol}，降级efinance...")
        df = _efinance_kline(symbol, datalen=datalen)
        if not df.empty:
            log.debug(f"  efinance K线成功 {symbol}")
            return df
    
    # 降级2：akshare（最后兜底）
    log.debug(f"  efinance K线失败 {symbol}，降级akshare...")
    try:
        code = symbol[2:] if len(symbol) > 2 else symbol
        df = _retry(ak.stock_zh_a_hist, symbol=code, period='daily', adjust='qfq')
        if df is not None and not df.empty:
            col_map = {
                '日期': 'day', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low', '成交量': 'volume',
            }
            rename = {k: v for k, v in col_map.items() if k in df.columns}
            df = df.rename(columns=rename)
            if 'day' in df.columns:
                df['day'] = pd.to_datetime(df['day'])
            for c in ['open', 'high', 'low', 'close', 'volume']:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
            df = df.sort_values('day').tail(datalen).reset_index(drop=True)
            return df
    except Exception as e:
        log.debug(f"  akshare K线失败 {symbol}: {e}")
    
    return pd.DataFrame()


def get_sina_realtime_batch(codes: list) -> dict:
    """
    批量获取Sina实时行情
    codes: ['sh600519', 'sz300750', ...]
    返回: {code: {name, close, pct_change, volume, amount, ...}}
    """
    result = {}
    # Sina hq.sinajs.cn 一次最多约800只
    batch_size = 200
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        url = f"https://hq.sinajs.cn/list={','.join(batch)}"
        raw = _sina_request(url)
        if not raw:
            continue
        try:
            for line in raw.strip().split('\n'):
                if '=' not in line:
                    continue
                var_part, data_part = line.split('=', 1)
                code = var_part.split('_')[-1].strip('"')
                data_str = data_part.strip().strip('";')
                if not data_str:
                    continue
                fields = data_str.split(',')
                if len(fields) >= 32:
                    prev_close = float(fields[2]) if fields[2] else 0
                    close = float(fields[3]) if fields[3] else 0
                    pct_change = ((close - prev_close) / prev_close * 100) if prev_close else 0
                    result[code] = {
                        'name': fields[0],
                        'open': float(fields[1]) if fields[1] else 0,
                        'prev_close': prev_close,
                        'close': close,
                        'high': float(fields[4]) if fields[4] else 0,
                        'low': float(fields[5]) if fields[5] else 0,
                        'volume': float(fields[8]) if fields[8] else 0,
                        'amount': float(fields[9]) if fields[9] else 0,
                        'pct_change': pct_change,
                        'date': fields[30],
                        'time': fields[31],
                    }
        except Exception as e:
            log.debug(f"Sina实时行情解析失败: {e}")
    return result


def get_stock_pool() -> list:
    """
    获取股票池：沪深300 + 中证500 + 中证1000
    返回: [{'symbol': 'sh600519', 'code': '600519', 'name': '贵州茅台', 'pool': 'hs300'}, ...]
    """
    stocks = []
    # 用akshare获取成分股
    for idx_code, pool_name in [("000300", "hs300"), ("000905", "zz500"), ("000852", "zz1000")]:
        try:
            df = _retry(ak.index_stock_cons_csindex, symbol=idx_code)
            if df is not None and not df.empty:
                # 列名: 日期, 指数代码, 指数名称, 指数英文名称, 成分券代码, 成分券名称, ...
                code_col = '成分券代码' if '成分券代码' in df.columns else df.columns[4]
                name_col = '成分券名称' if '成分券名称' in df.columns else df.columns[5]
                for _, row in df.iterrows():
                    code = str(row[code_col]).zfill(6)
                    name = str(row[name_col])
                    prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0','3')) else 'bj')
                    stocks.append({
                        'symbol': f'{prefix}{code}',
                        'code': code,
                        'name': name,
                        'pool': pool_name,
                    })
                log.info(f"  {pool_name}({idx_code}): {len(df)}只")
        except Exception as e:
            log.warning(f"  {pool_name}({idx_code})获取失败: {e}")
    
    # 去重(保留最小池的标记，hs300优先)
    seen = {}
    pool_priority = {'hs300': 0, 'zz500': 1, 'zz1000': 2}
    for s in stocks:
        code = s['code']
        if code not in seen or pool_priority.get(s['pool'], 9) < pool_priority.get(seen[code]['pool'], 9):
            seen[code] = s
    result = list(seen.values())
    log.info(f"  股票池总计: {len(result)}只(去重后)")
    return result


def get_industry_constituents() -> dict:
    """
    获取行业板块成分股 → {行业名: [symbol1, symbol2, ...]}
    同时返回反向映射 → 存入 industry_map.json
    
    优先级：
    1. efinance get_base_info（1次批量查询，返回"所处行业"字段，最稳定）
    2. akshare 逐行业获取成分股（31次API调用，容易连接断开）
    3. Sina 申万行业板块节点（兜底，31个行业全覆盖）
    """
    industry_map = {}   # symbol → industry_name (key格式: sh600519)
    industry_stocks = {}  # industry_name → [symbols]
    
    # ── 主源1：efinance get_base_info ──────────────────
    # 优势：1次批量查询获取所有股票的行业，不需要逐行业调用
    if HAS_EFINANCE:
        try:
            log.info("  获取行业分类(efinance get_base_info)...")
            # 获取股票池所有代码
            pool = get_stock_pool()
            codes = [s['code'] for s in pool]
            
            # efinance get_base_info 支持批量查询
            # 分批查询（每批200只，避免单次请求过大）
            batch_size = 200
            all_info = []
            for i in range(0, len(codes), batch_size):
                batch = codes[i:i+batch_size]
                try:
                    info = ef.stock.get_base_info(batch)
                    if info is not None:
                        if isinstance(info, pd.DataFrame):
                            all_info.append(info)
                        elif isinstance(info, pd.Series):
                            all_info.append(info.to_frame().T)
                except Exception as e:
                    log.debug(f"  efinance批次{i//batch_size+1}失败: {e}")
            
            if all_info:
                info_df = pd.concat(all_info, ignore_index=True)
                # 列名含"股票代码"和"所处行业"
                code_col = next((c for c in info_df.columns if '代码' in c), None)
                ind_col = next((c for c in info_df.columns if '行业' in c), None)
                
                if code_col and ind_col:
                    for _, row in info_df.iterrows():
                        code = str(row[code_col]).zfill(6)
                        em_ind_name = str(row[ind_col])
                        if not code or not em_ind_name or em_ind_name == 'nan':
                            continue
                        # 东财行业名 → 申万行业名（与SW_TO_SINA对接）
                        ind_name = EM_TO_SW.get(em_ind_name, em_ind_name)
                        prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0','3')) else 'bj')
                        sym = f'{prefix}{code}'
                        industry_map[sym] = ind_name
                        if ind_name not in industry_stocks:
                            industry_stocks[ind_name] = []
                        industry_stocks[ind_name].append(sym)
                    
                    if len(industry_map) >= 500:
                        log.info(f"  行业映射(efinance): {len(industry_map)}只股票, {len(industry_stocks)}个行业")
                        return industry_map, industry_stocks
                    else:
                        log.warning(f"  efinance行业映射仅{len(industry_map)}只，降级akshare")
                else:
                    log.warning(f"  efinance返回列名异常: {info_df.columns.tolist()}，降级akshare")
            else:
                log.warning("  efinance get_base_info返回空，降级akshare")
        except Exception as e:
            log.warning(f"  efinance行业分类获取失败: {e}，降级akshare")
    
    # ── 主源2：akshare 东方财富行业板块 ──────────────────
    try:
        log.info("  获取行业分类(akshare东方财富)...")
        # 获取所有行业板块名称
        board_df = _retry(ak.stock_board_industry_name_em)
        if board_df is not None and not board_df.empty:
            # 申万一级行业（31个）— 排除概念板块
            sw_industries = [
                '钢铁', '采掘', '化工', '有色金属', '建筑材料', '建筑装饰',
                '电气设备', '机械设备', '国防军工', '汽车', '家用电器',
                '轻工制造', '食品饮料', '纺织服装', '医药生物', '农林牧渔',
                '商贸零售', '社会服务', '银行', '非银金融', '房地产',
                '交通运输', '电子', '计算机', '通信', '传媒', '公用事业',
                '环保', '综合', '煤炭', '石油石化',
            ]
            matched = 0
            for ind_name in sw_industries:
                try:
                    cons_df = _retry(ak.stock_board_industry_cons_em, symbol=ind_name)
                    if cons_df is not None and not cons_df.empty:
                        code_col = next((c for c in cons_df.columns if '代码' in c), None)
                        if code_col:
                            symbols = []
                            for code in cons_df[code_col].astype(str):
                                code = code.zfill(6)
                                prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0','3')) else 'bj')
                                sym = f'{prefix}{code}'
                                symbols.append(sym)
                                industry_map[sym] = ind_name
                            industry_stocks[ind_name] = symbols
                            matched += 1
                            log.info(f"  行业 {ind_name}: {len(symbols)}只")
                except Exception as e:
                    log.debug(f"  行业 {ind_name} 获取失败: {e}")
            
            if matched >= 10:
                log.info(f"  行业映射(akshare): {len(industry_map)}只股票, {matched}个行业")
                return industry_map, industry_stocks
            else:
                log.warning(f"  akshare行业映射仅{matched}个行业，降级Sina")
    except Exception as e:
        log.warning(f"  akshare行业板块获取失败: {e}，降级Sina")
    
    # ── 兜底：Sina 申万行业板块节点（31个全覆盖） ──────
    log.info("  降级获取行业分类(Sina)...")
    industry_nodes = [
        ('sw_gt', '钢铁'), ('sw_jtys', '交通运输'), ('sw_gcls', '建筑装饰'),
        ('sw_jsj', '计算机'), ('sw_dz', '电子'), ('sw_yx', '银行'),
        ('sw_fdc', '房地产'), ('sw_yl', '医药生物'), ('sw_jx', '机械设备'),
        ('sw_qc', '汽车'), ('sw_sy', '商贸零售'), ('sw_hg', '化工'),
        ('sw_jz', '建筑材料'), ('sw_dy', '公用事业'), ('sw_ny', '石油石化'),
        ('sw_jr', '非银金融'), ('sw_sp', '食品饮料'), ('sw_jj', '家用电器'),
        ('sw_mt', '煤炭'), ('sw_youse', '有色金属'), ('sw_gf', '国防军工'),
        ('sw_nlm', '农林牧渔'), ('sw_zh', '综合'),
        # 补全v2.0缺失的8个行业节点
        ('sw_dqsb', '电气设备'), ('sw_qgz', '轻工制造'),
        ('sw_cm', '传媒'), ('sw_hb', '环保'),
        ('sw_tx', '通信'), ('sw_xxfw', '社会服务'),
        ('sw_fz', '纺织服装'), ('sw_xxyl', '休闲服务'),
    ]
    
    for node, ind_name in industry_nodes:
        page = 1
        symbols = []
        while True:
            url = (f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   f"Market_Center.getHQNodeData?page={page}&num=200&sort=amount&asc=0&node={node}")
            raw = _sina_request(url)
            if not raw:
                break
            try:
                data = json.loads(raw)
                if not data:
                    break
                for item in data:
                    code = str(item.get('code', '')).zfill(6)
                    if code:
                        prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0','3')) else 'bj')
                        sym = f'{prefix}{code}'
                        symbols.append(sym)
                        industry_map[sym] = ind_name
                if len(data) < 200:
                    break
                page += 1
            except Exception:
                break
        
        if symbols:
            industry_stocks[ind_name] = symbols
            log.info(f"  行业 {ind_name}(Sina): {len(symbols)}只")
    
    log.info(f"  行业映射(Sina): {len(industry_map)}只股票, {len(industry_stocks)}个行业")
    return industry_map, industry_stocks


# ════════════════════════════════════════════════════════
#  概念板块成分股（扩展至~50个板块）
# ════════════════════════════════════════════════════════

def get_concept_sector_stocks() -> tuple:
    """
    获取热门概念板块成分股 → (concept_map, concept_stocks)
    
    concept_map: {symbol: concept_name}  (个股→概念映射)
    concept_stocks: {concept_name: [symbol1, symbol2, ...]}  (概念→成分股列表)
    
    优先级：
    1. akshare stock_board_concept_name_em() 获取概念板块列表
    2. 按关键词匹配+成分股数量筛选热门概念
    3. akshare stock_board_concept_cons_em() 获取成分股
    """
    concept_map = {}     # symbol → concept_name
    concept_stocks = {}  # concept_name → [symbols]
    
    if not config.CONCEPT_ENABLED:
        log.info("  概念板块功能已禁用")
        return concept_map, concept_stocks
    
    log.info("  获取概念板块成分股...")
    
    try:
        # 获取东方财富概念板块列表
        board_df = _retry(ak.stock_board_concept_name_em)
        if board_df is None or board_df.empty:
            log.warning("  概念板块列表获取为空")
            return concept_map, concept_stocks
        
        log.info(f"  概念板块列表: {len(board_df)}个")
        
        # 解析列名
        cols = board_df.columns.tolist()
        name_col = next((c for c in cols if '名称' in c or '板块名称' in c), None)
        code_col = next((c for c in cols if '代码' in c or '板块代码' in c), None)
        # 成分股数量列（可能存在）
        count_col = next((c for c in cols if '数量' in c or '成分' in c), None)
        
        if not name_col:
            # 尝试使用第二列（通常第一列是代码，第二列是名称）
            name_col = cols[1] if len(cols) > 1 else cols[0]
        
        # ── 筛选热门概念 ──
        # 策略：先按关键词匹配，不足则按成分股数量补足
        keywords = config.CONCEPT_KEYWORDS
        top_n = config.CONCEPT_TOP_N
        
        # 为每个概念打分（关键词匹配优先，其次按成分股数量）
        scored_concepts = []
        for _, row in board_df.iterrows():
            concept_name = str(row.get(name_col, ''))
            if not concept_name or concept_name == 'nan':
                continue
            
            # 关键词匹配得分
            keyword_score = 0
            for kw in keywords:
                if kw in concept_name:
                    keyword_score += 10
                    break  # 每个概念只加一次关键词分
            
            # 成分股数量得分（如果列存在）
            count_score = 0
            if count_col:
                try:
                    count_score = int(_safe_float(row.get(count_col, 0)))
                except (ValueError, TypeError):
                    count_score = 0
            
            total_score = keyword_score * 1000 + count_score  # 关键词匹配优先
            scored_concepts.append({
                'name': concept_name,
                'score': total_score,
                'keyword_matched': keyword_score > 0,
            })
        
        # 排序：关键词匹配优先，其次按得分
        scored_concepts.sort(key=lambda x: (x['keyword_matched'], x['score']), reverse=True)
        
        # 取TOP N概念
        selected = scored_concepts[:top_n]
        keyword_matched = sum(1 for c in selected if c['keyword_matched'])
        log.info(f"  筛选概念: TOP{len(selected)}个 (关键词命中{keyword_matched}个)")
        
        # ── 获取每个概念的成分股 ──
        for concept in selected:
            concept_name = concept['name']
            try:
                cons_df = _retry(ak.stock_board_concept_cons_em, symbol=concept_name)
                if cons_df is not None and not cons_df.empty:
                    code_col_cons = next((c for c in cons_df.columns if '代码' in c), None)
                    if code_col_cons:
                        symbols = []
                        for code in cons_df[code_col_cons].astype(str):
                            code = code.zfill(6)
                            prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0', '3')) else 'bj')
                            sym = f'{prefix}{code}'
                            symbols.append(sym)
                            # 个股→概念映射（一只股可能属于多个概念，取最后匹配的）
                            if sym not in concept_map:
                                concept_map[sym] = concept_name
                        
                        concept_stocks[concept_name] = symbols
                        log.info(f"  概念 [{concept_name}]: {len(symbols)}只")
                    else:
                        log.debug(f"  概念 {concept_name} 成分股列名异常: {cons_df.columns.tolist()}")
                else:
                    log.debug(f"  概念 {concept_name} 成分股为空")
            except Exception as e:
                log.warning(f"  概念 {concept_name} 成分股获取失败: {e}")
            
            # 避免请求过快
            time.sleep(0.3)
        
        log.info(f"  概念板块映射: {len(concept_map)}只股票, {len(concept_stocks)}个概念")
        
    except Exception as e:
        log.error(f"  概念板块获取失败: {e}")
    
    return concept_map, concept_stocks


def get_concept_sector_fund_flow() -> pd.DataFrame:
    """
    获取概念板块资金流数据
    使用akshare stock_board_concept_name_em()获取概念板块列表和当日涨跌数据
    使用Sina概念板块资金流或概念板块成分股资金流加总
    
    返回: DataFrame (列: 名称, 净流入, 涨跌幅)
    """
    if not config.CONCEPT_ENABLED:
        return pd.DataFrame()
    
    log.info("  [概念资金流] 获取概念板块资金流")
    
    # ── 方法1：Sina概念板块资金流 ──
    try:
        url = (f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"MoneyFlow.ssl_bkzj_bk?page=1&num=100&sort=netamount&asc=0&fenlei=1")
        raw = _sina_request(url)
        if raw:
            data = json.loads(raw)
            if data:
                rows = []
                for item in data:
                    name = str(item.get('name', ''))
                    if not name:
                        continue
                    net_inflow = _safe_float(item.get('netamount', 0))
                    change_pct = _safe_float(item.get('avg_changeratio', 0)) * 100
                    net_inflow_pct = _safe_float(item.get('ratioamount', 0))
                    
                    rows.append({
                        '名称': name,
                        '净流入': net_inflow,
                        '涨跌幅': change_pct,
                        '净流入占比': net_inflow_pct,
                    })
                
                if rows:
                    result = pd.DataFrame(rows)
                    log.info(f"  [概念资金流] Sina获取成功: {len(result)}个概念板块")
                    return result
    except Exception as e:
        log.warning(f"  [概念资金流] Sina获取失败: {e}")
    
    # ── 方法2：akshare概念板块列表（仅当日涨跌，无资金流）──
    try:
        board_df = _retry(ak.stock_board_concept_name_em)
        if board_df is not None and not board_df.empty:
            cols = board_df.columns.tolist()
            name_col = next((c for c in cols if '名称' in c or '板块名称' in c), None)
            pct_col = next((c for c in cols if '涨跌幅' in c), None)
            
            if not name_col:
                name_col = cols[1] if len(cols) > 1 else cols[0]
            
            rows = []
            for _, row in board_df.iterrows():
                name = str(row.get(name_col, ''))
                pct = _safe_float(row.get(pct_col, 0)) if pct_col else 0
                rows.append({
                    '名称': name,
                    '净流入': 0,  # akshare列表无资金流数据
                    '涨跌幅': pct,
                    '净流入占比': 0,
                })
            
            if rows:
                result = pd.DataFrame(rows)
                log.info(f"  [概念资金流] akshare降级获取: {len(result)}个概念板块(无资金流)")
                return result
    except Exception as e:
        log.warning(f"  [概念资金流] akshare降级也失败: {e}")
    
    log.warning("  [概念资金流] 所有数据源均失败")
    return pd.DataFrame()


# ════════════════════════════════════════════════════════
#  资金流弦：板块/个股资金流（复用v1.4降级链路）
# ════════════════════════════════════════════════════════

# ── push2 备用源 ──────────────────────────────────────

def _fallback_push2_clist(fs_param: str, fields: str, page_size: int = 200) -> list:
    cdn_nodes = ['86', '1', '2', '56', 'push2ex']
    base_template = "https://{}.push2.eastmoney.com/api/qt/clist/get"
    params = f"?pn=1&pz={page_size}&po=1&np=1&fltt=2&invt=2&fid=f62&fs={fs_param}&fields={fields}"
    for node in cdn_nodes:
        url = base_template.format(node) + params
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://data.eastmoney.com/',
        })
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('data') and data['data'].get('diff'):
                log.info(f"  push2备用源成功 (CDN: {node})")
                return data['data']['diff']
        except Exception:
            continue
    return []


def _fallback_datacenter_web(report_name: str, sort_col: str = 'NET_INFLOW_AMT',
                              page_size: int = 200) -> list:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = urllib.parse.urlencode({
        'sortColumns': sort_col, 'sortTypes': '-1',
        'pageSize': str(page_size), 'pageNumber': '1',
        'reportName': report_name, 'columns': 'ALL',
        'source': 'WEB', 'client': 'WEB',
    })
    full_url = f"{url}?{params}"
    req = urllib.request.Request(full_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode('utf-8'))
        if data.get('result') and data['result'].get('data'):
            log.info(f"  datacenter-web备用源成功")
            return data['result']['data']
    except Exception:
        pass
    return []


# ── Sina板块资金流（主源） ────────────────────────────

def get_sector_fund_flow(indicator: str = "今日") -> pd.DataFrame:
    """板块资金流排名，Sina为主源"""
    # 先试Sina
    results = []
    for fenlei in ['0', '1']:  # 0=行业, 1=概念
        url = (f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"MoneyFlow.ssl_bkzj_bk?page=1&num=100&sort=netamount&asc=0&fenlei={fenlei}")
        raw = _sina_request(url)
        if raw:
            try:
                data = json.loads(raw)
                if data:
                    results.extend(data)
            except Exception:
                pass
    
    if results:
        rows = []
        for item in results:
            name = str(item.get('name', ''))
            if not name:
                continue
            net_inflow = _safe_float(item.get('netamount', 0))
            change_pct = _safe_float(item.get('avg_changeratio', 0)) * 100
            net_inflow_pct = _safe_float(item.get('ratioamount', 0)) * 100
            turnover = _safe_float(item.get('turnover', 0))
            rows.append({
                '名称': name, '涨跌幅': change_pct,
                '主力净流入-净额': net_inflow, '主力净流入-净占比': net_inflow_pct,
                '换手率': turnover,
            })
        df = pd.DataFrame(rows).sort_values('主力净流入-净额', ascending=False).reset_index(drop=True)
        log.info(f"  Sina板块资金流: {len(df)}个板块")
        return df
    
    # 降级到push2
    log.info("  Sina板块资金流失败，降级push2...")
    fs_param = "m:90+t:2"
    fields = "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124"
    raw = _fallback_push2_clist(fs_param, fields)
    if raw:
        rows = []
        for item in raw:
            try:
                rows.append({
                    '名称': str(item.get('f14', '')),
                    '涨跌幅': _safe_float(item.get('f3', 0)),
                    '主力净流入-净额': _safe_float(item.get('f62', 0)),
                    '主力净流入-净占比': _safe_float(item.get('f184', 0)),
                    '换手率': _safe_float(item.get('f124', 0)),
                })
            except Exception:
                continue
        if rows:
            return pd.DataFrame(rows)
    
    # 降级到datacenter-web
    log.info("  push2失败，降级datacenter-web...")
    raw2 = _fallback_datacenter_web('RPT_INDUSTRY_BOARD_MONEY_FLOW')
    if raw2:
        rows = []
        for item in raw2:
            name = item.get('BOARD_NAME', '') or item.get('SECURITY_NAME_ABBR', '')
            if not name:
                continue
            rows.append({
                '名称': name,
                '涨跌幅': _safe_float(item.get('CHANGE_RATE', 0)),
                '主力净流入-净额': _safe_float(item.get('NET_INFLOW_AMT', 0)),
                '主力净流入-净占比': _safe_float(item.get('NET_INFLOW_RATE', 0)),
                '换手率': _safe_float(item.get('TURNOVER_RATE', 0)),
            })
        if rows:
            return pd.DataFrame(rows)
    
    log.warning("板块资金流所有源均失败")
    return pd.DataFrame()


# ── 个股资金流 ────────────────────────────────────────

def get_individual_fund_flow_rank(indicator: str = "今日") -> pd.DataFrame:
    """个股资金流排名，多源降级"""
    # 主源：akshare
    try:
        df = _retry(ak.stock_individual_fund_flow_rank, indicator=indicator)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        log.warning(f"个股资金流akshare主源失败: {e}")

    # 降级1：push2 CDN
    log.info("  尝试个股资金流备用源1 (push2直连)...")
    fs_param = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    fields = "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124,f152,f173"
    raw = _fallback_push2_clist(fs_param, fields, page_size=200)
    if raw:
        rows = []
        for item in raw:
            code = str(item.get('f12', ''))
            name = str(item.get('f14', ''))
            if not code or not name:
                continue
            rows.append({
                '代码': code, '名称': name,
                '涨跌幅': _safe_float(item.get('f3', 0)),
                '主力净流入-净额': _safe_float(item.get('f62', 0)),
                '主力净流入-净占比': _safe_float(item.get('f184', 0)),
                '换手率': _safe_float(item.get('f124', 0)),
                '流通市值': _safe_float(item.get('f152', 0)),
                '成交额': _safe_float(item.get('f173', 0)),
            })
        if rows:
            return pd.DataFrame(rows)

    # 降级2：Tushare
    log.info("  尝试个股资金流备用源2 (Tushare)...")
    token = os.environ.get("TUSHARE_TOKEN", "") or config.TUSHARE_TOKEN
    if token:
        trade_date = datetime.now().strftime('%Y%m%d')
        url = "https://api.tushare.pro"
        payload = json.dumps({
            "api_name": "moneyflow", "token": token,
            "params": {"trade_date": trade_date}
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('data') and result['data'].get('items'):
                fields_t = result['data']['fields']
                items = result['data']['items']
                rows = []
                for item in items:
                    rd = dict(zip(fields_t, item))
                    ts_code = str(rd.get('ts_code', ''))
                    code = ts_code.split('.')[0] if '.' in ts_code else ts_code
                    net_mf = _safe_float(rd.get('net_mf_amount', 0))
                    rows.append({
                        '代码': code, '名称': '',
                        '涨跌幅': 0, '主力净流入-净额': net_mf * 10000,
                        '主力净流入-净占比': 0,
                    })
                if rows:
                    df = pd.DataFrame(rows).sort_values('主力净流入-净额', ascending=False)
                    log.info(f"  Tushare个股: {len(df)}只")
                    return df
        except Exception as e:
            log.debug(f"  Tushare失败: {e}")

    log.warning("个股资金流所有源均失败")
    return pd.DataFrame()


# ── 指数/市场数据 ─────────────────────────────────────

def get_index_daily(symbol: str = "sh000001", days: int = 30) -> pd.DataFrame:
    """指数日线，统一K线入口（Sina → efinance → akshare）"""
    df = get_kline(symbol, scale=240, datalen=days+50)
    if df.empty:
        # 最后兜底：akshare指数专用接口
        try:
            df = _retry(ak.stock_zh_index_daily, symbol=symbol)
            df = df.rename(columns={
                'date': 'day', 'open': '开盘', 'high': '最高',
                'low': '最低', 'close': '收盘', 'volume': '成交量'
            })
            df['day'] = pd.to_datetime(df['day'])
        except Exception:
            return pd.DataFrame()
    if df.empty:
        return df
    df = df.sort_values('day').tail(days).reset_index(drop=True)
    return df


def get_market_turnover() -> dict:
    sh = get_index_daily('sh000001', days=25)
    sz = get_index_daily('sz399001', days=25)
    if sh.empty or sz.empty:
        return {'today_amount': 0, 'avg20_amount': 0, 'amount_ratio': 0, 'status': '数据缺失'}
    
    # 用成交量近似（Sina返回的volume单位可能不一致）
    sh_vol = sh['volume'].astype(float)
    sz_vol = sz['volume'].astype(float)
    merged = pd.merge(
        sh[['day', 'volume']].rename(columns={'volume': 'sh_vol'}),
        sz[['day', 'volume']].rename(columns={'volume': 'sz_vol'}),
        on='day'
    )
    merged['总成交额'] = merged['sh_vol'].astype(float) + merged['sz_vol'].astype(float)
    merged = merged.sort_values('day').reset_index(drop=True)
    today_amount = float(merged.iloc[-1]['总成交额'])
    avg20_amount = float(merged.tail(20)['总成交额'].mean())
    return {
        'today_amount': today_amount,
        'avg20_amount': avg20_amount,
        'amount_ratio': today_amount / avg20_amount if avg20_amount > 0 else 0,
    }


def get_three_indices(days: int = 5) -> pd.DataFrame:
    sh = get_index_daily('sh000001', days=days)
    sz = get_index_daily('sz399001', days=days)
    try:
        qa = get_index_daily('sh000985', days=days)
    except Exception:
        qa = sh.copy()
    if sh.empty:
        return pd.DataFrame()
    result = pd.DataFrame()
    result['日期'] = sh['day'].values
    for col_src, idx_name in [('close', '收盘'), ('pct', '涨跌')]:
        if col_src == 'pct':
            result['上证涨跌'] = sh['close'].astype(float).pct_change().fillna(0).values
            result['深证涨跌'] = sz['close'].astype(float).pct_change().fillna(0).values
            result['全A替代涨跌'] = qa['close'].astype(float).pct_change().fillna(0).values
        else:
            result['上证收盘'] = sh['close'].astype(float).values
            result['深证收盘'] = sz['close'].astype(float).values
            result['全A替代收盘'] = qa['close'].astype(float).values
    return result


# ── 市场温度计 ──────────────────────────────────────────

def get_market_temperature() -> dict:
    """
    市场温度计：0-100分量化市场冷暖
    五个子指标各20分：
    1. 价格动量：当前价vs20日均线偏离度
    2. 成交量：当日成交额vs20日均值
    3. MACD状态：DIF/DEA位置
    4. 短期趋势：近5日收益率
    5. 中期趋势：近20日收益率
    """
    index_code = config.THERMOMETER_INDEX  # 默认sh000300
    log.info(f"  [温度计] 计算市场温度 ({index_code})")
    
    try:
        kline = get_sina_kline(index_code, scale=240, datalen=60)
        if kline.empty or len(kline) < 25:
            log.warning("  [温度计] K线数据不足")
            return {'score': 50, 'zone': '数据不足', 'emoji': '❓', 'sub_scores': {}}
        
        # 确保数据类型
        kline['close'] = kline['close'].astype(float)
        kline['volume'] = kline['volume'].astype(float)
        kline = kline.sort_values('day').reset_index(drop=True)
        
        close = kline['close']
        volume = kline['volume']
        
        # ── 1. 价格动量（vs MA20偏离度）──
        ma20 = close.rolling(20).mean()
        deviation = (close.iloc[-1] - ma20.iloc[-1]) / ma20.iloc[-1]
        # 偏离>5% → 20分，<-5% → 0分，线性插值
        momentum_score = max(0, min(20, (deviation + 0.05) / 0.10 * 20))
        
        # ── 2. 成交量（vs 20日均量）──
        avg_vol_20 = volume.tail(20).mean()
        vol_ratio = volume.iloc[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0
        # 放量>1.5倍 → 20分，<0.5倍 → 0分
        volume_score = max(0, min(20, (vol_ratio - 0.5) / 1.0 * 20))
        
        # ── 3. MACD状态 ──
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = 2 * (dif - dea)
        
        dif_val = dif.iloc[-1]
        dea_val = dea.iloc[-1]
        
        # DIF>0且DEA>0 → 高分；DIF<0且DEA<0 → 低分
        if dif_val > 0 and dea_val > 0:
            macd_score = 16  # 多头排列
            if macd_hist.iloc[-1] > macd_hist.iloc[-2]:
                macd_score = 20  # 柱还在放大
        elif dif_val < 0 and dea_val < 0:
            macd_score = 4   # 空头排列
            if macd_hist.iloc[-1] < macd_hist.iloc[-2]:
                macd_score = 0  # 柱还在放大向下
        else:
            macd_score = 10  # 混合状态
        
        # ── 4. 短期趋势（5日收益率）──
        if len(close) >= 6:
            ret_5d = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6]
        else:
            ret_5d = 0
        # >3% → 20分，<-3% → 0分
        trend_5d_score = max(0, min(20, (ret_5d + 0.03) / 0.06 * 20))
        
        # ── 5. 中期趋势（20日收益率）──
        if len(close) >= 21:
            ret_20d = (close.iloc[-1] - close.iloc[-21]) / close.iloc[-21]
        else:
            ret_20d = 0
        # >8% → 20分，<-8% → 0分
        trend_20d_score = max(0, min(20, (ret_20d + 0.08) / 0.16 * 20))
        
        # ── 汇总 ──
        total = momentum_score + volume_score + macd_score + trend_5d_score + trend_20d_score
        total = round(total)
        total = max(0, min(100, total))
        
        sub_scores = {
            '动量': round(momentum_score),
            '量能': round(volume_score),
            'MACD': macd_score,
            '短期趋势': round(trend_5d_score),
            '中期趋势': round(trend_20d_score),
        }
        
        # 温度分级
        if total >= 80:
            zone, emoji = '过热区', '🔥'
        elif total >= 60:
            zone, emoji = '温暖区', '☀️'
        elif total >= 40:
            zone, emoji = '中性区', '🌤️'
        elif total >= 20:
            zone, emoji = '偏冷区', '🌧️'
        else:
            zone, emoji = '冰点区', '🧊'
        
        result = {
            'score': total,
            'zone': zone,
            'emoji': emoji,
            'sub_scores': sub_scores,
            'deviation': round(deviation * 100, 2),
            'vol_ratio': round(vol_ratio, 2),
            'ret_5d': round(ret_5d * 100, 2),
            'ret_20d': round(ret_20d * 100, 2),
        }
        log.info(f"  [温度计] {total}/100 {emoji}{zone} {sub_scores}")
        return result
        
    except Exception as e:
        log.error(f"  [温度计] 计算失败: {e}")
        return {'score': 50, 'zone': '数据异常', 'emoji': '❓', 'sub_scores': {}}


# ── 板块资金多周期全景 ──────────────────────────────────

def get_sector_flow_multi_period() -> pd.DataFrame:
    """
    获取板块资金流多周期数据（今日/3日/5日/10日）
    使用akshare的stock_sector_fund_flow_rank，支持多个indicator
    返回包含多周期的DataFrame
    """
    log.info("  [热力图] 获取板块资金多周期数据")
    
    periods = {}
    for indicator in ['今日', '3日', '5日', '10日']:
        try:
            df_ak = ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type="行业资金流")
            if df_ak is not None and not df_ak.empty:
                # 标准化列名
                cols = df_ak.columns.tolist()
                name_col = next((c for c in cols if '名称' in c), cols[1] if len(cols) > 1 else cols[0])
                flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
                pct_col = next((c for c in cols if '涨跌幅' in c), None)
                
                if flow_col is None:
                    # 尝试找包含"净流入"的列
                    flow_candidates = [c for c in cols if '净流入' in c]
                    if flow_candidates:
                        flow_col = flow_candidates[0]
                
                if flow_col:
                    period_data = {}
                    for _, row in df_ak.iterrows():
                        name = str(row.get(name_col, ''))
                        net_flow = _safe_float(str(row.get(flow_col, '0')).replace(',', ''))
                        pct = _safe_float(str(row.get(pct_col, '0')).replace('%', '').replace(',', '')) if pct_col else 0
                        period_data[name] = {'net_flow': net_flow, 'pct': pct}
                    periods[indicator] = period_data
                    log.info(f"    {indicator}: {len(period_data)}个板块")
        except Exception as e:
            log.warning(f"    {indicator}获取失败: {e}")
    
    if not periods:
        log.warning("  [热力图] 所有周期数据获取失败")
        return pd.DataFrame()
    
    # 合并所有周期数据
    all_sectors = set()
    for p_data in periods.values():
        all_sectors.update(p_data.keys())
    
    rows = []
    for sector in all_sectors:
        row = {'名称': sector}
        for indicator in ['今日', '3日', '5日', '10日']:
            p_data = periods.get(indicator, {})
            if sector in p_data:
                row[f'{indicator}_净流入'] = p_data[sector]['net_flow']
                row[f'{indicator}_涨跌'] = p_data[sector]['pct']
            else:
                row[f'{indicator}_净流入'] = 0
                row[f'{indicator}_涨跌'] = 0
        
        # 计算累计控盘度（10日累计净流入，归一化）
        total_10d = row.get('10日_净流入', 0) + row.get('5日_净流入', 0) + row.get('3日_净流入', 0) + row.get('今日_净流入', 0)
        row['累计净流入'] = total_10d
        
        # 判断方向
        flows = [row.get(f'{p}_净流入', 0) for p in ['今日', '3日', '5日', '10日']]
        if all(f > 0 for f in flows):
            row['方向'] = '📈'
        elif all(f < 0 for f in flows):
            row['方向'] = '📉'
        elif flows[0] > 0 and flows[-1] < 0:
            row['方向'] = '⚡'  # 短期反转
        else:
            row['方向'] = '➖'
        
        rows.append(row)
    
    result = pd.DataFrame(rows)
    result = result.sort_values('累计净流入', ascending=False).reset_index(drop=True)
    log.info(f"  [热力图] 合并完成: {len(result)}个板块")
    return result


# ── 个股多周期资金流 ──────────────────────────────────

def get_stock_fund_flow_periods(stock_code: str, periods: list = None) -> dict:
    """
    获取单只股票的多周期主力净流入 + 资金沉淀率
    返回: {'3d': float, '5d': float, '10d': float, '20d': float,
           'sedimentation_rate': float, '3d_flow': float, '3d_turnover': float}
    """
    if periods is None:
        periods = config.MULTI_PERIOD_DAYS
    
    result = {f'{d}d': 0 for d in periods}
    result['sedimentation_rate'] = 0
    result['3d_flow'] = 0
    result['3d_turnover'] = 0
    
    try:
        # 判断市场
        if stock_code.startswith('6'):
            market = 'sh'
        else:
            market = 'sz'
        
        # 使用akshare获取个股历史资金流
        df_hist = ak.stock_individual_fund_flow(stock=stock_code, market=market)
        if df_hist is None or df_hist.empty:
            return result
        
        # 找到主力净流入列
        cols = df_hist.columns.tolist()
        flow_col = next((c for c in cols if '主力净流入' in c and '净额' in c), None)
        if flow_col is None:
            flow_col = next((c for c in cols if '主力净流入' in c), None)
        if flow_col is None:
            return result
        
        df_hist = df_hist.tail(25)  # 取最近25天足够
        flows = df_hist[flow_col].astype(float).values
        
        # 计算各周期累计
        for d in periods:
            if len(flows) >= d:
                result[f'{d}d'] = float(np.sum(flows[-d:]))
        
        # ── 资金沉淀率 ──────────────────────────────
        # 沉淀率 = 3日主力净流入 / 3日总成交额
        # 从K线数据获取成交额
        if config.SEDIMENTATION_ENABLED and len(flows) >= 3:
            prefix = 'sh' if stock_code.startswith('6') else 'sz'
            symbol = f"{prefix}{stock_code}"
            kline = get_sina_kline(symbol, scale=240, datalen=10)
            if not kline.empty and len(kline) >= 3:
                kline['amount'] = kline['close'].astype(float) * kline['volume'].astype(float)
                turnover_3d = float(kline['amount'].tail(3).sum())
                flow_3d = float(np.sum(flows[-3:]))
                if turnover_3d > 0:
                    result['sedimentation_rate'] = flow_3d / turnover_3d
                    result['3d_flow'] = flow_3d
                    result['3d_turnover'] = turnover_3d
        
        return result
        
    except Exception as e:
        log.warning(f"  [多周期] {stock_code} 资金流获取失败: {e}")
        return result


# ════════════════════════════════════════════════════════
#  主线军捕获器：识别近期启动板块 + 板块内龙头
# ════════════════════════════════════════════════════════

def get_main_line_sectors(lookback_days: int = 3) -> list:
    """
    主线军捕获器：
    1. 获取板块多周期资金流数据
    2. 筛选近N日净流入>0的"启动板块"
    3. 返回按N日净流入排序的板块列表（含龙头个股）
    
    返回: [
        {
            'sector': str,          # 板块名
            'net_flow_3d': float,   # 3日净流入（万元）
            'pct_3d': float,        # 3日涨跌幅%
            'direction': str,       # 方向标记
            'leaders': [            # 板块内龙头（沉淀率排序）
                {'symbol': str, 'code': str, 'name': str,
                 'sedimentation_rate': float, 'pct_change': float, 'close': float},
                ...
            ]
        }, ...
    ]
    """
    log.info(f"  [主线军] 扫描近{lookback_days}日启动板块")
    
    try:
        # 获取板块3日资金流（对应N日启动判断）
        df_3d = None
        fallback_to_today = False
        try:
            df_3d = ak.stock_sector_fund_flow_rank(indicator='3日', sector_type="行业资金流")
        except Exception as e:
            log.warning(f"  [主线军] 3日板块数据获取失败，降级使用今日数据: {e}")
            fallback_to_today = True
        
        if df_3d is None or df_3d.empty:
            if not fallback_to_today:
                log.warning("  [主线军] 3日板块数据为空，降级使用今日数据")
                fallback_to_today = True
            try:
                df_3d = ak.stock_sector_fund_flow_rank(indicator='今日', sector_type="行业资金流")
            except Exception as e:
                log.warning(f"  [主线军] 今日板块数据也获取失败: {e}")
        
        if df_3d is None or df_3d.empty:
            # 最终降级：使用 Sina 板块资金流（仅今日数据）
            log.info("  [主线军] akshare全部失败，降级到Sina板块资金流")
            sina_df = get_sector_fund_flow(indicator="今日")
            if sina_df is None or sina_df.empty:
                log.warning("  [主线军] Sina板块数据也获取失败，主线军本轮跳过")
                return []
            df_3d = sina_df  # 复用同一解析逻辑，Sina netamount单位已是元
            fallback_to_today = True
            log.info(f"  [主线军] Sina降级成功，获取{len(df_3d)}条板块数据")
        
        # 获取板块今日资金流（用于今日数据补充，仅在未降级时额外获取）
        df_today = None
        if not fallback_to_today:
            try:
                df_today = ak.stock_sector_fund_flow_rank(indicator='今日', sector_type="行业资金流")
            except Exception:
                df_today = None
        
        # 解析3日数据
        cols = df_3d.columns.tolist()
        name_col = next((c for c in cols if '名称' in c), cols[1] if len(cols) > 1 else cols[0])
        flow_col = next((c for c in cols if '净流入' in c and '净额' in c), None)
        if flow_col is None:
            flow_candidates = [c for c in cols if '净流入' in c]
            flow_col = flow_candidates[0] if flow_candidates else None
        pct_col = next((c for c in cols if '涨跌幅' in c), None)
        
        if flow_col is None:
            log.warning("  [主线军] 未找到净流入列")
            return []
        
        # 构建板块数据
        sectors = []
        for _, row in df_3d.iterrows():
            name = str(row.get(name_col, ''))
            net_flow = _safe_float(str(row.get(flow_col, '0')).replace(',', ''))
            pct = _safe_float(str(row.get(pct_col, '0')).replace('%', '').replace(',', '')) if pct_col else 0
            if net_flow > config.DRAGON_MIN_NET_FLOW:
                sectors.append({
                    'sector': name,
                    'net_flow_3d': net_flow,
                    'pct_3d': pct,
                })
        
        # 按3日净流入降序排序，取TOP N
        sectors = sorted(sectors, key=lambda x: x['net_flow_3d'], reverse=True)[:config.DRAGON_TOP_SECTORS]
        log.info(f"  [主线军] 启动板块: {len(sectors)}个, TOP: {[s['sector'] for s in sectors[:3]]}")
        
        # ── 为每个启动板块获取龙头个股 ──
        # SW_TO_SINA 反向映射：板块名 → Sina节点
        # 由于Sina板块节点与akshare行业名不完全一致，用akshare的成分股API
        for sector in sectors:
            sector_name = sector['sector']
            leaders = []
            try:
                # 用akshare获取板块成分股
                cons_df = ak.stock_board_industry_cons_em(symbol=sector_name)
                if cons_df is not None and not cons_df.empty:
                    # 获取成分股的代码列表
                    code_col = next((c for c in cons_df.columns if '代码' in c), cons_df.columns[0])
                    name_col_stock = next((c for c in cons_df.columns if '名称' in c), cons_df.columns[1])
                    pct_col_stock = next((c for c in cons_df.columns if '涨跌幅' in c or '最新涨幅' in c), None)
                    
                    stock_codes = cons_df[code_col].astype(str).tolist()[:50]  # 取前50只扫描
                    
                    # 批量获取沉淀率（只取前10只以减少API调用）
                    for stock_code in stock_codes[:15]:
                        stock_code = stock_code.zfill(6)
                        prefix = 'sh' if stock_code.startswith('6') else ('sz' if stock_code.startswith(('0', '3')) else 'bj')
                        symbol = f"{prefix}{stock_code}"
                        
                        try:
                            periods = get_stock_fund_flow_periods(stock_code, periods=[3])
                            if periods.get('sedimentation_rate', 0) > 0:
                                # 获取涨跌幅（从cons_df中取，或从K线取）
                                pct = 0
                                close = 0
                                stock_row = cons_df[cons_df[code_col].astype(str) == stock_code]
                                if not stock_row.empty:
                                    if pct_col_stock:
                                        pct = _safe_float(stock_row.iloc[0].get(pct_col_stock, 0))
                                    close_col = next((c for c in cons_df.columns if '最新价' in c or '收盘' in c), None)
                                    if close_col:
                                        close = _safe_float(stock_row.iloc[0].get(close_col, 0))
                                
                                name_in_board = ''
                                if not stock_row.empty:
                                    name_in_board = str(stock_row.iloc[0].get(name_col_stock, ''))
                                
                                leaders.append({
                                    'symbol': symbol,
                                    'code': stock_code,
                                    'name': name_in_board,
                                    'sedimentation_rate': periods['sedimentation_rate'],
                                    'pct_change': pct,
                                    'close': close,
                                    'net_flow_3d': periods.get('3d', 0),
                                })
                        except Exception:
                            continue
                    
                    # 按沉淀率降序，取龙头
                    leaders = sorted(leaders, key=lambda x: x['sedimentation_rate'], reverse=True)[:config.DRAGON_LEADERS_PER_SECTOR]
                    
            except Exception as e:
                log.warning(f"  [主线军] {sector_name} 成分股获取失败: {e}")
            
            sector['leaders'] = leaders
            if leaders:
                log.info(f"    {sector_name}: 龙头 {leaders[0]['name']} 沉淀率{leaders[0]['sedimentation_rate']:.1%}")
        
        return sectors
        
    except Exception as e:
        log.error(f"  [主线军] 扫描失败: {e}")
        return []

# ════════════════════════════════════════════════════════
#  筹码分布分析（CYQ）
# ════════════════════════════════════════════════════════

def _compute_chip_distribution(daily_df: pd.DataFrame, lookback: int = 60) -> dict:
    """
    本地三角筹码算法（通达信原版复刻）
    用已有K线数据计算筹码分布，不依赖外部API
    
    参数:
        daily_df: 日线DataFrame（含open/high/low/close/volume/turnover）
        lookback: 回溯交易日数（默认60日中线）
    
    返回: {
        'concentration_90': 90%集中度(%),
        'concentration_70': 70%集中度(%),
        'profit_ratio': 获利盘比例(0~1),
        'avg_cost': 市场平均成本,
        'main_peak_price': 主力成本峰（筹码最多价位）,
        'source': 'local'
    }
    """
    try:
        import scipy.stats
        from scipy.stats import triang as scipy_triang
        has_scipy = True
    except ImportError:
        has_scipy = False
    
    if daily_df is None or len(daily_df) < lookback:
        return {}
    
    df = daily_df.tail(lookback).copy()
    
    # 检查必要字段
    if 'turnover' not in df.columns or 'amount' not in df.columns:
        return {}
    
    price_step = 0.01
    price_min = df['low'].min() * 0.98
    price_max = df['high'].max() * 1.02
    
    if price_max <= price_min:
        return {}
    
    price_arr = np.arange(price_min, price_max + price_step, price_step)
    chip_total = np.zeros_like(price_arr, dtype=np.float64)
    
    for _, row in df.iterrows():
        h = float(row['high'])
        l = float(row['low'])
        turnover = float(row.get('turnover', 0)) / 100.0
        amount = float(row.get('amount', 0))
        
        if amount <= 0 or h <= l:
            continue
        
        # 存量筹码随换手率折旧衰减
        chip_total = chip_total * (1 - min(turnover, 0.99))
        
        # 当日成交三角分布赋值
        mid = float(row['close'])
        range_val = h - l
        if range_val < price_step:
            # 一字板，筹码集中在单一价位
            idx = np.searchsorted(price_arr, mid)
            if idx < len(chip_total):
                chip_total[idx] += amount
        else:
            if has_scipy:
                c_param = (mid - l) / range_val
                c_param = max(0.001, min(0.999, c_param))
                tri_dist = scipy_triang(c=c_param, loc=l, scale=range_val)
                add_chip = tri_dist.pdf(price_arr) * amount
                add_chip[np.isnan(add_chip)] = 0
                chip_total += add_chip
            else:
                # 无scipy时使用均匀分布近似
                mask = (price_arr >= l) & (price_arr <= h)
                count = mask.sum()
                if count > 0:
                    chip_total[mask] += amount / count
    
    total_chips = chip_total.sum()
    if total_chips <= 0:
        return {}
    
    current_price = float(df['close'].iloc[-1])
    
    # 累计分布
    chip_cum = np.cumsum(chip_total) / total_chips
    
    # 90%集中度
    p5_idx = np.argmin(np.abs(chip_cum - 0.05))
    p95_idx = np.argmin(np.abs(chip_cum - 0.95))
    p5_price = float(price_arr[p5_idx])
    p95_price = float(price_arr[p95_idx])
    mid_90 = (p95_price + p5_price) / 2
    concentration_90 = (p95_price - p5_price) / mid_90 * 100 if mid_90 > 0 else 0
    
    # 70%集中度
    p15_idx = np.argmin(np.abs(chip_cum - 0.15))
    p85_idx = np.argmin(np.abs(chip_cum - 0.85))
    p15_price = float(price_arr[p15_idx])
    p85_price = float(price_arr[p85_idx])
    mid_70 = (p85_price + p15_price) / 2
    concentration_70 = (p85_price - p15_price) / mid_70 * 100 if mid_70 > 0 else 0
    
    # 获利盘比例
    profit_mask = price_arr < current_price
    profit_ratio = chip_total[profit_mask].sum() / total_chips if total_chips > 0 else 0
    
    # 平均成本
    avg_cost = float(np.average(price_arr, weights=chip_total)) if total_chips > 0 else current_price
    
    # 主力成本峰（筹码最密集价位）
    peak_idx = int(np.argmax(chip_total))
    main_peak_price = float(price_arr[peak_idx])
    
    return {
        'concentration_90': round(concentration_90, 2),
        'concentration_70': round(concentration_70, 2),
        'profit_ratio': round(profit_ratio, 4),
        'avg_cost': round(avg_cost, 2),
        'main_peak_price': round(main_peak_price, 2),
        'source': 'local'
    }


def get_chip_distribution(stock_code: str, symbol: str = None, 
                          daily_df: pd.DataFrame = None) -> dict:
    """
    获取个股筹码分布数据
    
    优先级：
    1. akshare stock_cyq_em（东方财富官方筹码，最准确）
    2. 本地三角分布算法（用已有K线数据计算，稳定可靠）
    
    参数:
        stock_code: 6位股票代码（如 '600519'）
        symbol: 完整代码（如 'sh600519'），用于本地回退时获取K线
        daily_df: 已有的日线数据，避免重复请求
    
    返回: {
        'concentration_90': 90%集中度(%),
        'concentration_70': 70%集中度(%),
        'profit_ratio': 获利盘比例(0~1),
        'avg_cost': 平均成本,
        'main_peak_price': 主力成本峰,
        'chip_concentrated': bool (90%集中度 < 阈值),
        'source': 'akshare' / 'local'
    }
    """
    result = {}
    
    # 方案1：尝试akshare stock_cyq_em（东方财富筹码数据）
    try:
        import akshare as ak
        cyq_df = ak.stock_cyq_em(symbol=stock_code, adjust="qfq")
        if cyq_df is not None and not cyq_df.empty:
            latest = cyq_df.iloc[0]  # 最新一天
            # akshare返回字段: 日期/获利比例/平均成本/90成本-低/90成本-高/90集中度/70成本-低/70成本-高/70集中度
            result = {
                'concentration_90': float(latest.get('90集中度', 0)) * 100 if float(latest.get('90集中度', 0)) < 1 else float(latest.get('90集中度', 0)),
                'concentration_70': float(latest.get('70集中度', 0)) * 100 if float(latest.get('70集中度', 0)) < 1 else float(latest.get('70集中度', 0)),
                'profit_ratio': float(latest.get('获利比例', 0)),
                'avg_cost': float(latest.get('平均成本', 0)),
                'main_peak_price': float(latest.get('平均成本', 0)),  # 东财CYQ无主峰价，用平均成本近似
                'source': 'akshare'
            }
            # 东财集中度可能是0-1小数，也可能是百分比，统一为百分比
            if result['concentration_90'] < 1:
                result['concentration_90'] = result['concentration_90'] * 100
            if result['concentration_70'] < 1:
                result['concentration_70'] = result['concentration_70'] * 100
    except Exception as e:
        log.debug(f"  [筹码] {stock_code} akshare获取失败: {e}")
    
    # 方案2：回退到本地三角分布算法
    if not result:
        if daily_df is not None and not daily_df.empty:
            result = _compute_chip_distribution(daily_df, config.CHIP_LOOKBACK)
        else:
            # 尝试获取K线数据
            sym = symbol or f"{'sh' if stock_code.startswith('6') else 'sz'}{stock_code}"
            kline = get_kline(sym, scale=240, datalen=config.CHIP_LOOKBACK + 20)
            if not kline.empty:
                # 需要turnover和amount字段
                result = _compute_chip_distribution(kline, config.CHIP_LOOKBACK)
    
    if result:
        result['chip_concentrated'] = result.get('concentration_90', 999) < config.CHIP_CONCENTRATION_THRESHOLD
    
    return result


def batch_get_chip_distribution(candidates: list, daily_cache: dict = None) -> list:
    """
    批量获取候选股筹码分布
    
    参数:
        candidates: 候选股列表（每个元素含 code/symbol/close/name）
        daily_cache: 已有的日线数据缓存 {symbol: DataFrame}
    
    返回: 在candidates基础上增加chip字段
    """
    import time
    
    for cand in candidates:
        code = cand.get('code', '')
        symbol = cand.get('symbol', '')
        
        try:
            # 优先使用缓存的日线数据
            cached_df = daily_cache.get(symbol) if daily_cache else None
            chip = get_chip_distribution(code, symbol, cached_df)
            cand['chip'] = chip
            
            if chip:
                log.info(f"  [筹码] {cand.get('name', code)}: "
                        f"集中度90%={chip.get('concentration_90', 'N/A')}%, "
                        f"获利盘={chip.get('profit_ratio', 0):.1%}, "
                        f"{'🔒集中' if chip.get('chip_concentrated') else '🔓分散'}")
            
            # akshare请求间隔，避免被限流
            if chip.get('source') == 'akshare':
                time.sleep(0.3)
                
        except Exception as e:
            log.debug(f"  [筹码] {code} 获取失败: {e}")
            cand['chip'] = {}
    
    return candidates
