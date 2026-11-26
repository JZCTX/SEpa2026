"""运行配置。

所有时间阈值、金额规则集中在此，既方便演示时调整，也避免魔法数字散落。
"""

import os
from decimal import Decimal
from pathlib import Path

APP_NAME = "校园外卖点餐与配送系统"
VERSION = "1.0.0"

# 数据库默认放在程序目录下的 data 子目录
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "takeout.db"
DB_PATH = Path(os.environ.get("TAKEOUT_DB", DEFAULT_DB_PATH))

# 业务阈值
ACCEPT_TIMEOUT_MINUTES = int(os.environ.get("TAKEOUT_ACCEPT_TIMEOUT", "15"))
AUTO_CONFIRM_MINUTES = int(os.environ.get("TAKEOUT_AUTO_CONFIRM", "30"))
PENDING_HANDLE_MINUTES = 30
LOG_RETENTION_DAYS = 180
MAX_LOGIN_FAILURES = 5
LOCK_MINUTES = 10
TOKEN_HOURS = 8

# 配送规则
DELIVERY_FEE = Decimal("3.00")
BUSINESS_HOURS = "07:00-23:00"

# 会话与调度
SCHEDULER_INTERVAL_SECONDS = 20
PAGE_SIZE = 20
