"""系统枚举，对应 UML 类图中的 5 个枚举类型。

枚举值直接使用中文，写入数据库后仍然可读；代码中通过枚举成员访问，
避免出现散落的字符串常量。
"""

from enum import StrEnum


class UserRole(StrEnum):
    """用户角色。"""

    CUSTOMER = "顾客"
    MERCHANT = "商家"
    COURIER = "配送员"
    ADMIN = "管理员"


class ShopStatus(StrEnum):
    """店铺状态。"""

    PENDING = "待审核"
    OPEN = "营业"
    CLOSED = "歇业"
    REJECTED = "审核驳回"


class DishStatus(StrEnum):
    """菜品状态。"""

    DRAFT = "草稿"
    ON_SALE = "在售"
    OFF_SHELF = "下架"
    SOLD_OUT = "售罄"


class OrderStatus(StrEnum):
    """订单状态。"""

    PENDING_PAY = "待支付"
    PAID = "已支付"
    COOKING = "制作中"
    PENDING_DELIVERY = "待配送"
    DELIVERING = "配送中"
    PENDING_HANDLE = "待处理"
    DELIVERED = "已送达"
    COMPLETED = "已完成"
    CANCELLED = "已取消"
    REFUNDED = "已退款"


class DeliveryStatus(StrEnum):
    """配送单状态。"""

    PENDING_ASSIGN = "待分配"
    PENDING_PICKUP = "待取餐"
    DELIVERING = "配送中"
    DELIVERED = "已送达"
    FAILED = "配送失败"


ORDER_STATUS_CHOICES = [status.value for status in OrderStatus]
DISH_STATUS_CHOICES = [status.value for status in DishStatus]
