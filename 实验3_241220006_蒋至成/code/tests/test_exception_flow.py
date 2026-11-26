"""配送异常、管理员处置与超时任务测试。"""

# pylint: disable=missing-function-docstring

from datetime import timedelta

from takeout.enums import DeliveryStatus, OrderStatus
from takeout.errors import InvalidTransitionError
from takeout.utils import now
from tests.base import ServiceTestCase


class ExceptionFlowTest(ServiceTestCase):
    """REQ-009、REQ-010 与状态图待处理分支的测试。"""

    def test_delivery_failure_goes_to_pending_handle(self) -> None:
        order, task = self.advance_to_delivering("exc-001", quantity=1)
        self.app.delivery_service.pickup(self.courier, task.task_id)
        failed = self.app.delivery_service.report_fail(
            self.courier, task.task_id, "联系不上顾客"
        )
        self.assertEqual(failed.status, DeliveryStatus.FAILED)
        current = self.app.order_service.get(order.order_no)
        self.assertEqual(current.status, OrderStatus.PENDING_HANDLE)
        courier = self.app.users.get_by_id(self.courier.user_id)
        self.assertEqual(courier.work_status, "空闲")

    def test_admin_can_redispatch_then_refund(self) -> None:
        order, task = self.advance_to_delivering("exc-002", quantity=2)
        self.app.delivery_service.pickup(self.courier, task.task_id)
        self.app.delivery_service.report_fail(self.courier, task.task_id, "车辆故障")
        reassigned = self.app.delivery_service.admin_reassign(
            self.admin, order.order_no, self.courier.user_id
        )
        self.assertEqual(reassigned.status, DeliveryStatus.PENDING_PICKUP)
        self.assertEqual(
            self.app.order_service.get(order.order_no).status, OrderStatus.DELIVERING
        )
        self.app.delivery_service.pickup(self.courier, task.task_id)
        self.app.delivery_service.report_fail(
            self.courier, task.task_id, "再次失败"
        )
        stock_before_refund = self.app.dishes.get(self.dish.dish_id).stock
        refunded = self.app.order_service.admin_refund_exception(
            self.admin, order.order_no, "配送失败，同意退款"
        )
        self.assertEqual(refunded.status, OrderStatus.REFUNDED)
        self.assertEqual(
            self.app.dishes.get(self.dish.dish_id).stock, stock_before_refund + 2
        )
        self.assertIsNotNone(self.app.order_service.get_refund(order.order_no))

    def test_completed_order_cannot_be_refunded(self) -> None:
        order, task = self.advance_to_delivering("exc-003", quantity=1)
        self.app.delivery_service.pickup(self.courier, task.task_id)
        self.app.delivery_service.delivered(self.courier, task.task_id)
        self.app.order_service.confirm_received(self.customer, order.order_no)
        with self.assertRaises(InvalidTransitionError):
            self.app.order_service.admin_force_refund(
                self.admin, order.order_no, "测试"
            )

    def test_admin_reassign_requires_pending_handle(self) -> None:
        order, _ = self.advance_to_delivering("exc-004", quantity=1)
        with self.assertRaises(InvalidTransitionError):
            self.app.delivery_service.admin_reassign(
                self.admin, order.order_no, self.courier.user_id
            )

    def test_timeout_unaccepted_order_auto_refunded(self) -> None:
        order = self.place_paid_order("exc-005", quantity=1)
        future = now() + timedelta(minutes=16)
        result = self.app.scheduler.tick(future)
        self.assertEqual(result["timeout_cancelled"], 1)
        current = self.app.order_service.get(order.order_no)
        self.assertEqual(current.status, OrderStatus.REFUNDED)
        refund = self.app.order_service.get_refund(order.order_no)
        self.assertIn("超时", refund.reason)

    def test_timeout_order_accept_is_refused(self) -> None:
        order = self.place_paid_order("exc-006", quantity=1)
        self.app.orders.update(order, now())  # 保持数据一致
        future = now() + timedelta(minutes=16)
        result = self.app.scheduler.tick(future)
        self.assertEqual(result["timeout_cancelled"], 1)
        with self.assertRaises(InvalidTransitionError):
            self.app.order_service.merchant_accept(self.merchant, order.order_no)

    def test_auto_confirm_after_delivery_timeout(self) -> None:
        order, task = self.advance_to_delivering("exc-007", quantity=1)
        self.app.delivery_service.pickup(self.courier, task.task_id)
        self.app.delivery_service.delivered(self.courier, task.task_id)
        future = now() + timedelta(minutes=31)
        result = self.app.scheduler.tick(future)
        self.assertEqual(result["auto_completed"], 1)
        self.assertEqual(
            self.app.order_service.get(order.order_no).status, OrderStatus.COMPLETED
        )
