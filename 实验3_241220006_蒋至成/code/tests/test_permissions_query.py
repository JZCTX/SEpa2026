"""权限、查询与统计测试。"""

# pylint: disable=missing-function-docstring

from takeout.enums import OrderStatus, UserRole
from takeout.errors import (
    PermissionDeniedError,
    ValidationError,
)
from tests.base import PASSWORD, ServiceTestCase


class PermissionAndQueryTest(ServiceTestCase):
    """REQ-002、REQ-005、REQ-011、REQ-012、REQ-016 的测试。"""

    def _create_second_merchant(self):
        self.auth.register_merchant(
            "13900000008", PASSWORD, "第二家店", "TEST-LIC-002"
        )
        pending = self.app.shop_service.list_pending(self.admin)
        self.app.shop_service.audit(
            self.admin, pending[0].shop_id, True, "第二家店审核通过"
        )
        return self.login("13900000008")

    def test_merchant_cannot_touch_other_shop(self) -> None:
        other_merchant = self._create_second_merchant()
        with self.assertRaises(PermissionDeniedError):
            self.app.dish_service.change_price(
                other_merchant, self.dish.dish_id, "1.00"
            )
        order = self.place_paid_order("perm-001", quantity=1)
        with self.assertRaises(PermissionDeniedError):
            self.app.order_service.merchant_accept(
                other_merchant, order.order_no
            )

    def test_customer_cannot_view_others_order(self) -> None:
        self.auth.register_customer("13900000007", PASSWORD, "另一个地址")
        other_customer = self.login("13900000007")
        order, _ = self.place_order("perm-002", quantity=1)
        with self.assertRaises(PermissionDeniedError):
            self.app.order_service.get_visible(other_customer, order.order_no)

    def test_courier_cannot_assign_or_query_logs(self) -> None:
        order = self.place_paid_order("perm-003", quantity=1)
        self.app.order_service.merchant_accept(self.merchant, order.order_no)
        self.app.order_service.finish_cook(self.merchant, order.order_no)
        with self.assertRaises(PermissionDeniedError):
            self.app.delivery_service.assign(
                self.courier, order.order_no, self.courier.user_id
            )
        with self.assertRaises(PermissionDeniedError):
            self.app.logs.query(self.courier)

    def test_merchant_only_sees_own_logs(self) -> None:
        self.place_paid_order("perm-004", quantity=1)
        logs = self.app.logs.query(self.merchant)
        self.assertTrue(logs)
        self.assertTrue(all(log.shop_id == self.shop.shop_id for log in logs))
        with self.assertRaises(PermissionDeniedError):
            self.app.logs.query(self.customer)

    def test_dish_search_conditions(self) -> None:
        self.app.dish_service.create(
            self.merchant, "鱼香肉丝", "热菜", "24.00", 10, publish=True
        )
        self.app.dish_service.create(
            self.merchant, "可乐", "饮料", "4.00", 30, publish=True
        )
        spicy = self.app.dish_service.create(
            self.merchant, "麻婆豆腐", "热菜", "16.00", 10
        )
        self.app.dish_service.publish(self.merchant, spicy.dish_id)
        self.app.dish_service.off_shelf(self.merchant, spicy.dish_id)

        names = {dish.name for dish in self.app.dish_service.search(keyword="鸡")}
        self.assertIn("宫保鸡丁", names)
        dishes = self.app.dish_service.search(category="热菜", min_price="20", max_price="30")
        prices = {dish.price for dish in dishes}
        self.assertIn("28.00", {str(price) for price in prices})
        self.assertIn("24.00", {str(price) for price in prices})
        self.assertNotIn("麻婆豆腐", {dish.name for dish in dishes})
        with self.assertRaises(ValidationError):
            self.app.dish_service.search(min_price="30", max_price="10")

    def test_closed_shop_hides_dishes(self) -> None:
        self.assertEqual(len(self.app.dish_service.search(keyword="宫保")), 1)
        self.app.shop_service.set_business(self.merchant, False)
        self.assertEqual(len(self.app.dish_service.search(keyword="宫保")), 0)
        self.app.shop_service.set_business(self.merchant, True)

    def test_order_filters(self) -> None:
        self.place_order("perm-005", quantity=1)
        self.place_paid_order("perm-006", quantity=1)
        pending = self.app.order_service.list_orders(
            self.customer, OrderStatus.PENDING_PAY
        )
        paid = self.app.order_service.list_orders(self.customer, OrderStatus.PAID)
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(paid), 1)
        by_keyword = self.app.order_service.list_orders(
            self.customer, keyword=pending[0].order_no
        )
        self.assertEqual(len(by_keyword), 1)

    def test_platform_stats(self) -> None:
        self._create_second_merchant()
        self.place_paid_order("perm-007", quantity=1)
        overview = self.app.stats_service.platform_overview(self.admin)
        self.assertGreaterEqual(overview["shop_count"], 2)
        self.assertEqual(overview["order_count"], 1)
        comparison = self.app.stats_service.shop_comparison(self.admin)
        self.assertTrue(comparison)
        with self.assertRaises(PermissionDeniedError):
            self.app.stats_service.platform_overview(self.customer)

    def test_role_enum_values(self) -> None:
        self.assertEqual(str(UserRole.CUSTOMER), "顾客")
