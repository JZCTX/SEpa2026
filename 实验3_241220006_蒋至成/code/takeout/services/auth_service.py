"""注册、登录与会话服务，对应 REQ-001、REQ-002、REQ-016。"""

from datetime import datetime

from takeout import config
from takeout.db import Database
from takeout.domain.user import Courier, User
from takeout.enums import ShopStatus, UserRole
from takeout.errors import (
    AccountLockedError,
    AuthError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from takeout.repositories.shop_repo import ShopRepository
from takeout.repositories.user_repo import UserRepository
from takeout.security import Session, SessionStore, Token, hash_password
from takeout.utils import is_valid_phone, now


class AuthService:
    """负责账号生命周期与登录态。"""

    def __init__(
        self,
        db: Database,
        users: UserRepository,
        shops: ShopRepository,
        sessions: SessionStore | None = None,
    ) -> None:
        self.db = db
        self.users = users
        self.shops = shops
        self.sessions = sessions or SessionStore()

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def register(
        self,
        phone: str,
        password: str,
        role: UserRole,
        address: str = "",
        shop_name: str = "",
        license_no: str = "",
        business_hours: str = config.BUSINESS_HOURS,
    ) -> User:
        """注册四类用户之一；商家注册时同步创建待审核店铺。"""
        self._validate_account(phone, password)
        if not isinstance(role, UserRole):
            raise ValidationError("用户角色不合法")
        if role == UserRole.MERCHANT:
            if not shop_name.strip() or not license_no.strip():
                raise ValidationError("商家注册必须填写店铺名称与资质编号")
            if self.shops.get_by_name(shop_name.strip()):
                raise ConflictError("店铺名称已被占用")
        if self.users.get_by_phone(phone):
            raise ConflictError("该手机号已注册")

        moment = now()
        with self.db.transaction():
            user_id = self.users.create(
                phone=phone,
                password_hash=hash_password(password),
                role=role,
                created_at=moment,
                default_address=address.strip(),
                work_status="空闲" if role == UserRole.COURIER else "",
            )
            if role == UserRole.MERCHANT:
                shop_id = self.shops.create(
                    merchant_id=user_id,
                    name=shop_name.strip(),
                    license_no=license_no.strip(),
                    status=ShopStatus.PENDING,
                    business_hours=business_hours,
                    created_at=moment,
                )
                self.users.update_shop_id(user_id, shop_id)
            user = self.users.get_by_id(user_id)
        if user is None:  # pragma: no cover - 数据库异常保护
            raise NotFoundError("注册失败，请稍后重试")
        return user

    def register_customer(self, phone: str, password: str, address: str = "") -> User:
        """注册顾客。"""
        return self.register(phone, password, UserRole.CUSTOMER, address=address)

    def register_merchant(
        self, phone: str, password: str, shop_name: str, license_no: str
    ) -> User:
        """注册商家并提交店铺资料。"""
        return self.register(
            phone,
            password,
            UserRole.MERCHANT,
            shop_name=shop_name,
            license_no=license_no,
        )

    def register_courier(self, phone: str, password: str) -> User:
        """注册配送员。"""
        return self.register(phone, password, UserRole.COURIER)

    def register_admin(self, phone: str, password: str) -> User:
        """注册管理员。"""
        return self.register(phone, password, UserRole.ADMIN)

    def _validate_account(self, phone: str, password: str) -> None:
        if not is_valid_phone(phone):
            raise ValidationError("请输入有效的 11 位手机号")
        if len(password) < 6:
            raise ValidationError("密码长度不能少于 6 位")

    # ------------------------------------------------------------------
    # 登录与会话
    # ------------------------------------------------------------------
    def login(self, phone: str, password: str, moment: datetime | None = None) -> Token:
        """登录，连续 5 次密码错误锁定 10 分钟。"""
        moment = moment or now()
        user = self.users.get_by_phone(phone)
        if user is None:
            raise AuthError("手机号或密码错误")
        if user.is_locked(moment):
            remain = int((user.lock_until - moment).total_seconds() // 60) + 1
            raise AccountLockedError(
                f"账号已锁定，请在 {remain} 分钟后重试"
            )
        if user.lock_until is not None:
            user.unlock()
            self.users.update_login_state(user)

        if not user.verify_password(password):
            locked = user.register_failure(moment)
            self.users.update_login_state(user)
            if locked:
                raise AccountLockedError(
                    f"连续输错 {config.MAX_LOGIN_FAILURES} 次，账号已锁定 "
                    f"{config.LOCK_MINUTES} 分钟"
                )
            remain = config.MAX_LOGIN_FAILURES - user.failed_attempts
            raise AuthError(f"手机号或密码错误，还可尝试 {remain} 次")

        self.users.reset_failure(user.user_id)
        session = Session(
            user_id=user.user_id,
            phone=user.phone,
            role=user.role,
            shop_id=user.shop_id,
            display_name=user.phone,
        )
        return self.sessions.issue(session)

    def logout(self, token_value: str) -> None:
        """注销登录态。"""
        self.sessions.revoke(token_value)

    def resolve(self, token_value: str) -> Session:
        """把令牌解析为会话。"""
        return self.sessions.resolve(token_value)

    def change_password(
        self, session: Session, old_password: str, new_password: str
    ) -> None:
        """修改密码。"""
        user = self.get_user(session.user_id)
        if not user.verify_password(old_password):
            raise AuthError("原密码不正确")
        if len(new_password) < 6:
            raise ValidationError("新密码长度不能少于 6 位")
        self.users.update_password(user.user_id, hash_password(new_password))

    def update_address(self, session: Session, address: str) -> None:
        """顾客更新默认收货地址。"""
        if session.role != UserRole.CUSTOMER:
            raise ValidationError("只有顾客可以设置收货地址")
        if not address.strip():
            raise ValidationError("收货地址不能为空")
        self.users.update_default_address(session.user_id, address.strip())

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_user(self, user_id: int) -> User:
        """按主键取得用户。"""
        user = self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        return user

    def available_couriers(self) -> list[Courier]:
        """列出空闲配送员。"""
        couriers = [
            user for user in self.users.list_users(UserRole.COURIER)
            if isinstance(user, Courier) and user.available
        ]
        return couriers

    def list_users(self, role: UserRole | None = None) -> list[User]:
        """管理员查看用户列表。"""
        return self.users.list_users(role)
