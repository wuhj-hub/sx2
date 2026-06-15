"""
资金流实盘复盘脚本 — 配置文件
==================================
所有可调参数集中在此，改配置不动主逻辑。
GitHub Actions 运行时，推送凭证从环境变量读取。
"""

import os

# ── 数据源 ──────────────────────────────────────────────
DATA_SOURCE = "akshare"       # 主数据源，可选 akshare / sina_fallback

# ── 七步复盘 SOP 阈值 ──────────────────────────────────
# 第一步：全市场呼吸检查
BREATH_TURNOVER_RATIO = 0.80     # 成交额 < 20日均值 * 此值 → 冷区
BREATH_OVERHEAT_PERCENTILE = 90  # 换手率 > 过去一年此分位 → 过热

# 第二步：三指数
INDEX_CODES = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "全A等权替代": "sh000985",
}

# 第三步：ETF申赎
ETF_CHECK_WINDOW = 20            # 计算均值的回望窗口（日）
ETF_GIANT_SUBSCRIBE_MULT = 3.0   # 单日净申购 > 20日均值 * 此倍 → 巨量信号
ETF_REDEEM_WEEKS = 2             # 连续N周净赎回 → 信号

# 第四步：板块资金浓度
SECTOR_CONCENTRATION_STD = 1.0   # 资金浓度 > 正N个标准差 → 触发
SECTOR_TOP_REMOVE_RATIO = 0.20   # 去掉板块内市值前N比例的股票

# 第五步：个股资金流扫描
STOCK_TOP_N = 100                # 扫描成交额排名前N的个股

# 第六步：融资融券
MARGIN_ANOMALY_STD = 2.0         # 融资余额日变化 > 20日均值 ± N倍标准差 → 异常

# ── 六层滤网 ────────────────────────────────────────────
FILTER_MARKET_CAP_MIN = 100      # 流通市值下限（亿元）
FILTER_MARKET_CAP_MAX = 800      # 流通市值上限（亿元）
FILTER_TURNOVER_RATE_MIN = 0.005 # 20日日均换手率下限
FILTER_TURNOVER_RATE_MAX = 0.04  # 20日日均换手率上限
FILTER_ACCEL_DAYS = 2            # 资金加速度连续为正的天数
FILTER_ETF_WINDOW = 5            # ETF申赎回望窗口（日）
FILTER_SECTOR_STD = 1.0          # 板块资金浓度标准差阈值

# ── 三重确认 ────────────────────────────────────────────
CONFIRM_NORTH_WINDOW = 5         # 北向资金回望窗口（日）
CONFIRM_ETF_WINDOW = 5           # ETF申赎回望窗口（日）
CONFIRM_LEADER_COUNT = 5         # 检查成交额最高的N只龙头

# ── 输出 ────────────────────────────────────────────────
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./reports")  # 报告输出目录
REPORT_PREFIX = "daily_review"   # 报告文件名前缀

# ── 推送配置 ────────────────────────────────────────────
PUSH_TYPE = os.environ.get("PUSH_TYPE", "console")
PUSH_ENABLED = os.environ.get("PUSH_ENABLED", "false").lower() == "true"

# Server酱
SEND_KEY = os.environ.get("SEND_KEY", "")

# 钉钉机器人
DINGTALK_TOKEN = os.environ.get("DINGTALK_TOKEN", "")
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "")

# 企业微信机器人
WECHAT_KEY = os.environ.get("WECHAT_KEY", "")

# 兼容
PUSH_TOKEN = os.environ.get("PUSH_TOKEN", "")
