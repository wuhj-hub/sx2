"""
双弦投资系统 v2.2 — 配置文件
==================================
逻辑链弦(月线牛市+日线突破V3.0) + 资金流弦(七步复盘+三重确认)
+ 资金沉淀率 + 三层共振评分 + 主线军捕获器
AND门控：两弦信号对齐才推送操作信号
"""

import os

# ── 数据源 ──────────────────────────────────────────────
DATA_SOURCE = "sina"  # 主数据源用Sina（GitHub Actions稳定）
# 备用: akshare, push2 CDN, datacenter-web, Tushare

# Tushare token（个股资金流备用源）
TUSHARE_TOKEN = ""

# ── 股票池 ──────────────────────────────────────────────
# V3.0最优方案：全A(沪深300+中证500+中证1000)
STOCK_POOL = "all"  # all / hs300 / zz500 / zz1000

# ── 逻辑链弦：月线牛市 + 日线突破 ────────────────────────
# 月线牛市判定：3项全满
#   MACD > 0 + 站上MA20 + MA20斜率 > 0
MONTHLY_MACD_THRESHOLD = 0
MONTHLY_MA20_ABOVE = True
MONTHLY_MA20_SLOPE_POSITIVE = True

# 日线突破信号
SIGNAL_TYPES = ["limit_up", "new_high_vol", "new_high"]
# limit_up: 涨停(涨幅≥9.5%+收盘≈最高)
# new_high_vol: 突破120日新高+放量确认
# new_high: 突破120日新高(无量能要求)

# 领涨行业优先排序(非硬过滤)
INDUSTRY_PRIORITY = True

# ── 逻辑链弦：止损与退出 ────────────────────────────────
# V3.0最优：混合止损
EXIT_STRATEGY = "hybrid"  # hybrid / ma20 / trailing
MA20_STOP = True           # 跌破MA20止损
TRAILING_STOP_PCT = 0.08   # 从最高点回撤8%移动止盈
MONTHLY_BEAR_EXIT = True   # 月线转熊退出
MAX_HOLD_DAYS = 60         # 最长持有天数

# ── 资金流弦：七步复盘 ──────────────────────────────────
BREATH_TURNOVER_RATIO = 0.80
BREATH_OVERHEAT_PERCENTILE = 90
INDEX_CODES = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "全A等权替代": "sh000985",
}
ETF_CHECK_WINDOW = 20
ETF_GIANT_SUBSCRIBE_MULT = 3.0
SECTOR_CONCENTRATION_STD = 1.0
SECTOR_TOP_REMOVE_RATIO = 0.20
STOCK_TOP_N = 100
MARGIN_ANOMALY_STD = 2.0

# ── AND门控 ─────────────────────────────────────────────
# 逻辑链输出候选股 → 资金流二次确认 → 两弦共振才推送
# 门控条件(全部满足才推送操作信号):
GATE_MARKET_NORMAL = True       # 市场非冷区(呼吸检查正常/偏热)
GATE_SECTOR_MATCH = True        # 候选股所属板块当日资金净流入>0
GATE_INDIVIDUAL_FLOW = True     # 候选股当日主力净流入>0

# ── 推送配置 ────────────────────────────────────────────
# 推送通道: both=双通道同时推送 / pushplus=仅PushPlus / serverchan=仅Server酱
PUSH_TYPE = os.environ.get("PUSH_TYPE", "both")
PUSH_ENABLED = os.environ.get("PUSH_ENABLED", "true").lower() == "true"
# PushPlus Token
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
# Server酱 SendKey
SEND_KEY = os.environ.get("SEND_KEY", "")

# ── 输出 ────────────────────────────────────────────────
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./reports")
REPORT_PREFIX = "shuangxian_v2"

# ── 缓存目录(预计算数据) ────────────────────────────────
CACHE_DIR = os.environ.get("CACHE_DIR", "./cache")

# ── 月线数据回望 ────────────────────────────────────────
MONTHLY_BARS_NEEDED = 24  # 需要多少根月线来判定牛市(约2年)
DAILY_BARS_NEEDED = 150   # 日线回望(约7个月)

# ── 推送低价标记 ──────────────────────────────────────────
# 全量展示所有候选股，股价≤MAX_PRICE的加💰标记（低价股额外突出显示）
MAX_PRICE = float(os.environ.get("MAX_PRICE", "10"))

# ── 底背离买点检测 ──────────────────────────────────────
# 在月线牛市股票中检测日线MACD底背离，作为补充买入信号
DIVERGENCE_ENABLED = True          # 是否启用底背离检测
DIVERGENCE_LOOKBACK = 90           # 回望窗口（交易日），在此范围内寻找底背离
DIVERGENCE_LOCAL_WINDOW = 5        # 局部极小值窗口（±5根K线）
DIVERGENCE_MIN_GAP = 8             # 两个低点之间最少间隔（交易日）
DIVERGENCE_RECOVER_PCT = 0.02     # 确认回升幅度（从第二个低点回升2%以上）
DIVERGENCE_MACD_TYPE = "histogram" # 背离判断指标: histogram(MACD柱) / dif(DIF线)

# ── 市场温度计 ──────────────────────────────────────────
# 0-100分量化市场冷暖，作为推送首行信息
THERMOMETER_ENABLED = True
THERMOMETER_INDEX = "sh000300"  # 温度计使用的指数（沪深300）

# ── 板块资金全景扫描 ──────────────────────────────────────
# 多日累计控盘度排序，展示板块资金流全景
HEATMAP_ENABLED = True
HEATMAP_TOP_N = 10  # 显示TOP N流入板块

# ── 多周期资金验证 ──────────────────────────────────────
# 为每只候选股显示3/5/10/20日四个周期主力净流入
MULTI_PERIOD_ENABLED = True
MULTI_PERIOD_DAYS = [3, 5, 10, 20]  # 验证周期

# ── 资金沉淀率 ──────────────────────────────────────────
# 沉淀率 = 3日主力净流入 / 3日总成交额，越高表示主力锁仓意愿越强
SEDIMENTATION_ENABLED = True

# ── 三层共振分 ──────────────────────────────────────────
# 大盘+板块+个股三层趋势同向打分，+1/0/-1 求和得 -3~+3
RESONANCE_ENABLED = True

# ── 主线军捕获器 ─────────────────────────────────────────
# 扫描近N日启动的主线板块，输出板块内龙头（资金沉淀率最高）
DRAGON_ENABLED = True
DRAGON_LOOKBACK_DAYS = 3       # 板块近N日启动
DRAGON_TOP_SECTORS = 5         # 显示TOP N主线板块
DRAGON_LEADERS_PER_SECTOR = 5  # 每个板块内TOP N龙头
DRAGON_MIN_NET_FLOW = 0        # 板块最低N日净流入（万元），过滤弱板块

# ── 资金沉淀率综合榜单 ──────────────────────────────────
# 合并逻辑链候选股+主线军成分股，按沉淀率降序排TOP N
SED_RANK_ENABLED = True
SED_RANK_TOP_N = 30  # 榜单展示数量
# ── 筹码集中度分析 ──────────────────────────────────────
# 对候选股获取筹码分布数据（90%/70%集中度、获利盘比例、主力成本）
# 数据源：优先akshare stock_cyq_em（东方财富），失败回退本地三角分布算法
CHIP_ENABLED = True
CHIP_LOOKBACK = 60           # 筹码回溯周期（交易日）
CHIP_CONCENTRATION_THRESHOLD = 15  # 90%集中度阈值(%)，低于此值视为筹码集中

# ── 概念板块扩展 ──────────────────────────────────────
# 在31个申万一级行业基础上，扩展热门概念板块至约50个板块
CONCEPT_ENABLED = True           # 概念板块功能开关
CONCEPT_TOP_N = 19               # 概念板块TOP N数量（31行业+19概念=50）
CONCEPT_KEYWORDS = [             # 关注概念关键词（国产替代+科技热点）
    '芯片', '半导体', '光刻机', '机器人', 'AI', '人工智能',
    '算力', '新能源', '锂电池', '光伏', '军工', '国防',
    '航天', '生物医药', '创新药', '信创', '软件', '鸿蒙',
    '华为', '卫星导航',
]

# ── 候选股3维综合评分 ──────────────────────────────────
# AND门控通过后，按资金+技术+趋势三维评分排序
SCORING_ENABLED = True           # 评分功能开关
SCORING_WEIGHT_CAPITAL = 0.35    # 资金维度权重
SCORING_WEIGHT_TECH = 0.35       # 技术维度权重
SCORING_WEIGHT_TREND = 0.30      # 趋势维度权重