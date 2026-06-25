"""
双弦投资系统 v2.0 — 配置文件
==================================
逻辑链弦(月线牛市+日线突破V3.0) + 资金流弦(七步复盘+三重确认)
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
PUSH_TYPE = os.environ.get("PUSH_TYPE", "console")
PUSH_ENABLED = os.environ.get("PUSH_ENABLED", "false").lower() == "true"
 
# PushPlus 配置（主推送）
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
SEND_KEY = os.environ.get("SEND_KEY", "")
DINGTALK_TOKEN = os.environ.get("DINGTALK_TOKEN", "")
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "")
WECHAT_KEY = os.environ.get("WECHAT_KEY", "")
PUSH_TOKEN = os.environ.get("PUSH_TOKEN", "")

# ── 输出 ────────────────────────────────────────────────
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./reports")
REPORT_PREFIX = "shuangxian_v2"

# ── 缓存目录(预计算数据) ────────────────────────────────
CACHE_DIR = os.environ.get("CACHE_DIR", "./cache")

# ── 月线数据回望 ────────────────────────────────────────
MONTHLY_BARS_NEEDED = 24  # 需要多少根月线来判定牛市(约2年)
DAILY_BARS_NEEDED = 150   # 日线回望(约7个月)
