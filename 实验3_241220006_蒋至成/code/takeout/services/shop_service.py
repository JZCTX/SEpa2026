"""店铺服务：入驻审核与营业状态。"""

from takeout.db import Database
from takeout.domain.shop import Shop
from takeout.enums import ShopStatus, UserRole
from takeout.errors import NotFoundError, ValidationError
from takeout.repositories.shop_repo import ShopRepository
from takeout.repositories.user_repo import UserRepository
from takeout.security import Session
from takeout.services.base import require_role
from takeout.services.log_service import LogService
from takeout.services.notice_service import NoticeService


class ShopService:
    """店铺业务，对应 REQ-003。"""

    def __init__(
        self,
        db: Database,
        shops: ShopRepository,
        users: UserRepository,
        logs: LogService,
        notices: NoticeService,
    ) -> None:
        self.db = db
        self.shops = shops
        self.users = users
        self.logs = logs
        self.notices = notices

    def get(self, shop_id: int) -> Shop:
        """按编号取得店铺。"""
        shop = self.shops.get(shop_id)
        if shop is None:
            raise NotFoundError("店铺不存在")
        return shop

    def get_my_shop(self, session: Session) -> Shop:
        """商家取得自己的店铺。"""
        require_role(session, UserRole.MERCHANT)
        shop = self.shops.get_by_merchant(session.user_id)
        if shop is None:
            raise NotFoundError("当前商家尚未创建店铺")
        return shop

    def submit_audit(self, session: Session, remark: str = "") -> Shop:
        """商家重新提交店铺审核。"""
        require_role(session, UserRole.MERCHANT)
        shop = self.get_my_shop(session)
        before = str(shop.status)
        shop.submit_audit()
        if remark:
            shop.audit_remark = remark
        self.shops.update(shop)
        self.logs.record(
            session, "提交店铺审核", "店铺", str(shop.shop_id), before, str(shop.status)
        )
        return shop

    def set_business(self, session: Session, is_open: bool) -> Shop:
        """商家切换营业/歇业。"""
        require_role(session, UserRole.MERCHANT)
        shop = self.get_my_shop(session)
        before = str(shop.status)
        if is_open:
            shop.open()
        else:
            shop.close()
        self.shops.update(shop)
        self.logs.record(
            session,
            "切换营业状态" if is_open else "暂停营业",
            "店铺",
            str(shop.shop_id),
            before,
            str(shop.status),
        )
        return shop

    def update_business_hours(self, session: Session, hours: str) -> Shop:
        """商家设置营业时段。"""
        require_role(session, UserRole.MERCHANT)
        shop = self.get_my_shop(session)
        shop.business_hours = hours.strip() or shop.business_hours
        self.shops.update(shop)
        self.logs.record(
            session, "修改营业时段", "店铺", str(shop.shop_id), "", shop.business_hours
        )
        return shop

    def audit(
        self, session: Session, shop_id: int, approved: bool, remark: str = ""
    ) -> Shop:
        """管理员审核店铺资质。"""
        require_role(session, UserRole.ADMIN)
        shop = self.get(shop_id)
        before = str(shop.status)
        if approved:
            shop.approve(remark or "资质审核通过")
        else:
            if not remark.strip():
                raise ValidationError("驳回店铺必须填写原因")
            shop.reject(remark.strip())
        self.shops.update(shop)
        self.logs.record(
            session,
            "审核店铺通过" if approved else "驳回店铺审核",
            "店铺",
            str(shop_id),
            before,
            str(shop.status),
        )
        self.notices.push(
            shop.merchant_id,
            "店铺审核结果",
            f"店铺「{shop.name}」审核结果：{shop.status}。{shop.audit_remark}",
        )
        return shop

    def list_pending(self, session: Session) -> list[Shop]:
        """管理员查看待审核店铺。"""
        require_role(session, UserRole.ADMIN)
        return self.shops.list_all(ShopStatus.PENDING)

    def list_all(self, session: Session) -> list[Shop]:
        """管理员查看全部店铺。"""
        require_role(session, UserRole.ADMIN)
        return self.shops.list_all()

    def list_open_shops(self) -> list[Shop]:
        """顾客浏览营业中的店铺。"""
        return [shop for shop in self.shops.list_all() if shop.can_order()]

    def find_by_name(self, name: str) -> Shop | None:
        """按名称查找店铺。"""
        return self.shops.get_by_name(name)
