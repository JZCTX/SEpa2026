"""库存扣减、并发抢购与幂等测试。"""

# pylint: disable=missing-function-docstring

from takeout.enums import OrderStatus
from takeout.errors import SoldOutError
from takeout.utils import now
from tests.base import PASSWORD, ServiceTestCase


class InventoryTest(ServiceTestCase):
    """REQ-014 售罄与超卖防护测试。"""

    def test_only_one_customer_gets_last_stock(self) -> None:
        self.app.dish_service.set_stock(self.merchant, self.dish.dish_id, 1)
        self.auth.register_customer("13900000009", PASSWORD, "另一个地址")
        other = self.login("13900000009")
        self.app.cart_service.add(self.customer, self.dish.dish_id, 1)
        self.app.cart_service.add(other, self.dish.dish_id, 1)

        order, _ = self.app.order_service.place_order(self.customer, "stock-001")
        self.assertEqual(order.status, OrderStatus.PENDING_PAY)
        with self.assertRaises(SoldOutError):
            self.app.order_service.place_order(other, "stock-002")
        dish = self.app.dishes.get(self.dish.dish_id)
        self.assertEqual(dish.stock, 0)
        self.assertEqual(str(dish.status), "售罄")

        self.app.order_service.cancel_by_customer(
            self.customer, order.order_no, "释放库存"
        )
        dish = self.app.dishes.get(self.dish.dish_id)
        self.assertEqual(dish.stock, 1)
        self.assertEqual(str(dish.status), "在售")

    def test_atomic_deduct_never_negative(self) -> None:
        self.app.dish_service.set_stock(self.merchant, self.dish.dish_id, 5)
        moment = now()
        self.assertTrue(
            self.app.dishes.deduct_stock(self.dish.dish_id, 3, moment)
        )
        self.assertFalse(
            self.app.dishes.deduct_stock(self.dish.dish_id, 3, moment)
        )
        dish = self.app.dishes.get(self.dish.dish_id)
        self.assertEqual(dish.stock, 2)
        self.assertGreaterEqual(dish.version, 1)

    def test_restore_stock_recovers_sold_out_status(self) -> None:
        self.app.dish_service.set_stock(self.merchant, self.dish.dish_id, 1)
        order, _ = self.place_order("stock-003", quantity=1)
        self.assertEqual(str(self.app.dishes.get(self.dish.dish_id).status), "售罄")
        self.app.order_service.cancel_by_customer(
            self.customer, order.order_no, "取消"
        )
        self.assertEqual(self.app.dishes.get(self.dish.dish_id).stock, 1)
        self.assertEqual(str(self.app.dishes.get(self.dish.dish_id).status), "在售")

    def test_repeated_request_deducts_once(self) -> None:
        before = self.app.dishes.get(self.dish.dish_id).stock
        order, _ = self.place_order("stock-004", quantity=2)
        self.app.order_service.place_order(self.customer, "stock-004")
        self.app.order_service.place_order(self.customer, "stock-004")
        self.assertEqual(
            self.app.dishes.get(self.dish.dish_id).stock, before - 2
        )
        self.assertEqual(order.items[0].quantity, 2)
