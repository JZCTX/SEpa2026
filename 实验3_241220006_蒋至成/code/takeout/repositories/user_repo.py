"""用户仓储。"""

from datetime import datetime

from takeout.db import Database
from takeout.domain.user import User, user_from_row
from takeout.enums import UserRole
from takeout.utils import format_time


class UserRepository:
    """users 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        phone: str,
        password_hash: str,
        role: UserRole,
        created_at: datetime,
        default_address: str = "",
        work_status: str = "",
    ) -> int:
        """新增用户并返回主键。"""
        cursor = self.db.execute(
            """
            INSERT INTO users
                (phone, password_hash, role, account_status, failed_attempts,
                 default_address, work_status, created_at)
            VALUES (?, ?, ?, '正常', 0, ?, ?, ?)
            """,
            (phone, password_hash, str(role), default_address,
             work_status, format_time(created_at)),
        )
        return int(cursor.lastrowid)

    def get_by_id(self, user_id: int) -> User | None:
        """按主键查询。"""
        row = self.db.query_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return user_from_row(row) if row else None

    def get_by_phone(self, phone: str) -> User | None:
        """按手机号查询。"""
        row = self.db.query_one("SELECT * FROM users WHERE phone = ?", (phone,))
        return user_from_row(row) if row else None

    def list_users(self, role: UserRole | None = None) -> list[User]:
        """列出用户，可按角色过滤。"""
        if role is None:
            rows = self.db.query_all("SELECT * FROM users ORDER BY user_id")
        else:
            rows = self.db.query_all(
                "SELECT * FROM users WHERE role = ? ORDER BY user_id", (str(role),)
            )
        return [user_from_row(row) for row in rows]

    def update_login_state(self, user: User) -> None:
        """保存登录失败次数、锁定时间与账号状态。"""
        self.db.execute(
            """
            UPDATE users
               SET failed_attempts = ?, lock_until = ?, account_status = ?
             WHERE user_id = ?
            """,
            (
                user.failed_attempts,
                format_time(user.lock_until),
                user.account_status,
                user.user_id,
            ),
        )

    def reset_failure(self, user_id: int) -> None:
        """登录成功后清零失败次数。"""
        self.db.execute(
            "UPDATE users SET failed_attempts = 0, lock_until = NULL, "
            "account_status = '正常' WHERE user_id = ?",
            (user_id,),
        )

    def update_shop_id(self, user_id: int, shop_id: int) -> None:
        """绑定商家的店铺编号。"""
        self.db.execute(
            "UPDATE users SET shop_id = ? WHERE user_id = ?", (shop_id, user_id)
        )

    def update_work_status(self, user_id: int, work_status: str) -> None:
        """更新配送员工作状态。"""
        self.db.execute(
            "UPDATE users SET work_status = ? WHERE user_id = ?",
            (work_status, user_id),
        )

    def update_default_address(self, user_id: int, address: str) -> None:
        """更新顾客默认地址。"""
        self.db.execute(
            "UPDATE users SET default_address = ? WHERE user_id = ?",
            (address, user_id),
        )

    def update_password(self, user_id: int, password_hash: str) -> None:
        """修改密码哈希。"""
        self.db.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (password_hash, user_id),
        )
