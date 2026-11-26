"""领域模型包。

类与实验二 UML 类图一一对应，模型只表达业务数据和状态约束，
不直接访问数据库；持久化由 ``takeout.repositories`` 完成。
"""

from takeout.domain.cart import Cart, CartItem
from takeout.domain.delivery import DeliveryTask
from takeout.domain.dish import Dish
from takeout.domain.misc import DailyReport, Notification, OperationLog
from takeout.domain.order import Order, OrderItem, Payment, Refund
from takeout.domain.shop import Shop
from takeout.domain.user import (
    Admin,
    Courier,
    Customer,
    Merchant,
    User,
    user_from_row,
)

__all__ = [
    "Admin",
    "Cart",
    "CartItem",
    "Courier",
    "Customer",
    "DailyReport",
    "DeliveryTask",
    "Dish",
    "Merchant",
    "Notification",
    "OperationLog",
    "Order",
    "OrderItem",
    "Payment",
    "Refund",
    "Shop",
    "User",
    "user_from_row",
]
