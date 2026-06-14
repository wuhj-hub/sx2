"""
双弦投资系统 — 配置文件
==================================
所有可调参数集中在此，改配置不动主逻辑。
GitHub Actions 运行时，推送凭证从环境变量读取。

双弦系统核心理念：
- 逻辑链（赛道卡点）：解决"买什么"的问题
- 资金流（量价信号）：解决"什么时候买"的问题
- 双线AND门控：两个条件都满足才动手
"""

import os
from pathlib import Path

# ── 项目路径 ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", str(BASE_DIR / "reports"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 数据源 ──────────────────────────────────────────────
DATA_SOURCE = "akshare"       # 主数据源，可选 akshare / sina_fallback

# ── 七步复盘 SOP 阈值 ──────────────────────────────────
BREATH_TURNOVER_RATIO = 0.80     # 成交额 < 20日均值 * 此值 → 冷区
BREATH_OVERHEAT_PERCENTILE = 90  # 换手率 > 过去一年此分位 → 过热

INDEX_CODES = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "全A等权替代": "sh000985",
}

ETF_CHECK_WINDOW = 20
ETF_GIANT_SUBSCRIBE_MULT = 3.0
ETF_REDEEM_WEEKS = 2

SECTOR_CONCENTRATION_STD = 1.0
SECTOR_TOP_REMOVE_RATIO = 0.20
STOCK_TOP_N = 100
MARGIN_ANOMALY_STD = 2.0

# ── 六层滤网 ────────────────────────────────────────────
FILTER_MARKET_CAP_MIN = 100
FILTER_MARKET_CAP_MAX = 800
FILTER_TURNOVER_RATE_MIN = 0.005
FILTER_TURNOVER_RATE_MAX = 0.04
FILTER_ACCEL_DAYS = 2
FILTER_ETF_WINDOW = 5
FILTER_SECTOR_STD = 1.0

# ── 三重确认 ────────────────────────────────────────────
CONFIRM_NORTH_WINDOW = 5
CONFIRM_ETF_WINDOW = 5
CONFIRM_LEADER_COUNT = 5

# ════════════════════════════════════════════════════════
# 双弦系统新增配置
# ════════════════════════════════════════════════════════

# ── 逻辑链候选池 ────────────────────────────────────────
LOGIC_POOL_FILE = DATA_DIR / "logic_pool.yaml"  # 逻辑链标的池文件

# 赛道卡点配置
SECTOR_BLOCK_CONFIG = {
    "国产替代率目标": 0.70,     # 国产化率目标阈值
    "专精特新加分": True,       # 专精特新企业加分
    "卡脖子环节加分": True,     # 卡脖子环节加分
}

# ── 标的分级阈值 ────────────────────────────────────────
GRADE_A_MAX = 5                  # A级上限数量
GRADE_A_MARGIN_ACCEL_THRESHOLD = 0.5  # A级资金加速度阈值
GRADE_B_UPGRADE_WEEKS = 2        # B级升级为A级的观察周数
GRADE_B_UPGRADE_ACCEL = 0.3      # B级升级需要每周资金加速度
GRADE_C_LOGIC_CHECK_HOURS = 72   # C级需在72小时内完成逻辑初判

# ── 熔断配置 ────────────────────────────────────────────
CIRCUIT_BREAK_CONFIG = {
    # 软熔断
    "soft_observation_days": 5,      # 软熔断观察天数
    "soft_frozen_days": 3,           # 冻结加仓天数
    
    # 硬熔断
    "hard_reduce_ratio": 0.50,       # 建议减仓比例
    "hard_clear_days": 3,           # 3日内清仓
    
    # 熔断触发条件
    "accel_negative_days": 3,       # 资金加速度连续转负天数 → 软熔断
    "sector_concentration_drop_sigma": 2.0,  # 板块资金浓度骤降倍数标准差
    "sector_observation_days": 3,   # 板块异常观察天数
}

# ── 里程碑跟踪 ──────────────────────────────────────────
MILESTONE_FILE = DATA_DIR / "portfolio.yaml"  # 持仓里程碑文件
MILESTONE_OVERDUE_DAYS = 7      # 里程碑超时天数阈值

# ── 预警系统配置 ────────────────────────────────────────
ALERT_CONFIG = {
    # 推送渠道
    "daily_channel": "console",      # 日常推送渠道: console / serverchan / dingtalk / wechat
    "urgent_channel": "serverchan",   # 紧急推送渠道
    
    # 推送时间
    "daily_push_time": "20:00",       # 每日复盘推送时间
    "urgent_push_deadline": 120,      # 熔断预警2小时内确认（分钟）
    
    # 预警级别
    "green_hours": 24,               # 🟢日常：每日一次
    "yellow_hours": 12,              # 🟡预警：12小时内确认
    "red_minutes": 120,              # 🔴熔断：2小时内确认
}

# ── 系统状态阶段 ────────────────────────────────────────
SYSTEM_STAGES = {
    "stage1_watch": "观望期",      # 市场冷区/分歧
    "stage2_prepare": "准备期",    # 三重确认部分通过
    "stage3_action": "行动期",     # 三重确认全部通过
    "stage4_defense": "防御期",    # 出现熔断信号
}

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

# ── 报告配置 ────────────────────────────────────────────
REPORT_PREFIX = "shuangxian_review"
REPORT_FORMAT = "md"  # markdown
