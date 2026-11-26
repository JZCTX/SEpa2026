"""仓储层：封装全部 SQL，向上只暴露领域对象。"""

from takeout.repositories.cart_repo import CartRepository
from takeout.repositories.delivery_repo import DeliveryRepository
from takeout.repositories.dish_repo import DishRepository
from takeout.repositories.log_repo import LogRepository
from takeout.repositories.notice_repo import NoticeRepository
from takeout.repositories.order_repo import OrderRepository
from takeout.repositories.shop_repo import ShopRepository
from takeout.repositories.user_repo import UserRepository

__all__ = [
    "CartRepository",
    "DeliveryRepository",
    "DishRepository",
    "LogRepository",
    "NoticeRepository",
    "OrderRepository",
    "ShopRepository",
    "UserRepository",
]
