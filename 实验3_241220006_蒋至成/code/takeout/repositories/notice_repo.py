"""站内通知仓储。"""

from datetime import datetime

from takeout.db import Database
from takeout.domain.misc import Notification
from takeout.utils import format_time


class NoticeRepository:
    """notifications 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def push(
        self, user_id: int, title: str, content: str, moment: datetime
    ) -> int:
        """推送一条通知。"""
        cursor = self.db.execute(
            """
            INSERT INTO notifications (user_id, title, content, read_flag, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (user_id, title, content, format_time(moment)),
        )
        return int(cursor.lastrowid)

    def list_for(
        self, user_id: int, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        """列出用户通知。"""
        sql = "SELECT * FROM notifications WHERE user_id = ?"
        if unread_only:
            sql += " AND read_flag = 0"
        sql += " ORDER BY notice_id DESC LIMIT ?"
        rows = self.db.query_all(sql, (user_id, limit))
        return [Notification.from_row(row) for row in rows]

    def unread_count(self, user_id: int) -> int:
        """未读数量。"""
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_flag = 0",
            (user_id,),
        ) or 0)

    def mark_read(self, notice_id: int, user_id: int) -> None:
        """标记单条已读。"""
        self.db.execute(
            "UPDATE notifications SET read_flag = 1 WHERE notice_id = ? AND user_id = ?",
            (notice_id, user_id),
        )

    def mark_all_read(self, user_id: int) -> None:
        """全部标记已读。"""
        self.db.execute(
            "UPDATE notifications SET read_flag = 1 WHERE user_id = ?", (user_id,)
        )
