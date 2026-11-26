"""购物车服务。"""

from takeout.db import Database
from takeout.domain.cart import Cart
from takeout.enums import DishStatus, UserRole
from takeout.errors import ConflictError, SoldOutError, ValidationError
from takeout.repositories.cart_repo import CartRepository
from takeout.repositories.dish_repo import DishRepository
from takeout.security import Session
from takeout.services.base import require_role
from takeout.utils import now


class CartService:
    """购物车的增删改查。"""

    def __init__(
        self, db: Database, carts: CartRepository, dishes: DishRepository
    ) -> None:
        self.db = db
        self.carts = carts
        self.dishes = dishes

    def load(self, session: Session) -> Cart:
        """读取当前顾客的购物车。"""
        require_role(session, UserRole.CUSTOMER)
        return self.carts.load(session.user_id, now())

    def add(self, session: Session, dish_id: int, quantity: int) -> Cart:
        """加入购物车：校验在售、库存与单一店铺。"""
        require_role(session, UserRole.CUSTOMER)
        if quantity <= 0:
            raise ValidationError("购买数量必须大于 0")
        dish = self.dishes.get(dish_id)
        if dish is None:
            raise ValidationError("菜品不存在")
        if dish.status != DishStatus.ON_SALE:
            raise SoldOutError(f"菜品「{dish.name}」当前为{dish.status}，无法购买")
        cart = self.carts.load(session.user_id, now())
        cart.ensure_single_shop(dish.shop_id)
        current = sum(
            item.quantity for item in cart.items if item.dish_id == dish_id
        )
        if dish.stock < current + quantity:
            raise SoldOutError(
                f"菜品「{dish.name}」库存不足，当前仅剩 {dish.stock} 份"
            )
        self.carts.add_item(cart.cart_id, dish_id, quantity, dish.price)
        return self.carts.load(session.user_id, now())

    def remove(self, session: Session, dish_id: int) -> Cart:
        """移除购物车条目。"""
        require_role(session, UserRole.CUSTOMER)
        cart = self.carts.load(session.user_id, now())
        self.carts.remove_item(cart.cart_id, dish_id)
        return self.carts.load(session.user_id, now())

    def clear(self, session: Session) -> None:
        """清空购物车。"""
        require_role(session, UserRole.CUSTOMER)
        cart = self.carts.load(session.user_id, now())
        self.carts.clear(cart.cart_id)

    def refresh_prices(self, session: Session) -> int:
        """把购物车价格快照刷新为菜品当前价，返回刷新条数。"""
        require_role(session, UserRole.CUSTOMER)
        cart = self.carts.load(session.user_id, now())
        changed = 0
        for item in cart.items:
            if item.price_changed:
                self.carts.update_price_snapshot(
                    cart.cart_id, item.dish_id, item.unit_price
                )
                changed += 1
        return changed

    def summary(self, session: Session) -> dict[str, object]:
        """购物车摘要，供下单前确认。"""
        cart = self.load(session)
        unavailable = [item.dish_name for item in cart.items if not item.available]
        return {
            "cart": cart,
            "count": sum(item.quantity for item in cart.items),
            "subtotal": cart.total,
            "unavailable": unavailable,
        }

    def validate_for_checkout(self, cart: Cart) -> None:
        """下单前检查购物车中的菜品是否仍然可买。"""
        if cart.is_empty:
            raise ValidationError("购物车为空，请先添加菜品")
        for item in cart.items:
            if item.dish_status == DishStatus.SOLD_OUT:
                raise SoldOutError(f"菜品「{item.dish_name}」已售罄，请移除后再下单")
            if item.dish_status != DishStatus.ON_SALE:
                raise ConflictError(
                    f"菜品「{item.dish_name}」已{item.dish_status}，请移除后再下单"
                )
            if item.stock < item.quantity:
                raise SoldOutError(
                    f"菜品「{item.dish_name}」库存不足，仅剩 {item.stock} 份"
                )
