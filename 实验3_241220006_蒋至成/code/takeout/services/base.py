"""服务层公共权限校验。"""

from takeout.db import Database
from takeout.enums import UserRole
from takeout.errors import PermissionDeniedError
from takeout.security import Session


def require_role(session: Session, *roles: UserRole) -> Session:
    """校验当前会话是否属于指定角色之一。"""
    if session.role not in roles:
        allowed = "、".join(str(role) for role in roles)
        raise PermissionDeniedError(f"该操作仅限{allowed}使用")
    return session


def require_shop(session: Session, shop_id: int) -> None:
    """校验商家只能操作自己的店铺。"""
    if session.role == UserRole.MERCHANT and session.shop_id != shop_id:
        raise PermissionDeniedError("只能操作本店铺的数据")


class BaseService:
    """持有数据库连接的服务基类。"""

    def __init__(self, db: Database) -> None:
        self.db = db
