"""菜品领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from sqlite3 import Row
from typing import Mapping

from takeout.enums import DishStatus
from takeout.errors import InvalidTransitionError, ValidationError
from takeout.utils import money, parse_time


@dataclass
class Dish:
    """菜品。价格和库存是顾客下单时校验的核心字段。"""

    dish_id: int = 0
    shop_id: int = 0
    name: str = ""
    category: str = ""
    price: Decimal = Decimal("0.00")
    stock: int = 0
    status: DishStatus = DishStatus.DRAFT
    version: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "Dish":
        """从数据库行构造菜品。"""
        return cls(
            dish_id=int(row["dish_id"]),
            shop_id=int(row["shop_id"]),
            name=str(row["name"]),
            category=str(row["category"]),
            price=money(row["price"]),
            stock=int(row["stock"]),
            status=DishStatus(row["status"]),
            version=int(row["version"]),
            created_at=parse_time(row["created_at"]),
            updated_at=parse_time(row["updated_at"]),
        )

    def publish(self) -> None:
        """上架，库存为 0 时自动标记售罄。"""
        if self.status == DishStatus.ON_SALE:
            raise InvalidTransitionError("菜品已经在上架状态")
        if self.stock <= 0:
            self.status = DishStatus.SOLD_OUT
        else:
            self.status = DishStatus.ON_SALE

    def off_shelf(self) -> None:
        """下架。"""
        if self.status not in (DishStatus.ON_SALE, DishStatus.SOLD_OUT):
            raise InvalidTransitionError("只有在售或售罄的菜品可以下架")
        self.status = DishStatus.OFF_SHELF

    def change_price(self, new_price: Decimal | str | float) -> None:
        """调整价格，只影响之后的新订单。"""
        value = money(new_price)
        if value <= 0:
            raise ValidationError("菜品价格必须大于 0")
        self.price = value

    def set_stock(self, stock: int) -> None:
        """直接设置库存。"""
        if stock < 0:
            raise ValidationError("库存不能为负数")
        self.stock = stock
        if self.status == DishStatus.ON_SALE and stock == 0:
            self.status = DishStatus.SOLD_OUT
        elif self.status == DishStatus.SOLD_OUT and stock > 0:
            self.status = DishStatus.ON_SALE

    def deduct_stock(self, quantity: int) -> bool:
        """扣减库存，库存不足返回 False。扣除到 0 时转为售罄。"""
        if quantity <= 0:
            raise ValidationError("购买数量必须大于 0")
        if self.stock < quantity:
            return False
        self.stock -= quantity
        if self.stock == 0 and self.status == DishStatus.ON_SALE:
            self.status = DishStatus.SOLD_OUT
        return True

    def restore_stock(self, quantity: int) -> None:
        """回补库存，售罄状态恢复为在售。"""
        if quantity <= 0:
            raise ValidationError("回补数量必须大于 0")
        self.stock += quantity
        if self.status == DishStatus.SOLD_OUT:
            self.status = DishStatus.ON_SALE

    def is_available(self, quantity: int = 1) -> bool:
        """是否可购买指定数量。"""
        return self.status == DishStatus.ON_SALE and self.stock >= quantity
