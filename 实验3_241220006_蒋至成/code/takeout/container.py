"""依赖装配：把数据库、仓储与服务组装成应用对象。"""

from pathlib import Path

from takeout.db import Database
from takeout.repositories.cart_repo import CartRepository
from takeout.repositories.delivery_repo import DeliveryRepository
from takeout.repositories.dish_repo import DishRepository
from takeout.repositories.log_repo import LogRepository
from takeout.repositories.notice_repo import NoticeRepository
from takeout.repositories.order_repo import OrderRepository
from takeout.repositories.shop_repo import ShopRepository
from takeout.repositories.user_repo import UserRepository
from takeout.security import SessionStore
from takeout.services.auth_service import AuthService
from takeout.services.cart_service import CartService
from takeout.services.delivery_service import DeliveryService
from takeout.services.dish_service import DishService
from takeout.services.log_service import LogService
from takeout.services.notice_service import NoticeService
from takeout.services.order_service import OrderService
from takeout.services.scheduler import Scheduler
from takeout.services.shop_service import ShopService
from takeout.services.stats_service import StatsService


class Container:
    """应用容器，集中创建并持有全部服务实例。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db = Database(db_path)

        self.users = UserRepository(self.db)
        self.shops = ShopRepository(self.db)
        self.dishes = DishRepository(self.db)
        self.carts = CartRepository(self.db)
        self.orders = OrderRepository(self.db)
        self.tasks = DeliveryRepository(self.db)
        self.logs_repo = LogRepository(self.db)
        self.notices_repo = NoticeRepository(self.db)

        self.notices = NoticeService(self.db, self.notices_repo)
        self.logs = LogService(self.db, self.logs_repo)
        self.auth = AuthService(
            self.db, self.users, self.shops, SessionStore()
        )
        self.shop_service = ShopService(
            self.db, self.shops, self.users, self.logs, self.notices
        )
        self.dish_service = DishService(self.db, self.dishes, self.shops, self.logs)
        self.cart_service = CartService(self.db, self.carts, self.dishes)
        self.order_service = OrderService(
            self.db,
            self.orders,
            self.carts,
            self.dishes,
            self.shops,
            self.tasks,
            self.logs,
            self.notices,
        )
        self.delivery_service = DeliveryService(
            self.db,
            self.tasks,
            self.orders,
            self.shops,
            self.users,
            self.order_service,
            self.logs,
            self.notices,
        )
        self.stats_service = StatsService(self.db, self.orders, self.shops)
        self.scheduler = Scheduler(
            self.db, self.orders, self.tasks, self.order_service, self.logs
        )

    def close(self) -> None:
        """关闭数据库连接。"""
        self.db.close()
