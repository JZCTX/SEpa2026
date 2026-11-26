"""菜品服务：新增、上下架、改价、改库存与多条件查询。"""

from decimal import Decimal, InvalidOperation

from takeout.db import Database
from takeout.domain.dish import Dish
from takeout.enums import DishStatus, UserRole
from takeout.errors import NotFoundError, ValidationError
from takeout.repositories.dish_repo import DishRepository
from takeout.repositories.shop_repo import ShopRepository
from takeout.security import Session
from takeout.services.base import require_role, require_shop
from takeout.services.log_service import LogService
from takeout.utils import money, now


class DishService:
    """菜品业务，对应 REQ-004、REQ-005、REQ-014。"""

    def __init__(
        self,
        db: Database,
        dishes: DishRepository,
        shops: ShopRepository,
        logs: LogService,
    ) -> None:
        self.db = db
        self.dishes = dishes
        self.shops = shops
        self.logs = logs

    def get(self, dish_id: int) -> Dish:
        """按编号取得菜品。"""
        dish = self.dishes.get(dish_id)
        if dish is None:
            raise NotFoundError("菜品不存在")
        return dish

    def _get_owned(self, session: Session, dish_id: int) -> Dish:
        dish = self.get(dish_id)
        require_shop(session, dish.shop_id)
        return dish

    def create(
        self,
        session: Session,
        name: str,
        category: str,
        price: Decimal | str,
        stock: int,
        publish: bool = False,
    ) -> Dish:
        """商家新增菜品，默认保存草稿。"""
        require_role(session, UserRole.MERCHANT)
        if session.shop_id is None:
            raise ValidationError("商家尚未绑定店铺")
        name = name.strip()
        if not name:
            raise ValidationError("菜品名称不能为空")
        value = money(price)
        if value <= 0:
            raise ValidationError("菜品价格必须大于 0")
        if stock < 0:
            raise ValidationError("库存不能为负数")
        status = DishStatus.DRAFT
        if publish:
            status = DishStatus.ON_SALE if stock > 0 else DishStatus.SOLD_OUT
        dish_id = self.dishes.create(
            shop_id=session.shop_id,
            name=name,
            category=category.strip() or "其他",
            price=value,
            stock=stock,
            status=status,
            moment=now(),
        )
        dish = self.get(dish_id)
        self.logs.record(
            session, "新增菜品", "菜品", str(dish_id), "", str(dish.status)
        )
        return dish

    def update(
        self,
        session: Session,
        dish_id: int,
        name: str | None = None,
        category: str | None = None,
        price: Decimal | str | None = None,
        stock: int | None = None,
    ) -> Dish:
        """修改菜品基础信息。"""
        require_role(session, UserRole.MERCHANT)
        dish = self._get_owned(session, dish_id)
        before = f"{dish.name}/{dish.price}/{dish.stock}/{dish.status}"
        if name is not None:
            if not name.strip():
                raise ValidationError("菜品名称不能为空")
            dish.name = name.strip()
        if category is not None:
            dish.category = category.strip() or dish.category
        if price is not None:
            dish.change_price(price)
        if stock is not None:
            dish.set_stock(stock)
        self.dishes.update(dish, now())
        self.logs.record(
            session,
            "修改菜品",
            "菜品",
            str(dish_id),
            before,
            f"{dish.name}/{dish.price}/{dish.stock}/{dish.status}",
        )
        return self.get(dish_id)

    def change_price(
        self, session: Session, dish_id: int, price: Decimal | str
    ) -> Dish:
        """改价，只影响之后的新订单。"""
        require_role(session, UserRole.MERCHANT)
        dish = self._get_owned(session, dish_id)
        old_price = dish.price
        dish.change_price(price)
        self.dishes.update(dish, now())
        self.logs.record(
            session,
            "菜品改价",
            "菜品",
            str(dish_id),
            f"{old_price:.2f}",
            f"{dish.price:.2f}",
        )
        return self.get(dish_id)

    def set_stock(self, session: Session, dish_id: int, stock: int) -> Dish:
        """修改库存，0 表示售罄。"""
        require_role(session, UserRole.MERCHANT)
        dish = self._get_owned(session, dish_id)
        before = f"{dish.stock}/{dish.status}"
        dish.set_stock(stock)
        self.dishes.update(dish, now())
        self.logs.record(
            session,
            "调整库存",
            "菜品",
            str(dish_id),
            before,
            f"{dish.stock}/{dish.status}",
        )
        return self.get(dish_id)

    def publish(self, session: Session, dish_id: int) -> Dish:
        """上架菜品。"""
        require_role(session, UserRole.MERCHANT)
        dish = self._get_owned(session, dish_id)
        before = str(dish.status)
        dish.publish()
        self.dishes.update(dish, now())
        self.logs.record(
            session, "菜品上架", "菜品", str(dish_id), before, str(dish.status)
        )
        return self.get(dish_id)

    def off_shelf(self, session: Session, dish_id: int) -> Dish:
        """下架菜品。"""
        require_role(session, UserRole.MERCHANT)
        dish = self._get_owned(session, dish_id)
        before = str(dish.status)
        dish.off_shelf()
        self.dishes.update(dish, now())
        self.logs.record(
            session, "菜品下架", "菜品", str(dish_id), before, str(dish.status)
        )
        return self.get(dish_id)

    def list_mine(self, session: Session) -> list[Dish]:
        """商家查看本店全部菜品。"""
        require_role(session, UserRole.MERCHANT)
        if session.shop_id is None:
            return []
        return self.dishes.list_by_shop(session.shop_id)

    def search(
        self,
        keyword: str = "",
        category: str = "",
        min_price: Decimal | str | None = None,
        max_price: Decimal | str | None = None,
        shop_id: int | None = None,
    ) -> list[Dish]:
        """顾客多条件查询在售菜品。"""
        low = self._parse_price(min_price, "最低价")
        high = self._parse_price(max_price, "最高价")
        if low is not None and high is not None and low > high:
            raise ValidationError("价格区间不合法：最低价不能大于最高价")
        return self.dishes.search(
            keyword=keyword.strip(),
            category=category.strip(),
            min_price=low,
            max_price=high,
            shop_id=shop_id,
            only_on_sale=True,
        )

    @staticmethod
    def _parse_price(value: Decimal | str | None, field: str) -> Decimal | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = money(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"{field}格式不正确") from exc
        if parsed < 0:
            raise ValidationError(f"{field}不能为负数")
        return parsed
