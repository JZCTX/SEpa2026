"""通知服务。"""

from datetime import datetime

from takeout.db import Database
from takeout.domain.misc import Notification
from takeout.repositories.notice_repo import NoticeRepository
from takeout.security import Session
from takeout.utils import now


class NoticeService:
    """站内通知的推送与阅读。"""

    def __init__(self, db: Database, notices: NoticeRepository) -> None:
        self.db = db
        self.notices = notices

    def push(
        self,
        user_id: int,
        title: str,
        content: str,
        moment: datetime | None = None,
    ) -> None:
        """推送通知。"""
        self.notices.push(user_id, title, content, moment or now())

    def list_mine(
        self, session: Session, unread_only: bool = False
    ) -> list[Notification]:
        """查看本人通知。"""
        return self.notices.list_for(session.user_id, unread_only=unread_only)

    def unread_count(self, session: Session) -> int:
        """未读数量。"""
        return self.notices.unread_count(session.user_id)

    def mark_read(self, session: Session, notice_id: int) -> None:
        """标记已读。"""
        self.notices.mark_read(notice_id, session.user_id)

    def mark_all_read(self, session: Session) -> None:
        """全部已读。"""
        self.notices.mark_all_read(session.user_id)
