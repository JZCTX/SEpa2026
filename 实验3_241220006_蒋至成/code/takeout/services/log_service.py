"""操作日志服务，对应 REQ-013。"""

from datetime import date, timedelta

from takeout import config
from takeout.db import Database
from takeout.domain.misc import OperationLog
from takeout.enums import UserRole
from takeout.errors import PermissionDeniedError
from takeout.repositories.log_repo import LogRepository
from takeout.security import Session
from takeout.utils import now


class LogService:
    """负责日志写入、查询与过期清理。"""

    def __init__(self, db: Database, logs: LogRepository) -> None:
        self.db = db
        self.logs = logs

    def record(
        self,
        session: Session | None,
        action: str,
        target_type: str,
        target_id: str,
        before_state: str = "",
        after_state: str = "",
        shop_id: int | None = None,
    ) -> None:
        """记录一条关键操作；系统定时任务以 operator_id=0 记录。"""
        operator_id = session.user_id if session else 0
        operator_role = str(session.role) if session else "系统"
        log = OperationLog(
            operator_id=operator_id,
            operator_role=operator_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_state=before_state,
            after_state=after_state,
            shop_id=shop_id if shop_id is not None else (session.shop_id if session else None),
            created_at=now(),
        )
        self.logs.write(log)

    def query(
        self,
        session: Session,
        action: str = "",
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
    ) -> list[OperationLog]:
        """管理员查全部日志，商家只查本店日志。"""
        if session.role == UserRole.ADMIN:
            return self.logs.query(
                action=action,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        if session.role == UserRole.MERCHANT:
            if session.shop_id is None:
                return []
            return self.logs.query(
                shop_id=session.shop_id,
                action=action,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        raise PermissionDeniedError("只有管理员和商家可以查询操作日志")

    def cleanup_expired(self) -> int:
        """清理超过 180 天的日志。"""
        before = now() - timedelta(days=config.LOG_RETENTION_DAYS)
        return self.logs.cleanup(before)
