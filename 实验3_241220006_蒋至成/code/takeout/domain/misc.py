"""统计报表、操作日志与通知模型。"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from sqlite3 import Row
from typing import Mapping

from takeout.utils import money, parse_time


@dataclass
class DailyReport:
    """商家日报：某一天的订单数、营业额与热销菜品。"""

    report_date: date
    order_count: int = 0
    gmv: Decimal = Decimal("0.00")
    top_dishes: list[tuple[str, int]] = field(default_factory=list)

    @classmethod
    def generate(
        cls,
        report_date: date,
        order_count: int,
        gmv: Decimal,
        top_dishes: list[tuple[str, int]] | None = None,
    ) -> "DailyReport":
        """根据统计结果生成日报对象。"""
        return cls(
            report_date=report_date,
            order_count=order_count,
            gmv=money(gmv),
            top_dishes=top_dishes or [],
        )


@dataclass
class OperationLog:
    """关键操作日志，对应 REQ-013。"""

    log_id: int = 0
    operator_id: int = 0
    operator_role: str = ""
    action: str = ""
    target_type: str = ""
    target_id: str = ""
    before_state: str = ""
    after_state: str = ""
    shop_id: int | None = None
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "OperationLog":
        """从数据库行构造日志。"""
        return cls(
            log_id=int(row["log_id"]),
            operator_id=int(row["operator_id"]),
            operator_role=str(row["operator_role"]),
            action=str(row["action"]),
            target_type=str(row["target_type"]),
            target_id=str(row["target_id"]),
            before_state=str(row["before_state"]),
            after_state=str(row["after_state"]),
            shop_id=row["shop_id"],
            created_at=parse_time(row["created_at"]),
        )

    def write(self) -> dict[str, object]:
        """转换为待写入数据库的字段，对应 UML 中的 write()。"""
        return {
            "operator_id": self.operator_id,
            "operator_role": self.operator_role,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "shop_id": self.shop_id,
            "created_at": self.created_at,
        }


@dataclass
class Notification:
    """站内通知，模拟短信与消息推送。"""

    notice_id: int = 0
    user_id: int = 0
    title: str = ""
    content: str = ""
    read_flag: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "Notification":
        """从数据库行构造通知。"""
        return cls(
            notice_id=int(row["notice_id"]),
            user_id=int(row["user_id"]),
            title=str(row["title"]),
            content=str(row["content"]),
            read_flag=bool(row["read_flag"]),
            created_at=parse_time(row["created_at"]),
        )

    def push(self) -> None:
        """新通知默认未读，对应 UML 中的 push()。"""
        self.read_flag = False
