"""用户领域模型：User 及其四个子类。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlite3 import Row
from typing import Mapping

from takeout import config
from takeout.enums import UserRole
from takeout.security import verify_password
from takeout.utils import now, parse_time


@dataclass
class User:
    """用户基类，保存登录与账号状态。"""

    user_id: int = 0
    phone: str = ""
    password_hash: str = ""
    role: UserRole = UserRole.CUSTOMER
    account_status: str = "正常"
    lock_until: datetime | None = None
    failed_attempts: int = 0
    default_address: str = ""
    shop_id: int | None = None
    work_status: str = ""
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "User":
        """从数据库行构造用户。"""
        return cls(
            user_id=int(row["user_id"]),
            phone=str(row["phone"]),
            password_hash=str(row["password_hash"]),
            role=UserRole(row["role"]),
            account_status=str(row["account_status"]),
            lock_until=parse_time(row["lock_until"]),
            failed_attempts=int(row["failed_attempts"]),
            default_address=str(row["default_address"]),
            shop_id=row["shop_id"],
            work_status=str(row["work_status"]),
            created_at=parse_time(row["created_at"]),
        )

    def verify_password(self, password: str) -> bool:
        """校验密码。"""
        return verify_password(password, self.password_hash)

    def is_locked(self, moment: datetime | None = None) -> bool:
        """账号当前是否处于锁定期。"""
        if self.lock_until is None:
            return False
        moment = moment or now()
        if moment >= self.lock_until:
            return False
        return True

    def lock(self, minutes: int = config.LOCK_MINUTES, moment: datetime | None = None) -> None:
        """锁定账号若干分钟。"""
        moment = moment or now()
        self.lock_until = moment + timedelta(minutes=minutes)
        self.account_status = "锁定"

    def unlock(self) -> None:
        """解除锁定并清零失败次数。"""
        self.lock_until = None
        self.account_status = "正常"
        self.failed_attempts = 0

    def register_failure(self, moment: datetime | None = None) -> bool:
        """记录一次密码错误，达到阈值时锁定并返回 True。"""
        moment = moment or now()
        self.failed_attempts += 1
        if self.failed_attempts >= config.MAX_LOGIN_FAILURES:
            self.lock(config.LOCK_MINUTES, moment)
            return True
        return False

    @property
    def is_idle_courier(self) -> bool:
        """配送员是否空闲。"""
        return self.role == UserRole.COURIER and self.work_status == "空闲"


@dataclass
class Customer(User):
    """顾客。"""

    @property
    def address(self) -> str:
        """默认收货地址。"""
        return self.default_address


@dataclass
class Merchant(User):
    """商家，持有一个店铺的编号。"""

    @property
    def has_shop(self) -> bool:
        """是否已绑定店铺。"""
        return self.shop_id is not None


@dataclass
class Courier(User):
    """配送员。"""

    @property
    def available(self) -> bool:
        """是否可以接单。"""
        return self.work_status == "空闲"


@dataclass
class Admin(User):
    """平台管理员。"""

    @property
    def can_audit(self) -> bool:
        """管理员天然具备审核权限。"""
        return self.role == UserRole.ADMIN


USER_CLASSES = {
    UserRole.CUSTOMER: Customer,
    UserRole.MERCHANT: Merchant,
    UserRole.COURIER: Courier,
    UserRole.ADMIN: Admin,
}


def user_from_row(row: Row | Mapping[str, object]) -> User:
    """依据角色列返回具体的用户子类实例。"""
    role = UserRole(row["role"])
    user_class = USER_CLASSES.get(role, User)
    return user_class(
        user_id=int(row["user_id"]),
        phone=str(row["phone"]),
        password_hash=str(row["password_hash"]),
        role=role,
        account_status=str(row["account_status"]),
        lock_until=parse_time(row["lock_until"]),
        failed_attempts=int(row["failed_attempts"]),
        default_address=str(row["default_address"]),
        shop_id=row["shop_id"],
        work_status=str(row["work_status"]),
        created_at=parse_time(row["created_at"]),
    )
