"""购物车仓储。"""

from datetime import datetime
from decimal import Decimal

from takeout.db import Database
from takeout.domain.cart import Cart, CartItem
from takeout.enums import DishStatus
from takeout.utils import format_time, money


class CartRepository:
    """carts 与 cart_items 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_cart(self, customer_id: int, moment: datetime) -> int:
        """取得购物车主键，没有则创建。"""
        row = self.db.query_one(
            "SELECT cart_id FROM carts WHERE customer_id = ?", (customer_id,)
        )
        if row:
            return int(row["cart_id"])
        cursor = self.db.execute(
            "INSERT INTO carts (customer_id, created_at) VALUES (?, ?)",
            (customer_id, format_time(moment)),
        )
        return int(cursor.lastrowid)

    def load(self, customer_id: int, moment: datetime) -> Cart:
        """读取带菜品信息的购物车。"""
        cart_id = self.ensure_cart(customer_id, moment)
        rows = self.db.query_all(
            """
            SELECT ci.dish_id, ci.quantity, ci.price_snapshot,
                   d.name, d.shop_id, d.price, d.stock, d.status
              FROM cart_items ci
              JOIN dishes d ON d.dish_id = ci.dish_id
             WHERE ci.cart_id = ?
             ORDER BY ci.dish_id
            """,
            (cart_id,),
        )
        items = [
            CartItem(
                dish_id=int(row["dish_id"]),
                dish_name=str(row["name"]),
                shop_id=int(row["shop_id"]),
                unit_price=money(row["price"]),
                price_snapshot=money(row["price_snapshot"]),
                quantity=int(row["quantity"]),
                stock=int(row["stock"]),
                dish_status=DishStatus(row["status"]),
            )
            for row in rows
        ]
        return Cart(cart_id=cart_id, customer_id=customer_id, items=items)

    def add_item(
        self,
        cart_id: int,
        dish_id: int,
        quantity: int,
        price_snapshot: Decimal,
    ) -> None:
        """加入购物车，已存在则累加数量。"""
        self.db.execute(
            """
            INSERT INTO cart_items (cart_id, dish_id, quantity, price_snapshot)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cart_id, dish_id) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                price_snapshot = excluded.price_snapshot
            """,
            (cart_id, dish_id, quantity, str(money(price_snapshot))),
        )

    def remove_item(self, cart_id: int, dish_id: int) -> None:
        """移除菜品。"""
        self.db.execute(
            "DELETE FROM cart_items WHERE cart_id = ? AND dish_id = ?",
            (cart_id, dish_id),
        )

    def clear(self, cart_id: int) -> None:
        """清空购物车。"""
        self.db.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))

    def update_price_snapshot(self, cart_id: int, dish_id: int, price: Decimal) -> None:
        """把购物车中的价格快照刷新为当前价格。"""
        self.db.execute(
            "UPDATE cart_items SET price_snapshot = ? WHERE cart_id = ? AND dish_id = ?",
            (str(money(price)), cart_id, dish_id),
        )
