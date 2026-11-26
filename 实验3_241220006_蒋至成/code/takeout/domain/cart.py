"""购物车领域模型。"""

from dataclasses import dataclass, field
from decimal import Decimal

from takeout.enums import DishStatus
from takeout.errors import ConflictError, ValidationError
from takeout.utils import money


@dataclass
class CartItem:
    """购物车条目，保存加入时的单价快照用于改价检测。"""

    dish_id: int
    dish_name: str
    shop_id: int
    unit_price: Decimal
    price_snapshot: Decimal
    quantity: int
    stock: int
    dish_status: DishStatus

    @property
    def subtotal(self) -> Decimal:
        """小计。"""
        return money(self.unit_price * self.quantity)

    @property
    def price_changed(self) -> bool:
        """当前价格是否已与加入购物车时不同。"""
        return money(self.price_snapshot) != money(self.unit_price)

    @property
    def available(self) -> bool:
        """菜品当前是否仍可购买。"""
        return self.dish_status == DishStatus.ON_SALE and self.stock >= self.quantity


@dataclass
class Cart:
    """购物车，一个顾客只有一个购物车。"""

    cart_id: int = 0
    customer_id: int = 0
    items: list[CartItem] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """购物车是否为空。"""
        return not self.items

    @property
    def total(self) -> Decimal:
        """商品合计金额（不含配送费）。"""
        return money(sum((item.subtotal for item in self.items), Decimal("0.00")))

    @property
    def shop_ids(self) -> set[int]:
        """购物车中出现的店铺编号集合。"""
        return {item.shop_id for item in self.items}

    def ensure_single_shop(self, shop_id: int) -> None:
        """一个订单只能属于一个店铺，因此购物车不允许混合店铺。"""
        existing = self.shop_ids
        if existing and shop_id not in existing:
            raise ConflictError("购物车中已有其他店铺的菜品，请先清空购物车")

    def add_item(self, item: CartItem) -> None:
        """加入或累加菜品数量。"""
        if item.quantity <= 0:
            raise ValidationError("购买数量必须大于 0")
        self.ensure_single_shop(item.shop_id)
        for existing in self.items:
            if existing.dish_id == item.dish_id:
                existing.quantity += item.quantity
                return
        self.items.append(item)

    def remove_item(self, dish_id: int) -> None:
        """移除菜品。"""
        self.items = [item for item in self.items if item.dish_id != dish_id]

    def clear(self) -> None:
        """清空购物车。"""
        self.items.clear()
