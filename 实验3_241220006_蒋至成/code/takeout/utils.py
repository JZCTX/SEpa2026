"""通用工具函数：时间、金额、编号与终端对齐。"""

import re
import secrets
import unicodedata
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"
PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
MONEY_QUANT = Decimal("0.01")


def now() -> datetime:
    """返回精确到秒的当前时间。"""
    return datetime.now().replace(microsecond=0)


def today() -> date:
    """返回当前日期。"""
    return date.today()


def format_time(value: datetime | None) -> str:
    """把时间格式化为数据库字符串。"""
    return value.strftime(TIME_FORMAT) if value else ""


def parse_time(value: str | None) -> datetime | None:
    """解析数据库中的时间字符串。"""
    if not value:
        return None
    return datetime.strptime(value, TIME_FORMAT)


def format_date(value: date) -> str:
    """把日期格式化为数据库字符串。"""
    return value.strftime(DATE_FORMAT)


def parse_date(value: str | None) -> date | None:
    """解析日期字符串，空值返回 None。"""
    if not value:
        return None
    return datetime.strptime(value, DATE_FORMAT).date()


def money(value: Decimal | int | float | str) -> Decimal:
    """转换为保留两位小数的金额。"""
    return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def money_text(value: Decimal | int | float | str) -> str:
    """金额显示为两位小数字符串。"""
    return f"{money(value):.2f}"


def new_order_no() -> str:
    """生成订单号：OD + 日期 + 6 位随机串。"""
    return "OD" + now().strftime("%Y%m%d") + secrets.token_hex(3).upper()


def new_trade_no() -> str:
    """生成模拟支付流水号。"""
    return "PAY" + now().strftime("%Y%m%d%H%M%S") + secrets.token_hex(2).upper()


def new_refund_no() -> str:
    """生成退款单号。"""
    return "RF" + now().strftime("%Y%m%d%H%M%S") + secrets.token_hex(2).upper()


def is_valid_phone(phone: str) -> bool:
    """校验中国大陆手机号。"""
    return bool(PHONE_PATTERN.match(phone))


def text_width(text: str) -> int:
    """计算字符串在等宽终端中的显示宽度（中文占两列）。"""
    width = 0
    for char in str(text):
        width += 2 if unicodedata.east_asian_width(char) in "WF" else 1
    return width


def pad(text: object, width: int, align: str = "left") -> str:
    """按终端显示宽度补空格，避免中文表格错位。"""
    content = "" if text is None else str(text)
    spaces = max(0, width - text_width(content))
    if align == "right":
        return " " * spaces + content
    if align == "center":
        left = spaces // 2
        return " " * left + content + " " * (spaces - left)
    return content + " " * spaces


def truncate(text: object, width: int) -> str:
    """按显示宽度截断长文本。"""
    content = "" if text is None else str(text)
    if text_width(content) <= width:
        return content
    result = ""
    used = 0
    for char in content:
        char_width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used + char_width > width - 1:
            break
        result += char
        used += char_width
    return result + "…"
