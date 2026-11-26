"""配送单仓储。"""

from datetime import datetime

from takeout.db import Database
from takeout.domain.delivery import DeliveryTask
from takeout.enums import DeliveryStatus
from takeout.utils import format_time


class DeliveryRepository:
    """delivery_tasks 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        order_id: int,
        courier_id: int,
        status: DeliveryStatus,
        moment: datetime,
    ) -> int:
        """为订单创建配送单。"""
        cursor = self.db.execute(
            """
            INSERT INTO delivery_tasks
                (order_id, courier_id, status, assigned_at, fail_reason)
            VALUES (?, ?, ?, ?, '')
            """,
            (order_id, courier_id, str(status), format_time(moment)),
        )
        return int(cursor.lastrowid)

    def get_by_order(self, order_id: int) -> DeliveryTask | None:
        """查询订单对应的配送单。"""
        row = self.db.query_one(
            "SELECT * FROM delivery_tasks WHERE order_id = ?", (order_id,)
        )
        return DeliveryTask.from_row(row) if row else None

    def get(self, task_id: int) -> DeliveryTask | None:
        """按主键查询。"""
        row = self.db.query_one(
            "SELECT * FROM delivery_tasks WHERE task_id = ?", (task_id,)
        )
        return DeliveryTask.from_row(row) if row else None

    def list_by_courier(self, courier_id: int) -> list[DeliveryTask]:
        """列出配送员的全部配送单。"""
        rows = self.db.query_all(
            "SELECT * FROM delivery_tasks WHERE courier_id = ? ORDER BY task_id DESC",
            (courier_id,),
        )
        return [DeliveryTask.from_row(row) for row in rows]

    def list_by_status(self, statuses: list[DeliveryStatus]) -> list[DeliveryTask]:
        """按状态查询配送单。"""
        values = [str(status) for status in statuses]
        if not values:
            return []
        placeholders = ", ".join("?" for _ in values)
        rows = self.db.query_all(
            f"SELECT * FROM delivery_tasks WHERE status IN ({placeholders}) "
            "ORDER BY task_id",
            values,
        )
        return [DeliveryTask.from_row(row) for row in rows]

    def count_active_by_courier(self, courier_id: int) -> int:
        """统计配送员尚未完成的配送单数量。"""
        return int(self.db.scalar(
            """
            SELECT COUNT(*) FROM delivery_tasks
             WHERE courier_id = ? AND status IN ('待取餐', '配送中')
            """,
            (courier_id,),
        ) or 0)

    def update(self, task: DeliveryTask) -> None:
        """保存配送单状态与时间。"""
        self.db.execute(
            """
            UPDATE delivery_tasks
               SET courier_id = ?, status = ?, assigned_at = ?, pickup_at = ?,
                   delivered_at = ?, fail_reason = ?
             WHERE task_id = ?
            """,
            (
                task.courier_id,
                str(task.status),
                format_time(task.assigned_at),
                format_time(task.pickup_at),
                format_time(task.delivered_at),
                task.fail_reason,
                task.task_id,
            ),
        )
