"""操作日志仓储。"""

from datetime import date, datetime

from takeout.db import Database
from takeout.domain.misc import OperationLog
from takeout.utils import format_date, format_time


class LogRepository:
    """operation_logs 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def write(self, log: OperationLog) -> int:
        """写入一条操作日志。"""
        record = log.write()
        cursor = self.db.execute(
            """
            INSERT INTO operation_logs
                (operator_id, operator_role, action, target_type, target_id,
                 before_state, after_state, shop_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["operator_id"],
                record["operator_role"],
                record["action"],
                record["target_type"],
                record["target_id"],
                record["before_state"],
                record["after_state"],
                record["shop_id"],
                format_time(record["created_at"]) if record["created_at"] else "",
            ),
        )
        return int(cursor.lastrowid)

    def query(
        self,
        shop_id: int | None = None,
        operator_id: int | None = None,
        action: str = "",
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
    ) -> list[OperationLog]:
        """按条件查询日志。"""
        conditions: list[str] = []
        params: list[object] = []
        if shop_id is not None:
            conditions.append("shop_id = ?")
            params.append(shop_id)
        if operator_id is not None:
            conditions.append("operator_id = ?")
            params.append(operator_id)
        if action:
            conditions.append("action LIKE ?")
            params.append(f"%{action}%")
        if date_from is not None:
            conditions.append("substr(created_at, 1, 10) >= ?")
            params.append(format_date(date_from))
        if date_to is not None:
            conditions.append("substr(created_at, 1, 10) <= ?")
            params.append(format_date(date_to))
        sql = "SELECT * FROM operation_logs"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY log_id DESC LIMIT ?"
        params.append(limit)
        return [
            OperationLog.from_row(row) for row in self.db.query_all(sql, params)
        ]

    def cleanup(self, before: datetime) -> int:
        """删除超过保留期的日志，返回删除条数。"""
        cursor = self.db.execute(
            "DELETE FROM operation_logs WHERE created_at < ?",
            (format_time(before),),
        )
        return cursor.rowcount
