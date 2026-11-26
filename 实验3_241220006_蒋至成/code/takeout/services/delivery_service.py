"""配送服务：分配、取餐、送达、失败上报与重新配送。"""

from takeout import config
from takeout.db import Database
from takeout.domain.delivery import DeliveryTask
from takeout.enums import DeliveryStatus, OrderStatus, UserRole
from takeout.errors import ConflictError, InvalidTransitionError, NotFoundError
from takeout.repositories.delivery_repo import DeliveryRepository
from takeout.repositories.order_repo import OrderRepository
from takeout.repositories.shop_repo import ShopRepository
from takeout.repositories.user_repo import UserRepository
from takeout.security import Session
from takeout.services.base import require_role, require_shop
from takeout.services.log_service import LogService
from takeout.services.notice_service import NoticeService
from takeout.services.order_service import OrderService
from takeout.utils import now


class DeliveryService:
    """配送履约，对应 REQ-009 和状态图中的待处理分支。"""

    def __init__(
        self,
        db: Database,
        tasks: DeliveryRepository,
        orders: OrderRepository,
        shops: ShopRepository,
        users: UserRepository,
        order_service: OrderService,
        logs: LogService,
        notices: NoticeService,
    ) -> None:
        self.db = db
        self.tasks = tasks
        self.orders = orders
        self.shops = shops
        self.users = users
        self.order_service = order_service
        self.logs = logs
        self.notices = notices

    def get_task(self, task_id: int) -> DeliveryTask:
        """按编号取得配送单。"""
        task = self.tasks.get(task_id)
        if task is None:
            raise NotFoundError("配送单不存在")
        return task

    def _courier_task(self, session: Session, task_id: int) -> DeliveryTask:
        require_role(session, UserRole.COURIER)
        task = self.get_task(task_id)
        if task.courier_id != session.user_id:
            raise InvalidTransitionError("只能操作分配给自己的配送单")
        return task

    def _verify_courier(self, courier_id: int) -> None:
        courier = self.users.get_by_id(courier_id)
        if courier is None or courier.role != UserRole.COURIER:
            raise NotFoundError("配送员不存在")
        if courier.work_status != "空闲":
            raise ConflictError("该配送员当前忙碌，请选择其他配送员")
        if self.tasks.count_active_by_courier(courier_id) > 0:
            raise ConflictError("该配送员仍有未完成的配送单")

    def assign(self, session: Session, order_no: str, courier_id: int) -> DeliveryTask:
        """商家为待配送订单分配配送员。"""
        require_role(session, UserRole.MERCHANT)
        order = self.order_service.get(order_no)
        require_shop(session, order.shop_id)
        if order.status != OrderStatus.PENDING_DELIVERY:
            raise InvalidTransitionError(
                f"订单当前为「{order.status}」，只有待配送订单可以分配"
            )
        if self.tasks.get_by_order(order.order_id) is not None:
            raise ConflictError("该订单已存在配送单，请勿重复分配")
        self._verify_courier(courier_id)
        moment = now()
        with self.db.transaction():
            task_id = self.tasks.create(
                order.order_id, courier_id, DeliveryStatus.PENDING_PICKUP, moment
            )
            order.start_delivery()
            self.orders.update(order, moment)
            self.users.update_work_status(courier_id, "配送中")
            self.logs.record(
                session,
                "分配配送员",
                "订单",
                order_no,
                str(OrderStatus.PENDING_DELIVERY),
                str(OrderStatus.DELIVERING),
                shop_id=order.shop_id,
            )
            self.notices.push(
                courier_id,
                "新配送任务",
                f"订单 {order_no} 已分配给你，请尽快到店取餐。",
            )
            self.notices.push(
                order.customer_id,
                "骑手已接单",
                f"订单 {order_no} 已分配配送员，正在前往取餐。",
            )
        return self.get_task(task_id)

    def list_my_tasks(self, session: Session) -> list[DeliveryTask]:
        """配送员查看自己的配送单。"""
        require_role(session, UserRole.COURIER)
        return self.tasks.list_by_courier(session.user_id)

    def pickup(self, session: Session, task_id: int) -> DeliveryTask:
        """配送员取餐。"""
        task = self._courier_task(session, task_id)
        if task.status != DeliveryStatus.PENDING_PICKUP:
            raise InvalidTransitionError(f"配送单当前为「{task.status}」，不能取餐")
        moment = now()
        with self.db.transaction():
            task.pickup(moment)
            self.tasks.update(task)
            order = self.order_service.get_by_id(task.order_id)
            self.logs.record(
                session,
                "配送员取餐",
                "配送单",
                str(task_id),
                str(DeliveryStatus.PENDING_PICKUP),
                str(DeliveryStatus.DELIVERING),
                shop_id=order.shop_id,
            )
            self.notices.push(
                order.customer_id,
                "骑手已取餐",
                f"订单 {order.order_no} 已取餐，正在配送中。",
            )
        return self.get_task(task_id)

    def delivered(self, session: Session, task_id: int) -> DeliveryTask:
        """配送员确认送达。"""
        task = self._courier_task(session, task_id)
        if task.status != DeliveryStatus.DELIVERING:
            raise InvalidTransitionError(f"配送单当前为「{task.status}」，不能确认送达")
        moment = now()
        with self.db.transaction():
            task.confirm_delivered(moment)
            self.tasks.update(task)
            order = self.order_service.get_by_id(task.order_id)
            order.mark_delivered()
            self.orders.update(order, moment)
            self.users.update_work_status(session.user_id, "空闲")
            self.logs.record(
                session,
                "确认送达",
                "订单",
                order.order_no,
                str(OrderStatus.DELIVERING),
                str(OrderStatus.DELIVERED),
                shop_id=order.shop_id,
            )
            self.notices.push(
                order.customer_id,
                "餐品已送达",
                f"订单 {order.order_no} 已送达，请确认收货。",
            )
        return self.get_task(task_id)

    def report_fail(self, session: Session, task_id: int, reason: str) -> DeliveryTask:
        """配送员上报失败，订单进入待处理。"""
        task = self._courier_task(session, task_id)
        if task.status not in (
            DeliveryStatus.PENDING_PICKUP,
            DeliveryStatus.DELIVERING,
        ):
            raise InvalidTransitionError(f"配送单当前为「{task.status}」，不能上报失败")
        if not reason.strip():
            raise ConflictError("上报配送失败必须填写原因")
        moment = now()
        with self.db.transaction():
            task.report_fail(reason.strip())
            self.tasks.update(task)
            order = self.order_service.get_by_id(task.order_id)
            order.report_failed(reason.strip())
            self.orders.update(order, moment)
            self.users.update_work_status(session.user_id, "空闲")
            self.logs.record(
                session,
                "上报配送失败",
                "订单",
                order.order_no,
                str(OrderStatus.DELIVERING),
                str(OrderStatus.PENDING_HANDLE),
                shop_id=order.shop_id,
            )
            self.notices.push(
                order.customer_id,
                "配送异常",
                f"订单 {order.order_no} 配送失败，平台正在处理，原因：{reason}。",
            )
            shop = self.shops.get(order.shop_id)
            if shop is not None:
                self.notices.push(
                    shop.merchant_id,
                    "配送异常提醒",
                    f"订单 {order.order_no} 配送失败，等待平台处理。",
                )
            for admin in self.users.list_users(UserRole.ADMIN):
                self.notices.push(
                    admin.user_id,
                    "待处理异常订单",
                    f"订单 {order.order_no} 配送失败，请在 "
                    f"{config.PENDING_HANDLE_MINUTES} 分钟内裁定重新配送或退款。",
                )
        return self.get_task(task_id)

    def admin_reassign(
        self, session: Session, order_no: str, courier_id: int
    ) -> DeliveryTask:
        """管理员协调重新配送。"""
        require_role(session, UserRole.ADMIN)
        order = self.order_service.get(order_no)
        if order.status != OrderStatus.PENDING_HANDLE:
            raise InvalidTransitionError(
                f"订单当前为「{order.status}」，不是待处理订单"
            )
        task = self.tasks.get_by_order(order.order_id)
        if task is None:
            raise NotFoundError("该订单没有配送单")
        if task.status != DeliveryStatus.FAILED:
            raise InvalidTransitionError("只有配送失败的配送单可以重新分配")
        self._verify_courier(courier_id)
        moment = now()
        with self.db.transaction():
            task.redispatch(courier_id, moment)
            self.tasks.update(task)
            order.start_delivery()
            self.orders.update(order, moment)
            self.users.update_work_status(courier_id, "配送中")
            self.logs.record(
                session,
                "异常订单重新配送",
                "订单",
                order_no,
                str(OrderStatus.PENDING_HANDLE),
                str(OrderStatus.DELIVERING),
                shop_id=order.shop_id,
            )
            self.notices.push(
                courier_id,
                "重新配送任务",
                f"订单 {order_no} 已重新分配给你，请尽快取餐。",
            )
            self.notices.push(
                order.customer_id,
                "平台已重新安排配送",
                f"订单 {order_no} 已重新分配配送员。",
            )
        return self.get_task(task.task_id)

    def available_couriers(self) -> list[int]:
        """返回可分配的配送员编号。"""
        result = []
        for user in self.users.list_users(UserRole.COURIER):
            if user.work_status == "空闲" and self.tasks.count_active_by_courier(
                user.user_id
            ) == 0:
                result.append(user.user_id)
        return result

    def set_work_status(self, session: Session, status: str) -> None:
        """配送员切换空闲/忙碌。"""
        require_role(session, UserRole.COURIER)
        if status not in ("空闲", "忙碌"):
            raise InvalidTransitionError("工作状态只能是空闲或忙碌")
        self.users.update_work_status(session.user_id, status)
        self.logs.record(session, "切换工作状态", "用户", str(session.user_id), "", status)
