"""单元测试公共夹具：临时数据库与四类基础账号。"""

import tempfile
import unittest
from pathlib import Path

from takeout.container import Container

ADMIN_PHONE = "13900000000"
MERCHANT_PHONE = "13900000002"
CUSTOMER_PHONE = "13900000001"
COURIER_PHONE = "13900000003"
PASSWORD = "123456"


class ServiceTestCase(unittest.TestCase):
    """为每个测试创建独立的 SQLite 数据库和基础数据。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.app = Container(self.db_path)
        self.auth = self.app.auth
        self.auth.register_admin(ADMIN_PHONE, PASSWORD)
        self.auth.register_customer(CUSTOMER_PHONE, PASSWORD, "测试地址 1 号")
        self.auth.register_merchant(
            MERCHANT_PHONE, PASSWORD, "测试餐厅", "TEST-LIC-001"
        )
        self.auth.register_courier(COURIER_PHONE, PASSWORD)

        self.admin = self.login(ADMIN_PHONE)
        pending = self.app.shop_service.list_pending(self.admin)
        self.app.shop_service.audit(
            self.admin, pending[0].shop_id, True, "测试审核通过"
        )
        self.merchant = self.login(MERCHANT_PHONE)
        self.shop = self.app.shop_service.get_my_shop(self.merchant)
        self.customer = self.login(CUSTOMER_PHONE)
        self.courier = self.login(COURIER_PHONE)

        self.dish = self.app.dish_service.create(
            self.merchant, "宫保鸡丁", "热菜", "28.00", 20, publish=True
        )
        self.rice = self.app.dish_service.create(
            self.merchant, "米饭", "主食", "2.00", 100, publish=True
        )

    def tearDown(self) -> None:
        self.app.close()
        self._tmp.cleanup()

    def login(self, phone: str, password: str = PASSWORD):
        """登录并返回会话。"""
        return self.auth.login(phone, password).session

    def place_order(self, key: str, dish=None, quantity: int = 1):
        """把菜品加入购物车并下单。"""
        dish = dish or self.dish
        self.app.cart_service.add(self.customer, dish.dish_id, quantity)
        return self.app.order_service.place_order(self.customer, key)

    def place_paid_order(self, key: str, dish=None, quantity: int = 1):
        """下单并支付。"""
        order, _ = self.place_order(key, dish, quantity)
        self.app.order_service.pay(self.customer, order.order_no)
        return self.app.order_service.get(order.order_no)

    def advance_to_delivering(self, key: str, dish=None, quantity: int = 1):
        """推进订单到配送中，返回订单与配送单。"""
        order = self.place_paid_order(key, dish, quantity)
        self.app.order_service.merchant_accept(self.merchant, order.order_no)
        self.app.order_service.finish_cook(self.merchant, order.order_no)
        task = self.app.delivery_service.assign(
            self.merchant, order.order_no, self.courier.user_id
        )
        return self.app.order_service.get(order.order_no), task
