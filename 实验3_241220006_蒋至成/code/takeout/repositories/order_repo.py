"""订单、明细、支付与退款仓储。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from takeout.db import Database
from takeout.domain.order import Order, OrderItem, Payment, Refund
from takeout.enums import OrderStatus
from takeout.utils import format_date, format_time, money, today


class OrderRepository:
    """orders、order_items、payments、refunds 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        order_no: str,
        customer_id: int,
        shop_id: int,
        total_amount: Decimal,
        delivery_fee: Decimal,
        address_snapshot: str,
        idempotency_key: str,
        moment: datetime,
    ) -> int:
        """创建待支付订单。"""
        text = format_time(moment)
        cursor = self.db.execute(
            """
            INSERT INTO orders
                (order_no, customer_id, shop_id, status, total_amount,
                 delivery_fee, address_snapshot, idempotency_key,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_no,
                customer_id,
                shop_id,
                str(OrderStatus.PENDING_PAY),
                str(money(total_amount)),
                str(money(delivery_fee)),
                address_snapshot,
                idempotency_key,
                text,
                text,
            ),
        )
        return int(cursor.lastrowid)

    def add_item(self, order_id: int, item: OrderItem) -> None:
        """写入订单明细快照。"""
        self.db.execute(
            """
            INSERT INTO order_items
                (order_id, dish_id, dish_name_snapshot, unit_price_snapshot,
                 quantity, subtotal)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                item.dish_id,
                item.dish_name_snapshot,
                str(item.unit_price_snapshot),
                item.quantity,
                str(item.subtotal),
            ),
        )

    def _row_to_order(self, row) -> Order:
        order = Order.from_row(row)
        order.items = self.list_items(order.order_id)
        return order

    def get_by_no(self, order_no: str) -> Order | None:
        """按订单号查询，包含明细。"""
        row = self.db.query_one("SELECT * FROM orders WHERE order_no = ?", (order_no,))
        return self._row_to_order(row) if row else None

    def get_by_id(self, order_id: int) -> Order | None:
        """按主键查询，包含明细。"""
        row = self.db.query_one("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        return self._row_to_order(row) if row else None

    def get_by_idempotency_key(
        self, customer_id: int, idempotency_key: str
    ) -> Order | None:
        """按幂等键查询，用于重复提交保护。"""
        row = self.db.query_one(
            "SELECT * FROM orders WHERE idempotency_key = ? AND customer_id = ?",
            (idempotency_key, customer_id),
        )
        return self._row_to_order(row) if row else None

    def list_items(self, order_id: int) -> list[OrderItem]:
        """读取订单明细。"""
        rows = self.db.query_all(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY item_id",
            (order_id,),
        )
        return [OrderItem.from_row(row) for row in rows]

    def update(self, order: Order, moment: datetime) -> None:
        """保存订单状态与相关时间。"""
        self.db.execute(
            """
            UPDATE orders
               SET status = ?, pay_time = ?, cancel_reason = ?, updated_at = ?
             WHERE order_id = ?
            """,
            (
                str(order.status),
                format_time(order.pay_time),
                order.cancel_reason,
                format_time(moment),
                order.order_id,
            ),
        )

    def list_orders(
        self,
        customer_id: int | None = None,
        shop_id: int | None = None,
        courier_id: int | None = None,
        status: OrderStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        keyword: str = "",
        limit: int = 100,
    ) -> list[Order]:
        """多条件查询订单，对应 REQ-011。"""
        sql = "SELECT o.* FROM orders o"
        params: list[object] = []
        if courier_id is not None:
            sql += " JOIN delivery_tasks t ON t.order_id = o.order_id"
        conditions: list[str] = []
        if courier_id is not None:
            conditions.append("t.courier_id = ?")
            params.append(courier_id)
        if customer_id is not None:
            conditions.append("o.customer_id = ?")
            params.append(customer_id)
        if shop_id is not None:
            conditions.append("o.shop_id = ?")
            params.append(shop_id)
        if status is not None:
            conditions.append("o.status = ?")
            params.append(str(status))
        if date_from is not None:
            conditions.append("substr(o.created_at, 1, 10) >= ?")
            params.append(format_date(date_from))
        if date_to is not None:
            conditions.append("substr(o.created_at, 1, 10) <= ?")
            params.append(format_date(date_to))
        if keyword:
            conditions.append("(o.order_no LIKE ? OR o.address_snapshot LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY o.order_id DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_order(row) for row in self.db.query_all(sql, params)]

    def list_by_status(
        self, statuses: Iterable[OrderStatus], limit: int = 200
    ) -> list[Order]:
        """按状态集合查询订单，供定时任务使用。"""
        values = [str(status) for status in statuses]
        if not values:
            return []
        placeholders = ", ".join("?" for _ in values)
        rows = self.db.query_all(
            f"SELECT * FROM orders WHERE status IN ({placeholders}) "
            "ORDER BY order_id LIMIT ?",
            (*values, limit),
        )
        return [self._row_to_order(row) for row in rows]

    def create_payment(
        self, order_id: int, trade_no: str, amount: Decimal, moment: datetime
    ) -> None:
        """写入模拟支付记录。"""
        self.db.execute(
            """
            INSERT INTO payments (order_id, trade_no, amount, channel, status, paid_at)
            VALUES (?, ?, ?, '模拟支付', '成功', ?)
            """,
            (order_id, trade_no, str(money(amount)), format_time(moment)),
        )

    def get_payment(self, order_id: int) -> Payment | None:
        """查询订单的支付记录。"""
        row = self.db.query_one(
            "SELECT * FROM payments WHERE order_id = ?", (order_id,)
        )
        return Payment.from_row(row) if row else None

    def create_refund(
        self,
        order_id: int,
        refund_no: str,
        amount: Decimal,
        reason: str,
        moment: datetime,
    ) -> None:
        """写入退款记录。"""
        self.db.execute(
            """
            INSERT INTO refunds
                (order_id, refund_no, amount, reason, status, refunded_at)
            VALUES (?, ?, ?, ?, '已退款', ?)
            """,
            (order_id, refund_no, str(money(amount)), reason, format_time(moment)),
        )

    def get_refund(self, order_id: int) -> Refund | None:
        """查询订单最近一条退款记录。"""
        row = self.db.query_one(
            "SELECT * FROM refunds WHERE order_id = ? ORDER BY refund_id DESC LIMIT 1",
            (order_id,),
        )
        return Refund.from_row(row) if row else None

    def list_completed(
        self, shop_id: int | None = None, day: date | None = None
    ) -> list[Order]:
        """查询已完成订单，用于销售统计。"""
        conditions = ["status = ?"]
        params: list[object] = [str(OrderStatus.COMPLETED)]
        if shop_id is not None:
            conditions.append("shop_id = ?")
            params.append(shop_id)
        if day is not None:
            conditions.append("substr(COALESCE(updated_at, created_at), 1, 10) = ?")
            params.append(format_date(day or today()))
        sql = "SELECT * FROM orders WHERE " + " AND ".join(conditions)
        sql += " ORDER BY order_id"
        return [self._row_to_order(row) for row in self.db.query_all(sql, params)]

    def top_dishes(self, shop_id: int, day: date, limit: int = 5) -> list[tuple[str, int]]:
        """按已完成订单统计热销菜品。"""
        rows = self.db.query_all(
            """
            SELECT oi.dish_name_snapshot AS name, SUM(oi.quantity) AS qty
              FROM order_items oi
              JOIN orders o ON o.order_id = oi.order_id
             WHERE o.shop_id = ?
               AND o.status = ?
               AND substr(COALESCE(o.updated_at, o.created_at), 1, 10) = ?
             GROUP BY oi.dish_name_snapshot
             ORDER BY qty DESC
             LIMIT ?
            """,
            (shop_id, str(OrderStatus.COMPLETED), format_date(day), limit),
        )
        return [(str(row["name"]), int(row["qty"])) for row in rows]

    def counts_by_shop(self) -> list[tuple[int, str, int]]:
        """按店铺统计订单量，返回 (店铺编号, 店铺名, 订单数)。"""
        rows = self.db.query_all(
            """
            SELECT s.shop_id, s.name, COUNT(o.order_id) AS total
              FROM shops s
              LEFT JOIN orders o ON o.shop_id = s.shop_id
             GROUP BY s.shop_id, s.name
             ORDER BY total DESC, s.shop_id
            """
        )
        return [
            (int(row["shop_id"]), str(row["name"]), int(row["total"]))
            for row in rows
        ]

    def count_by_status(self) -> dict[str, int]:
        """按状态统计全平台订单数量。"""
        rows = self.db.query_all(
            "SELECT status, COUNT(*) AS total FROM orders GROUP BY status"
        )
        return {str(row["status"]): int(row["total"]) for row in rows}
