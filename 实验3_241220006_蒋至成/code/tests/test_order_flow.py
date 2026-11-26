"""订单主流程与状态机测试。"""

# pylint: disable=missing-function-docstring

from decimal import Decimal

from takeout.enums import OrderStatus
from takeout.errors import InvalidTransitionError, SoldOutError
from takeout.utils import now
from tests.base import ServiceTestCase


class OrderFlowTest(ServiceTestCase):
    """REQ-006、REQ-007、REQ-008、REQ-010 的测试。"""

    def test_place_order_deducts_stock_and_snapshots_price(self) -> None:
        before = self.app.dishes.get(self.dish.dish_id).stock
        order, created = self.place_order("flow-001", quantity=2)
        self.assertTrue(created)
        self.assertEqual(order.status, OrderStatus.PENDING_PAY)
        self.assertEqual(order.total_amount, Decimal("59.00"))
        self.assertEqual(order.delivery_fee, Decimal("3.00"))
        self.assertEqual(self.app.dishes.get(self.dish.dish_id).stock, before - 2)
        self.assertEqual(order.items[0].unit_price_snapshot, Decimal("28.00"))
        cart = self.app.cart_service.load(self.customer)
        self.assertTrue(cart.is_empty)

    def test_duplicate_submission_returns_same_order(self) -> None:
        order, _ = self.place_order("flow-002", quantity=1)
        stock = self.app.dishes.get(self.dish.dish_id).stock
        again, created = self.app.order_service.place_order(
            self.customer, "flow-002"
        )
        self.assertFalse(created)
        self.assertEqual(again.order_no, order.order_no)
        self.assertEqual(self.app.dishes.get(self.dish.dish_id).stock, stock)
        orders = self.app.order_service.list_orders(self.customer)
        self.assertEqual(len(orders), 1)

    def test_full_happy_path(self) -> None:
        order = self.place_paid_order("flow-003", quantity=1)
        self.assertEqual(order.status, OrderStatus.PAID)
        payment = self.app.order_service.get_payment(order.order_no)
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, "成功")

        self.app.order_service.merchant_accept(self.merchant, order.order_no)
        self.assertEqual(
            self.app.order_service.get(order.order_no).status, OrderStatus.COOKING
        )
        self.app.order_service.finish_cook(self.merchant, order.order_no)
        self.assertEqual(
            self.app.order_service.get(order.order_no).status,
            OrderStatus.PENDING_DELIVERY,
        )
        task = self.app.delivery_service.assign(
            self.merchant, order.order_no, self.courier.user_id
        )
        self.assertEqual(
            self.app.order_service.get(order.order_no).status, OrderStatus.DELIVERING
        )
        self.app.delivery_service.pickup(self.courier, task.task_id)
        self.app.delivery_service.delivered(self.courier, task.task_id)
        self.assertEqual(
            self.app.order_service.get(order.order_no).status, OrderStatus.DELIVERED
        )
        done = self.app.order_service.confirm_received(self.customer, order.order_no)
        self.assertEqual(done.status, OrderStatus.COMPLETED)
        report = self.app.stats_service.merchant_daily(self.merchant)
        self.assertEqual(report.order_count, 1)
        self.assertEqual(report.gmv, Decimal("31.00"))

    def test_cancel_unpaid_restores_stock(self) -> None:
        before = self.app.dishes.get(self.dish.dish_id).stock
        order, _ = self.place_order("flow-004", quantity=3)
        self.assertEqual(self.app.dishes.get(self.dish.dish_id).stock, before - 3)
        cancelled = self.app.order_service.cancel_by_customer(
            self.customer, order.order_no, "不需要了"
        )
        self.assertEqual(cancelled.status, OrderStatus.CANCELLED)
        self.assertEqual(self.app.dishes.get(self.dish.dish_id).stock, before)
        self.assertIsNone(self.app.order_service.get_refund(order.order_no))

    def test_cancel_paid_order_refunds(self) -> None:
        order = self.place_paid_order("flow-005", quantity=2)
        before = self.app.dishes.get(self.dish.dish_id).stock
        refunded = self.app.order_service.cancel_by_customer(
            self.customer, order.order_no, "临时有事"
        )
        self.assertEqual(refunded.status, OrderStatus.REFUNDED)
        refund = self.app.order_service.get_refund(order.order_no)
        self.assertIsNotNone(refund)
        self.assertEqual(refund.amount, order.total_amount)
        self.assertEqual(self.app.dishes.get(self.dish.dish_id).stock, before + 2)

    def test_merchant_reject_refunds(self) -> None:
        order = self.place_paid_order("flow-006", quantity=1)
        rejected = self.app.order_service.merchant_reject(
            self.merchant, order.order_no, "原料不足"
        )
        self.assertEqual(rejected.status, OrderStatus.REFUNDED)
        self.assertIn("原料不足", rejected.cancel_reason)

    def test_forbidden_transitions(self) -> None:
        order, _ = self.place_order("flow-007", quantity=1)
        with self.assertRaises(InvalidTransitionError):
            self.app.order_service.merchant_accept(self.merchant, order.order_no)
        self.app.order_service.pay(self.customer, order.order_no)
        self.app.order_service.merchant_accept(self.merchant, order.order_no)
        with self.assertRaises(InvalidTransitionError):
            self.app.order_service.cancel_by_customer(
                self.customer, order.order_no, "接单后取消"
            )
        with self.assertRaises(InvalidTransitionError):
            self.app.order_service.confirm_received(self.customer, order.order_no)

    def test_price_change_does_not_affect_existing_order(self) -> None:
        order, _ = self.place_order("flow-008", quantity=1)
        self.app.dish_service.change_price(
            self.merchant, self.dish.dish_id, "30.00"
        )
        unchanged = self.app.order_service.get(order.order_no)
        self.assertEqual(unchanged.items[0].unit_price_snapshot, Decimal("28.00"))
        self.assertEqual(unchanged.total_amount, Decimal("31.00"))
        new_order, _ = self.place_order("flow-009", quantity=1)
        self.assertEqual(new_order.items[0].unit_price_snapshot, Decimal("30.00"))
        self.assertEqual(new_order.total_amount, Decimal("33.00"))

    def test_sold_out_cannot_be_added_to_cart(self) -> None:
        self.app.dish_service.set_stock(self.merchant, self.rice.dish_id, 0)
        self.assertEqual(str(self.app.dishes.get(self.rice.dish_id).status), "售罄")
        with self.assertRaises(SoldOutError):
            self.app.cart_service.add(self.customer, self.rice.dish_id, 1)

    def test_order_time_is_recorded(self) -> None:
        order = self.place_paid_order("flow-010", quantity=1)
        self.assertIsNotNone(order.created_at)
        self.assertIsNotNone(order.pay_time)
        self.assertLessEqual(order.created_at, now())
