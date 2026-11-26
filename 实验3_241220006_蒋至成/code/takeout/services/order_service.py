"""订单服务：下单、支付、状态流转、取消退款与查询。"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from takeout import config
from takeout.db import Database
from takeout.domain.order import Order, OrderItem, Payment, Refund
from takeout.enums import OrderStatus, UserRole
from takeout.errors import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    PriceChangedError,
    SoldOutError,
    ValidationError,
)
from takeout.repositories.cart_repo import CartRepository
from takeout.repositories.delivery_repo import DeliveryRepository
from takeout.repositories.dish_repo import DishRepository
from takeout.repositories.order_repo import OrderRepository
from takeout.repositories.shop_repo import ShopRepository
from takeout.security import Session
from takeout.services.base import require_role, require_shop
from takeout.services.log_service import LogService
from takeout.services.notice_service import NoticeService
from takeout.utils import (
    money,
    new_order_no,
    new_refund_no,
    new_trade_no,
    now,
)


class OrderService:
    """订单主流程，完整实现实验二状态图中的允许与禁止转换。"""

    def __init__(
        self,
        db: Database,
        orders: OrderRepository,
        carts: CartRepository,
        dishes: DishRepository,
        shops: ShopRepository,
        delivery_tasks: DeliveryRepository,
        logs: LogService,
        notices: NoticeService,
    ) -> None:
        self.db = db
        self.orders = orders
        self.carts = carts
        self.dishes = dishes
        self.shops = shops
        self.delivery_tasks = delivery_tasks
        self.logs = logs
        self.notices = notices

    # ------------------------------------------------------------------
    # 查询与权限
    # ------------------------------------------------------------------
    def get(self, order_no: str) -> Order:
        """按订单号取得订单。"""
        order = self.orders.get_by_no(order_no)
        if order is None:
            raise NotFoundError("订单不存在")
        return order

    def get_by_id(self, order_id: int) -> Order:
        """按主键取得订单，供配送服务内部使用。"""
        order = self.orders.get_by_id(order_id)
        if order is None:
            raise NotFoundError("订单不存在")
        return order

    def get_visible(self, session: Session, order_no: str) -> Order:
        """取得当前用户可见的订单，越权时拒绝。"""
        order = self.get(order_no)
        if session.role == UserRole.CUSTOMER and order.customer_id != session.user_id:
            raise PermissionDeniedError("只能查看自己的订单")
        if session.role == UserRole.MERCHANT and order.shop_id != session.shop_id:
            raise PermissionDeniedError("只能查看本店订单")
        if session.role == UserRole.COURIER:
            task = self.delivery_tasks.get_by_order(order.order_id)
            if task is None or task.courier_id != session.user_id:
                raise PermissionDeniedError("只能查看分配给自己的配送订单")
        return order

    def list_orders(
        self,
        session: Session,
        status: OrderStatus | None = None,
        date_from=None,
        date_to=None,
        keyword: str = "",
        limit: int = 100,
    ) -> list[Order]:
        """按角色限定查询范围，再叠加筛选条件。"""
        if session.role == UserRole.CUSTOMER:
            return self.orders.list_orders(
                customer_id=session.user_id,
                status=status,
                date_from=date_from,
                date_to=date_to,
                keyword=keyword,
                limit=limit,
            )
        if session.role == UserRole.MERCHANT:
            if session.shop_id is None:
                return []
            return self.orders.list_orders(
                shop_id=session.shop_id,
                status=status,
                date_from=date_from,
                date_to=date_to,
                keyword=keyword,
                limit=limit,
            )
        if session.role == UserRole.COURIER:
            return self.orders.list_orders(
                courier_id=session.user_id,
                status=status,
                date_from=date_from,
                date_to=date_to,
                keyword=keyword,
                limit=limit,
            )
        return self.orders.list_orders(
            status=status,
            date_from=date_from,
            date_to=date_to,
            keyword=keyword,
            limit=limit,
        )

    def get_payment(self, order_no: str) -> Payment | None:
        """查询支付记录。"""
        return self.orders.get_payment(self.get(order_no).order_id)

    def get_refund(self, order_no: str) -> Refund | None:
        """查询退款记录。"""
        return self.orders.get_refund(self.get(order_no).order_id)

    # ------------------------------------------------------------------
    # 下单
    # ------------------------------------------------------------------
    def place_order(
        self,
        session: Session,
        idempotency_key: str = "",
        address: str = "",
    ) -> tuple[Order, bool]:
        """从购物车生成订单。

        返回 ``(订单, 是否新建)``；重复提交同一幂等键时返回原订单，
        不会重复扣减库存。
        """
        require_role(session, UserRole.CUSTOMER)
        key = idempotency_key.strip() or uuid.uuid4().hex
        existing = self.orders.get_by_idempotency_key(session.user_id, key)
        if existing is not None:
            return existing, False
        cart = self.carts.load(session.user_id, now())
        if cart.is_empty:
            raise ValidationError("购物车为空，请先添加菜品")
        if len(cart.shop_ids) != 1:
            raise ValidationError("一个订单只能包含同一店铺的菜品")
        shop_id = next(iter(cart.shop_ids))
        shop = self.shops.get(shop_id)
        if shop is None:
            raise NotFoundError("店铺不存在")
        if not shop.can_order():
            raise ConflictError(f"店铺「{shop.name}」当前{shop.status}，无法下单")
        address = (address or self._customer_address(session)).strip()
        if not address:
            raise ValidationError("请先填写收货地址")

        created = False
        with self.db.transaction():
            existing = self.orders.get_by_idempotency_key(session.user_id, key)
            if existing is not None:
                return existing, False
            items: list[OrderItem] = []
            subtotal = Decimal("0.00")
            for item in cart.items:
                dish = self.dishes.get(item.dish_id)
                if dish is None:
                    raise NotFoundError(f"菜品「{item.dish_name}」已不存在")
                if dish.price != item.price_snapshot:
                    raise PriceChangedError(
                        dish.name, f"{item.price_snapshot:.2f}", f"{dish.price:.2f}"
                    )
                if not self.dishes.deduct_stock(dish.dish_id, item.quantity, now()):
                    raise SoldOutError(f"菜品「{dish.name}」库存不足或已售罄")
                items.append(
                    OrderItem.create(dish.dish_id, dish.name, dish.price, item.quantity)
                )
                subtotal += item.subtotal
            total = money(subtotal + config.DELIVERY_FEE)
            order_no = new_order_no()
            order_id = self.orders.create(
                order_no=order_no,
                customer_id=session.user_id,
                shop_id=shop_id,
                total_amount=total,
                delivery_fee=config.DELIVERY_FEE,
                address_snapshot=address,
                idempotency_key=key,
                moment=now(),
            )
            for item in items:
                item.order_id = order_id
                self.orders.add_item(order_id, item)
            self.carts.clear(cart.cart_id)
            self.logs.record(
                session,
                "提交订单",
                "订单",
                order_no,
                "",
                str(OrderStatus.PENDING_PAY),
                shop_id=shop_id,
            )
            self.notices.push(
                session.user_id,
                "订单已创建",
                f"订单 {order_no} 已创建，金额 {total:.2f} 元，请及时支付。",
            )
            self.notices.push(
                shop.merchant_id,
                "新订单提醒",
                f"收到新订单 {order_no}，金额 {total:.2f} 元。",
            )
            created = True
        order = self.get(order_no)
        return order, created

    def _customer_address(self, session: Session) -> str:
        user = self.db.query_one(
            "SELECT default_address FROM users WHERE user_id = ?", (session.user_id,)
        )
        return str(user["default_address"]) if user else ""

    # ------------------------------------------------------------------
    # 支付与顾客操作
    # ------------------------------------------------------------------
    def pay(self, session: Session, order_no: str) -> Payment:
        """模拟支付，金额与订单总额一致时成功。"""
        require_role(session, UserRole.CUSTOMER)
        order = self.get(order_no)
        if order.customer_id != session.user_id:
            raise PermissionDeniedError("只能支付自己的订单")
        if order.status != OrderStatus.PENDING_PAY:
            raise InvalidTransitionError(f"订单当前为「{order.status}」，无需支付")
        moment = now()
        with self.db.transaction():
            order.pay(moment)
            self.orders.update(order, moment)
            trade_no = new_trade_no()
            self.orders.create_payment(
                order.order_id, trade_no, order.total_amount, moment
            )
            self.logs.record(
                session,
                "模拟支付",
                "订单",
                order_no,
                str(OrderStatus.PENDING_PAY),
                str(OrderStatus.PAID),
                shop_id=order.shop_id,
            )
            self.notices.push(
                order.customer_id,
                "支付成功",
                f"订单 {order_no} 支付成功，金额 {order.total_amount:.2f} 元。",
            )
            shop = self.shops.get(order.shop_id)
            if shop is not None:
                self.notices.push(
                    shop.merchant_id,
                    "订单待接单",
                    f"订单 {order_no} 已支付，请在 {config.ACCEPT_TIMEOUT_MINUTES} 分钟内接单。",
                )
        payment = self.orders.get_payment(order.order_id)
        if payment is None:  # pragma: no cover - 刚写入必然存在
            raise NotFoundError("支付记录写入失败")
        return payment

    def cancel_by_customer(self, session: Session, order_no: str, reason: str = "") -> Order:
        """顾客取消：待支付直接取消；已支付且未接单则退款。"""
        require_role(session, UserRole.CUSTOMER)
        order = self.get(order_no)
        if order.customer_id != session.user_id:
            raise PermissionDeniedError("只能取消自己的订单")
        reason = reason.strip() or "顾客取消订单"
        with self.db.transaction():
            if order.status == OrderStatus.PENDING_PAY:
                before = str(order.status)
                order.cancel(reason)
                self._restore_stock(order)
                self.orders.update(order, now())
                self.logs.record(
                    session, "取消订单", "订单", order_no, before, str(order.status),
                    shop_id=order.shop_id,
                )
                shop = self.shops.get(order.shop_id)
                if shop is not None:
                    self.notices.push(
                        shop.merchant_id,
                        "订单已取消",
                        f"订单 {order_no} 已被顾客取消。",
                    )
            elif order.status == OrderStatus.PAID:
                self._refund_locked(order, reason, session)
            elif order.status == OrderStatus.COOKING:
                raise InvalidTransitionError(
                    "商家已接单，顾客不能直接取消，请联系商家或管理员处理"
                )
            else:
                raise InvalidTransitionError(f"订单当前为「{order.status}」，不能取消")
        return self.get(order_no)

    def confirm_received(self, session: Session, order_no: str) -> Order:
        """顾客确认收货。"""
        require_role(session, UserRole.CUSTOMER)
        order = self.get(order_no)
        if order.customer_id != session.user_id:
            raise PermissionDeniedError("只能确认自己的订单")
        moment = now()
        with self.db.transaction():
            before = str(order.status)
            order.complete()
            self.orders.update(order, moment)
            self.logs.record(
                session, "确认收货", "订单", order_no, before, str(order.status),
                shop_id=order.shop_id,
            )
        return self.get(order_no)

    # ------------------------------------------------------------------
    # 商家操作
    # ------------------------------------------------------------------
    def _merchant_order(self, session: Session, order_no: str) -> Order:
        require_role(session, UserRole.MERCHANT)
        order = self.get(order_no)
        require_shop(session, order.shop_id)
        return order

    def merchant_accept(self, session: Session, order_no: str) -> Order:
        """商家接单；若已超过 15 分钟则自动退款并拒绝接单。"""
        order = self._merchant_order(session, order_no)
        if order.status != OrderStatus.PAID:
            raise InvalidTransitionError(f"订单当前为「{order.status}」，不能接单")
        moment = now()
        timed_out = (
            order.pay_time is not None
            and moment - order.pay_time
            >= timedelta(minutes=config.ACCEPT_TIMEOUT_MINUTES)
        )
        with self.db.transaction():
            if timed_out:
                self._refund_locked(order, "超时未接单，系统自动退款", None)
            else:
                order.accept()
                self.orders.update(order, moment)
                self.logs.record(
                    session,
                    "商家接单",
                    "订单",
                    order_no,
                    str(OrderStatus.PAID),
                    str(OrderStatus.COOKING),
                    shop_id=order.shop_id,
                )
                self.notices.push(
                    order.customer_id,
                    "商家已接单",
                    f"订单 {order_no} 已由商家接单，正在制作中。",
                )
        if timed_out:
            raise ConflictError(
                f"订单已超过 {config.ACCEPT_TIMEOUT_MINUTES} 分钟未接单，已自动退款"
            )
        return self.get(order_no)

    def merchant_reject(self, session: Session, order_no: str, reason: str) -> Order:
        """商家拒单并全额退款。"""
        order = self._merchant_order(session, order_no)
        if order.status != OrderStatus.PAID:
            raise InvalidTransitionError(f"订单当前为「{order.status}」，不能拒单")
        if not reason.strip():
            raise ValidationError("拒单必须填写原因")
        with self.db.transaction():
            self._refund_locked(order, f"商家拒单：{reason.strip()}", session)
        return self.get(order_no)

    def finish_cook(self, session: Session, order_no: str) -> Order:
        """商家出餐，订单进入待配送。"""
        order = self._merchant_order(session, order_no)
        if order.status != OrderStatus.COOKING:
            raise InvalidTransitionError(f"订单当前为「{order.status}」，不能出餐")
        moment = now()
        with self.db.transaction():
            order.finish_cook()
            self.orders.update(order, moment)
            self.logs.record(
                session,
                "商家出餐",
                "订单",
                order_no,
                str(OrderStatus.COOKING),
                str(OrderStatus.PENDING_DELIVERY),
                shop_id=order.shop_id,
            )
            self.notices.push(
                order.customer_id,
                "餐品已出餐",
                f"订单 {order_no} 已出餐，等待配送员取餐。",
            )
        return self.get(order_no)

    # ------------------------------------------------------------------
    # 系统与管理员操作
    # ------------------------------------------------------------------
    def auto_cancel_unaccepted(self, order_no: str, moment: datetime | None = None) -> bool:
        """定时任务：已支付超过 15 分钟未接单则取消并退款。"""
        moment = moment or now()
        order = self.get(order_no)
        if order.status != OrderStatus.PAID or order.pay_time is None:
            return False
        if moment - order.pay_time < timedelta(minutes=config.ACCEPT_TIMEOUT_MINUTES):
            return False
        with self.db.transaction():
            self._refund_locked(order, "支付后超时未接单，系统自动退款", None)
        return True

    def auto_complete(self, order_no: str, moment: datetime | None = None) -> bool:
        """定时任务：送达超时后自动确认完成。"""
        moment = moment or now()
        order = self.get(order_no)
        if order.status != OrderStatus.DELIVERED:
            return False
        task = self.delivery_tasks.get_by_order(order.order_id)
        if task is None or task.delivered_at is None:
            return False
        if moment - task.delivered_at < timedelta(minutes=config.AUTO_CONFIRM_MINUTES):
            return False
        with self.db.transaction():
            order.complete()
            self.orders.update(order, moment)
            self.logs.record(
                None,
                "超时自动确认收货",
                "订单",
                order_no,
                str(OrderStatus.DELIVERED),
                str(OrderStatus.COMPLETED),
                shop_id=order.shop_id,
            )
            self.notices.push(
                order.customer_id,
                "订单已完成",
                f"订单 {order_no} 已超过 {config.AUTO_CONFIRM_MINUTES} 分钟未确认，系统自动完成。",
            )
        return True

    def admin_refund_exception(
        self, session: Session, order_no: str, reason: str
    ) -> Order:
        """管理员对配送失败订单裁定退款。"""
        require_role(session, UserRole.ADMIN)
        order = self.get(order_no)
        if order.status != OrderStatus.PENDING_HANDLE:
            raise InvalidTransitionError(f"订单当前为「{order.status}」，不是待处理订单")
        if not reason.strip():
            raise ValidationError("退款必须填写原因")
        with self.db.transaction():
            self._refund_locked(order, f"管理员处理：{reason.strip()}", session)
        return self.get(order_no)

    def admin_force_refund(self, session: Session, order_no: str, reason: str) -> Order:
        """管理员对已支付链路中的异常订单强制退款。"""
        require_role(session, UserRole.ADMIN)
        order = self.get(order_no)
        if order.status not in (
            OrderStatus.PAID,
            OrderStatus.COOKING,
            OrderStatus.PENDING_HANDLE,
        ):
            raise InvalidTransitionError(f"订单当前为「{order.status}」，不能退款")
        if not reason.strip():
            raise ValidationError("退款必须填写原因")
        with self.db.transaction():
            self._refund_locked(order, f"管理员退款：{reason.strip()}", session)
        return self.get(order_no)

    def _restore_stock(self, order: Order) -> None:
        """按订单明细回补库存。"""
        for item in order.items:
            self.dishes.restore_stock(item.dish_id, item.quantity, now())

    def _refund_locked(self, order: Order, reason: str, session: Session | None) -> None:
        """在事务内完成退款：更新状态、回补库存、写退款单、记日志、发通知。"""
        before = str(order.status)
        moment = now()
        order.refund(reason)
        self._restore_stock(order)
        self.orders.update(order, moment)
        self.orders.create_refund(
            order.order_id,
            new_refund_no(),
            order.total_amount,
            reason,
            moment,
        )
        self.logs.record(
            session,
            "订单退款",
            "订单",
            order.order_no,
            before,
            str(order.status),
            shop_id=order.shop_id,
        )
        self.notices.push(
            order.customer_id,
            "订单已退款",
            f"订单 {order.order_no} 已退款 {order.total_amount:.2f} 元，原因：{reason}。",
        )
        shop = self.shops.get(order.shop_id)
        if shop is not None:
            self.notices.push(
                shop.merchant_id,
                "订单退款通知",
                f"订单 {order.order_no} 已退款，原因：{reason}。",
            )
