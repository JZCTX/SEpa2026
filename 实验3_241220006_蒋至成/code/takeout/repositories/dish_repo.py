"""菜品仓储，包含基于版本号的原子扣减库存。"""

from datetime import datetime
from decimal import Decimal

from takeout.db import Database
from takeout.domain.dish import Dish
from takeout.enums import DishStatus
from takeout.utils import format_time, money


class DishRepository:
    """dishes 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        shop_id: int,
        name: str,
        category: str,
        price: Decimal,
        stock: int,
        status: DishStatus,
        moment: datetime,
    ) -> int:
        """新增菜品。"""
        text = format_time(moment)
        cursor = self.db.execute(
            """
            INSERT INTO dishes
                (shop_id, name, category, price, stock, status, version,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (shop_id, name, category, str(money(price)), stock, str(status), text, text),
        )
        return int(cursor.lastrowid)

    def get(self, dish_id: int) -> Dish | None:
        """按主键查询。"""
        row = self.db.query_one("SELECT * FROM dishes WHERE dish_id = ?", (dish_id,))
        return Dish.from_row(row) if row else None

    def list_by_shop(self, shop_id: int) -> list[Dish]:
        """列出一个店铺的全部菜品。"""
        rows = self.db.query_all(
            "SELECT * FROM dishes WHERE shop_id = ? ORDER BY dish_id", (shop_id,)
        )
        return [Dish.from_row(row) for row in rows]

    def search(
        self,
        keyword: str = "",
        category: str = "",
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        shop_id: int | None = None,
        only_on_sale: bool = True,
    ) -> list[Dish]:
        """多条件查询菜品，对应 REQ-005。"""
        conditions: list[str] = []
        params: list[object] = []
        if only_on_sale:
            conditions.append("d.status = ?")
            params.append(str(DishStatus.ON_SALE))
        if keyword:
            conditions.append("(d.name LIKE ? OR d.category LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if category:
            conditions.append("d.category = ?")
            params.append(category)
        if min_price is not None:
            conditions.append("CAST(d.price AS REAL) >= ?")
            params.append(float(min_price))
        if max_price is not None:
            conditions.append("CAST(d.price AS REAL) <= ?")
            params.append(float(max_price))
        if shop_id is not None:
            conditions.append("d.shop_id = ?")
            params.append(shop_id)
        sql = "SELECT d.* FROM dishes d"
        if only_on_sale:
            sql += " JOIN shops s ON s.shop_id = d.shop_id AND s.status = '营业'"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY CAST(d.price AS REAL), d.dish_id"
        return [Dish.from_row(row) for row in self.db.query_all(sql, params)]

    def update(self, dish: Dish, moment: datetime) -> None:
        """保存菜品的名称、分类、价格、库存与状态。"""
        self.db.execute(
            """
            UPDATE dishes
               SET name = ?, category = ?, price = ?, stock = ?, status = ?,
                   version = version + 1, updated_at = ?
             WHERE dish_id = ?
            """,
            (
                dish.name,
                dish.category,
                str(money(dish.price)),
                dish.stock,
                str(dish.status),
                format_time(moment),
                dish.dish_id,
            ),
        )

    def deduct_stock(
        self, dish_id: int, quantity: int, moment: datetime
    ) -> bool:
        """原子扣减库存。

        ``stock >= quantity`` 与状态判断都放在同一条 UPDATE 中，由 SQLite
        的单写锁保证不会出现负库存；返回 False 表示库存不足或已下架。
        """
        cursor = self.db.execute(
            """
            UPDATE dishes
               SET stock = stock - ?,
                   version = version + 1,
                   status = CASE
                                WHEN stock - ? = 0 AND status = '在售' THEN '售罄'
                                ELSE status
                            END,
                   updated_at = ?
             WHERE dish_id = ?
               AND stock >= ?
               AND status = '在售'
            """,
            (
                quantity,
                quantity,
                format_time(moment),
                dish_id,
                quantity,
            ),
        )
        return cursor.rowcount == 1

    def restore_stock(self, dish_id: int, quantity: int, moment: datetime) -> None:
        """回补库存；若原先因缺货售罄则恢复为在售。"""
        self.db.execute(
            """
            UPDATE dishes
               SET stock = stock + ?,
                   version = version + 1,
                   status = CASE WHEN status = '售罄' THEN '在售' ELSE status END,
                   updated_at = ?
             WHERE dish_id = ?
            """,
            (quantity, format_time(moment), dish_id),
        )

    def count_by_shop(self, shop_id: int) -> int:
        """统计店铺菜品数量。"""
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM dishes WHERE shop_id = ?", (shop_id,)
        ) or 0)
