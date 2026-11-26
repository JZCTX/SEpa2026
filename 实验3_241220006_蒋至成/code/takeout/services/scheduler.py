"""超时扫描任务。

命令行程序在主循环中周期性调用 ``tick()``，效果等价于后台每分钟执行
一次的定时任务；测试可以直接传入时间参数模拟时间流逝。
"""

from datetime import datetime, timedelta

from takeout import config
from takeout.db import Database
from takeout.enums import OrderStatus
from takeout.repositories.delivery_repo import DeliveryRepository
from takeout.repositories.order_repo import OrderRepository
from takeout.services.log_service import LogService
from takeout.services.order_service import OrderService
from takeout.utils import now, today


class Scheduler:
    """扫描超时未接单、超时未确认的订单并自动处理。"""

    def __init__(
        self,
        db: Database,
        orders: OrderRepository,
        delivery_tasks: DeliveryRepository,
        order_service: OrderService,
        logs: LogService,
    ) -> None:
        self.db = db
        self.orders = orders
        self.delivery_tasks = delivery_tasks
        self.order_service = order_service
        self.logs = logs
        self._last_cleanup_date = None

    def tick(self, moment: datetime | None = None) -> dict[str, int]:
        """执行一次扫描，返回各类处理数量。"""
        moment = moment or now()
        cancelled = 0
        completed = 0
        for order in self.orders.list_by_status([OrderStatus.PAID]):
            if order.pay_time is None:
                continue
            if moment - order.pay_time >= timedelta(
                minutes=config.ACCEPT_TIMEOUT_MINUTES
            ):
                if self.order_service.auto_cancel_unaccepted(order.order_no, moment):
                    cancelled += 1
        for order in self.orders.list_by_status([OrderStatus.DELIVERED]):
            if self.order_service.auto_complete(order.order_no, moment):
                completed += 1
        cleaned = self._cleanup_logs_once()
        return {
            "timeout_cancelled": cancelled,
            "auto_completed": completed,
            "logs_cleaned": cleaned,
        }

    def _cleanup_logs_once(self) -> int:
        """每天最多清理一次过期日志。"""
        if self._last_cleanup_date == today():
            return 0
        self._last_cleanup_date = today()
        return self.logs.cleanup_expired()
