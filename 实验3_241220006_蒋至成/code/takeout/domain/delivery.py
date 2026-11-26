"""配送单领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row
from typing import Mapping

from takeout.enums import DeliveryStatus
from takeout.errors import InvalidTransitionError
from takeout.utils import parse_time

DELIVERY_TRANSITIONS: dict[DeliveryStatus, set[DeliveryStatus]] = {
    DeliveryStatus.PENDING_ASSIGN: {
        DeliveryStatus.PENDING_PICKUP,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.PENDING_PICKUP: {
        DeliveryStatus.DELIVERING,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.DELIVERING: {
        DeliveryStatus.DELIVERED,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.FAILED: {DeliveryStatus.PENDING_PICKUP},
}


@dataclass
class DeliveryTask:
    """配送单，一个订单同时只允许一条有效配送单。"""

    task_id: int = 0
    order_id: int = 0
    courier_id: int = 0
    status: DeliveryStatus = DeliveryStatus.PENDING_ASSIGN
    assigned_at: datetime | None = None
    pickup_at: datetime | None = None
    delivered_at: datetime | None = None
    fail_reason: str = ""

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "DeliveryTask":
        """从数据库行构造配送单。"""
        return cls(
            task_id=int(row["task_id"]),
            order_id=int(row["order_id"]),
            courier_id=int(row["courier_id"]),
            status=DeliveryStatus(row["status"]),
            assigned_at=parse_time(row["assigned_at"]),
            pickup_at=parse_time(row["pickup_at"]),
            delivered_at=parse_time(row["delivered_at"]),
            fail_reason=str(row["fail_reason"]),
        )

    def transit(self, target: DeliveryStatus) -> None:
        """校验并执行配送状态迁移。"""
        if target not in DELIVERY_TRANSITIONS.get(self.status, set()):
            raise InvalidTransitionError(
                f"配送单状态不能从「{self.status}」变为「{target}」"
            )
        self.status = target

    def assign(self, courier_id: int, moment: datetime) -> None:
        """分配给配送员。"""
        self.transit(DeliveryStatus.PENDING_PICKUP)
        self.courier_id = courier_id
        self.assigned_at = moment
        self.fail_reason = ""

    def pickup(self, moment: datetime) -> None:
        """配送员取餐。"""
        self.transit(DeliveryStatus.DELIVERING)
        self.pickup_at = moment

    def confirm_delivered(self, moment: datetime) -> None:
        """确认送达。"""
        self.transit(DeliveryStatus.DELIVERED)
        self.delivered_at = moment

    def report_fail(self, reason: str) -> None:
        """上报配送失败。"""
        self.transit(DeliveryStatus.FAILED)
        self.fail_reason = reason

    def redispatch(self, courier_id: int, moment: datetime) -> None:
        """管理员协调后重新分配。"""
        self.transit(DeliveryStatus.PENDING_PICKUP)
        self.courier_id = courier_id
        self.assigned_at = moment
        self.fail_reason = ""

    @property
    def is_active(self) -> bool:
        """是否占用配送员。"""
        return self.status in (
            DeliveryStatus.PENDING_PICKUP,
            DeliveryStatus.DELIVERING,
        )
