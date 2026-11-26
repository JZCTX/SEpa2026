"""订单、订单明细、支付与退款领域模型。"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from sqlite3 import Row
from typing import Mapping

from takeout.enums import OrderStatus
from takeout.errors import InvalidTransitionError
from takeout.utils import money, parse_time

# 订单状态机：键为当前状态，值为允许迁移到的目标状态
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING_PAY: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.COOKING, OrderStatus.REFUNDED},
    OrderStatus.COOKING: {OrderStatus.PENDING_DELIVERY, OrderStatus.REFUNDED},
    OrderStatus.PENDING_DELIVERY: {OrderStatus.DELIVERING},
    OrderStatus.DELIVERING: {OrderStatus.DELIVERED, OrderStatus.PENDING_HANDLE},
    OrderStatus.PENDING_HANDLE: {OrderStatus.DELIVERING, OrderStatus.REFUNDED},
    OrderStatus.DELIVERED: {OrderStatus.COMPLETED},
}

TERMINAL_STATUSES = {
    OrderStatus.COMPLETED,
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
}


@dataclass
class OrderItem:
    """订单明细，保存下单瞬间的菜名与单价快照。"""

    item_id: int = 0
    order_id: int = 0
    dish_id: int = 0
    dish_name_snapshot: str = ""
    unit_price_snapshot: Decimal = Decimal("0.00")
    quantity: int = 0
    subtotal: Decimal = Decimal("0.00")

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "OrderItem":
        """从数据库行构造明细。"""
        return cls(
            item_id=int(row["item_id"]),
            order_id=int(row["order_id"]),
            dish_id=int(row["dish_id"]),
            dish_name_snapshot=str(row["dish_name_snapshot"]),
            unit_price_snapshot=money(row["unit_price_snapshot"]),
            quantity=int(row["quantity"]),
            subtotal=money(row["subtotal"]),
        )

    @classmethod
    def create(
        cls,
        dish_id: int,
        dish_name: str,
        unit_price: Decimal,
        quantity: int,
    ) -> "OrderItem":
        """根据购物车条目生成快照。"""
        return cls(
            dish_id=dish_id,
            dish_name_snapshot=dish_name,
            unit_price_snapshot=money(unit_price),
            quantity=quantity,
            subtotal=money(unit_price * quantity),
        )


@dataclass
class Order:
    """订单聚合根，状态迁移统一由本类校验。"""

    order_id: int = 0
    order_no: str = ""
    customer_id: int = 0
    shop_id: int = 0
    status: OrderStatus = OrderStatus.PENDING_PAY
    total_amount: Decimal = Decimal("0.00")
    delivery_fee: Decimal = Decimal("0.00")
    address_snapshot: str = ""
    idempotency_key: str = ""
    created_at: datetime | None = None
    pay_time: datetime | None = None
    cancel_reason: str = ""
    updated_at: datetime | None = None
    items: list[OrderItem] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "Order":
        """从数据库行构造订单。"""
        return cls(
            order_id=int(row["order_id"]),
            order_no=str(row["order_no"]),
            customer_id=int(row["customer_id"]),
            shop_id=int(row["shop_id"]),
            status=OrderStatus(row["status"]),
            total_amount=money(row["total_amount"]),
            delivery_fee=money(row["delivery_fee"]),
            address_snapshot=str(row["address_snapshot"]),
            idempotency_key=str(row["idempotency_key"]),
            created_at=parse_time(row["created_at"]),
            pay_time=parse_time(row["pay_time"]),
            cancel_reason=str(row["cancel_reason"]),
            updated_at=parse_time(row["updated_at"]),
        )

    def can_transit_to(self, target: OrderStatus) -> bool:
        """判断当前状态能否迁移到目标状态。"""
        return target in ALLOWED_TRANSITIONS.get(self.status, set())

    def transit(self, target: OrderStatus) -> None:
        """执行状态迁移，非法迁移抛出异常。"""
        if not self.can_transit_to(target):
            raise InvalidTransitionError(
                f"订单状态不能从「{self.status}」变为「{target}」"
            )
        self.status = target

    def pay(self, moment: datetime) -> None:
        """模拟支付成功。"""
        self.transit(OrderStatus.PAID)
        self.pay_time = moment

    def accept(self) -> None:
        """商家接单。"""
        self.transit(OrderStatus.COOKING)

    def reject(self, reason: str) -> None:
        """商家拒单，订单退款。"""
        self.cancel_reason = reason
        self.transit(OrderStatus.REFUNDED)

    def finish_cook(self) -> None:
        """商家出餐。"""
        self.transit(OrderStatus.PENDING_DELIVERY)

    def start_delivery(self) -> None:
        """分配配送员后开始配送。"""
        self.transit(OrderStatus.DELIVERING)

    def mark_delivered(self) -> None:
        """配送员确认送达。"""
        self.transit(OrderStatus.DELIVERED)

    def report_failed(self, reason: str) -> None:
        """配送失败，进入待处理。"""
        self.cancel_reason = reason
        self.transit(OrderStatus.PENDING_HANDLE)

    def complete(self) -> None:
        """顾客确认或超时自动完成。"""
        self.transit(OrderStatus.COMPLETED)

    def cancel(self, reason: str) -> None:
        """未支付订单取消。"""
        self.cancel_reason = reason
        self.transit(OrderStatus.CANCELLED)

    def refund(self, reason: str) -> None:
        """已支付订单退款。"""
        self.cancel_reason = reason
        self.transit(OrderStatus.REFUNDED)

    @property
    def is_terminal(self) -> bool:
        """是否为终态。"""
        return self.status in TERMINAL_STATUSES

    @property
    def subtotal(self) -> Decimal:
        """商品金额合计。"""
        return money(self.total_amount - self.delivery_fee)

    def item_quantity(self, dish_id: int) -> int:
        """指定菜品在订单中的数量。"""
        return sum(item.quantity for item in self.items if item.dish_id == dish_id)


@dataclass
class Payment:
    """模拟支付记录。"""

    pay_id: int = 0
    order_id: int = 0
    trade_no: str = ""
    amount: Decimal = Decimal("0.00")
    channel: str = "模拟支付"
    status: str = "成功"
    paid_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "Payment":
        """从数据库行构造支付记录。"""
        return cls(
            pay_id=int(row["pay_id"]),
            order_id=int(row["order_id"]),
            trade_no=str(row["trade_no"]),
            amount=money(row["amount"]),
            channel=str(row["channel"]),
            status=str(row["status"]),
            paid_at=parse_time(row["paid_at"]),
        )


@dataclass
class Refund:
    """退款记录。"""

    refund_id: int = 0
    order_id: int = 0
    refund_no: str = ""
    amount: Decimal = Decimal("0.00")
    reason: str = ""
    status: str = "已退款"
    refunded_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "Refund":
        """从数据库行构造退款记录。"""
        return cls(
            refund_id=int(row["refund_id"]),
            order_id=int(row["order_id"]),
            refund_no=str(row["refund_no"]),
            amount=money(row["amount"]),
            reason=str(row["reason"]),
            status=str(row["status"]),
            refunded_at=parse_time(row["refunded_at"]),
        )
