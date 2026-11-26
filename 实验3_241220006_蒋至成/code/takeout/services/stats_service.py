"""查询与统计服务，对应 REQ-012。"""

from datetime import date, timedelta
from decimal import Decimal

from takeout.db import Database
from takeout.domain.misc import DailyReport
from takeout.enums import UserRole
from takeout.repositories.order_repo import OrderRepository
from takeout.repositories.shop_repo import ShopRepository
from takeout.security import Session
from takeout.services.base import require_role
from takeout.utils import money, today


class StatsService:
    """商家日报与平台统计。"""

    def __init__(
        self, db: Database, orders: OrderRepository, shops: ShopRepository
    ) -> None:
        self.db = db
        self.orders = orders
        self.shops = shops

    def merchant_daily(self, session: Session, day: date | None = None) -> DailyReport:
        """商家某日经营日报，只统计已完成订单。"""
        require_role(session, UserRole.MERCHANT)
        day = day or today()
        shop_id = session.shop_id or 0
        completed = self.orders.list_completed(shop_id=shop_id, day=day)
        gmv = money(sum((order.total_amount for order in completed), Decimal("0.00")))
        return DailyReport.generate(
            day,
            len(completed),
            gmv,
            self.orders.top_dishes(shop_id, day),
        )

    def merchant_recent(self, session: Session, days: int = 7) -> list[DailyReport]:
        """商家最近若干天日报。"""
        require_role(session, UserRole.MERCHANT)
        end = today()
        reports = []
        for offset in range(days - 1, -1, -1):
            day = end - timedelta(days=offset)
            completed = self.orders.list_completed(
                shop_id=session.shop_id or 0, day=day
            )
            gmv = money(
                sum((order.total_amount for order in completed), Decimal("0.00"))
            )
            reports.append(DailyReport.generate(day, len(completed), gmv))
        return reports

    def platform_overview(self, session: Session) -> dict[str, object]:
        """管理员平台概览。"""
        require_role(session, UserRole.ADMIN)
        completed = self.orders.list_completed()
        gmv = money(sum((order.total_amount for order in completed), Decimal("0.00")))
        return {
            "shop_count": len(self.shops.list_all()),
            "order_count": sum(self.orders.count_by_status().values()),
            "completed_count": len(completed),
            "gmv": gmv,
            "status_counts": self.orders.count_by_status(),
        }

    def shop_comparison(self, session: Session) -> list[tuple[int, str, int]]:
        """管理员查看各店铺订单量对比。"""
        require_role(session, UserRole.ADMIN)
        return self.orders.counts_by_shop()

    def merchant_revenue(self, session: Session) -> Decimal:
        """商家累计营业额（已完成订单）。"""
        require_role(session, UserRole.MERCHANT)
        completed = self.orders.list_completed(shop_id=session.shop_id or 0)
        return money(
            sum((order.total_amount for order in completed), Decimal("0.00"))
        )
