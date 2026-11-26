"""顾客菜单。"""

import uuid

from takeout import config
from takeout.cli import console, helpers
from takeout.domain.cart import Cart
from takeout.errors import AppError, PriceChangedError, ValidationError
from takeout.utils import format_time


class CustomerMenu:
    """顾客端：浏览、购物车、下单、支付、订单与通知。"""

    def __init__(self, app, session) -> None:
        self.app = app
        self.session = session
        self.services = app.container

    def run(self) -> None:
        """顾客主菜单循环。"""
        while True:
            choice = console.show_menu(
                f"顾客菜单（{self.session.phone}）",
                [
                    "浏览与搜索菜品",
                    "购物车",
                    "提交订单",
                    "我的订单",
                    "模拟支付",
                    "取消订单",
                    "确认收货",
                    "消息通知",
                    "修改默认收货地址",
                ],
            )
            if choice == 0:
                return
            try:
                self._handle(choice)
            except AppError as exc:
                console.error(exc.message)
            console.pause()

    def _handle(self, choice: int) -> None:
        actions = {
            1: self._browse,
            2: self._cart,
            3: self._checkout,
            4: self._orders,
            5: self._pay,
            6: self._cancel,
            7: self._confirm,
            8: self._notices,
            9: self._address,
        }
        actions[choice]()

    # ------------------------------------------------------------------
    # 菜品浏览
    # ------------------------------------------------------------------
    def _browse(self) -> None:
        keyword = console.read_text("关键词（菜品名/分类，可留空）")
        category = console.read_text("分类（可留空）")
        low = console.read_text("最低价（可留空）")
        high = console.read_text("最高价（可留空）")
        try:
            dishes = self.services.dish_service.search(
                keyword, category, low, high
            )
        except ValidationError as exc:
            console.warning(f"{exc.message}，已忽略价格区间条件")
            dishes = self.services.dish_service.search(keyword, category)
        names = helpers.shop_name_map(self.app)
        rows = [
            [
                dish.dish_id,
                dish.name,
                dish.category,
                f"{dish.price:.2f}",
                dish.stock,
                dish.status,
                names.get(dish.shop_id, dish.shop_id),
            ]
            for dish in dishes
        ]
        console.print_table(
            ["编号", "菜品", "分类", "价格", "库存", "状态", "店铺"],
            rows,
            aligns=["right", "left", "left", "right", "right", "left", "left"],
        )
        raw = console.read_text("输入菜品编号加入购物车（留空返回）")
        if not raw:
            return
        dish_id = int(raw)
        quantity = console.read_int("购买数量", minimum=1, default=1)
        cart = self.services.cart_service.add(self.session, dish_id, quantity)
        console.success(f"已加入购物车，当前共 {sum(i.quantity for i in cart.items)} 件")

    # ------------------------------------------------------------------
    # 购物车
    # ------------------------------------------------------------------
    def _show_cart(self, cart: Cart) -> None:
        rows = [
            [
                item.dish_id,
                item.dish_name,
                f"{item.unit_price:.2f}",
                item.quantity,
                f"{item.subtotal:.2f}",
                item.dish_status,
                "是" if item.price_changed else "否",
            ]
            for item in cart.items
        ]
        console.print_table(
            ["编号", "菜品", "单价", "数量", "小计", "状态", "已改价"],
            rows,
            aligns=["right", "left", "right", "right", "right", "left", "center"],
        )
        console.info(
            f"商品合计 {cart.total:.2f} 元，配送费 {config.DELIVERY_FEE:.2f} 元，"
            f"应付 {cart.total + config.DELIVERY_FEE:.2f} 元"
        )
        if any(item.price_changed for item in cart.items):
            console.warning("部分菜品价格已变化，下单时会提示刷新")

    def _cart(self) -> None:
        while True:
            cart = self.services.cart_service.load(self.session)
            if cart.is_empty:
                console.info("购物车为空")
                return
            self._show_cart(cart)
            choice = console.show_menu("购物车操作", ["移除菜品", "清空购物车"])
            if choice == 0:
                return
            try:
                if choice == 1:
                    dish_id = console.read_int("菜品编号", minimum=1)
                    self.services.cart_service.remove(self.session, dish_id)
                    console.success("已移除")
                elif choice == 2 and console.confirm("确认清空购物车？"):
                    self.services.cart_service.clear(self.session)
                    console.success("购物车已清空")
            except AppError as exc:
                console.error(exc.message)
            console.pause()

    # ------------------------------------------------------------------
    # 下单
    # ------------------------------------------------------------------
    def _checkout(self) -> None:
        summary = self.services.cart_service.summary(self.session)
        cart: Cart = summary["cart"]
        if cart.is_empty:
            console.info("购物车为空，请先添加菜品")
            return
        if summary["unavailable"]:
            console.warning(
                "以下菜品当前不可购买，请先移除：" + "、".join(summary["unavailable"])
            )
            return
        self._show_cart(cart)
        user = self.services.auth.get_user(self.session.user_id)
        address = console.read_text("收货地址", default=user.default_address)
        if not address:
            console.error("收货地址不能为空")
            return
        key = uuid.uuid4().hex
        console.info(f"本次请求幂等键：{key}")
        try:
            order, created = self.services.order_service.place_order(
                self.session, key, address
            )
        except PriceChangedError as exc:
            console.warning(exc.message)
            if not console.confirm("是否按最新价格刷新购物车并重新提交？"):
                return
            changed = self.services.cart_service.refresh_prices(self.session)
            console.info(f"已刷新 {changed} 条价格，正在重新提交")
            order, created = self.services.order_service.place_order(
                self.session, key, address
            )
        helpers.print_order_detail(self.app, order)
        if created:
            console.success(f"订单创建成功，订单号 {order.order_no}")
        else:
            console.warning("检测到重复提交，已返回原订单，未重复扣减库存")
        if console.confirm("是否立即模拟支付？", default=True):
            payment = self.services.order_service.pay(self.session, order.order_no)
            console.success(
                f"支付成功，流水号 {payment.trade_no}，金额 {payment.amount:.2f} 元"
            )

    # ------------------------------------------------------------------
    # 订单查询与操作
    # ------------------------------------------------------------------
    def _orders(self) -> None:
        status = helpers.choose_status()
        keyword = console.read_text("关键词（订单号/地址，可留空）")
        date_from = helpers.read_optional_date("开始日期")
        date_to = helpers.read_optional_date("结束日期")
        orders = self.services.order_service.list_orders(
            self.session, status, date_from, date_to, keyword
        )
        helpers.print_order_table(self.app, orders)
        order_no = console.read_text("输入订单号查看详情（留空返回）")
        if order_no:
            order = self.services.order_service.get_visible(self.session, order_no)
            helpers.print_order_detail(self.app, order)

    def _pay(self) -> None:
        order_no = console.read_text("订单号")
        payment = self.services.order_service.pay(self.session, order_no)
        console.success(
            f"支付成功，流水号 {payment.trade_no}，金额 {payment.amount:.2f} 元，"
            f"时间 {format_time(payment.paid_at)}"
        )

    def _cancel(self) -> None:
        order_no = console.read_text("订单号")
        order = self.services.order_service.get_visible(self.session, order_no)
        console.info(f"订单当前状态：{order.status}，金额 {order.total_amount:.2f} 元")
        if not console.confirm("确认取消该订单？"):
            return
        reason = console.read_text("取消原因", default="顾客取消订单")
        order = self.services.order_service.cancel_by_customer(
            self.session, order_no, reason
        )
        console.success(f"订单已处理，当前状态：{order.status}")
        if order.status.value == "已退款":
            console.info(f"已退款 {order.total_amount:.2f} 元，库存已回补")

    def _confirm(self) -> None:
        order_no = console.read_text("订单号")
        order = self.services.order_service.confirm_received(self.session, order_no)
        console.success(f"已确认收货，订单状态：{order.status}")

    # ------------------------------------------------------------------
    # 通知与地址
    # ------------------------------------------------------------------
    def _notices(self) -> None:
        notices = self.services.notices.list_mine(self.session)
        rows = [
            [
                notice.notice_id,
                format_time(notice.created_at),
                notice.title,
                notice.content,
                "未读" if not notice.read_flag else "已读",
            ]
            for notice in notices
        ]
        console.print_table(
            ["编号", "时间", "标题", "内容", "状态"],
            rows,
            max_cell=30,
        )
        if notices and console.confirm("是否全部标记为已读？"):
            self.services.notices.mark_all_read(self.session)
            console.success("已全部标记为已读")

    def _address(self) -> None:
        user = self.services.auth.get_user(self.session.user_id)
        console.info(f"当前默认地址：{user.default_address or '未设置'}")
        address = console.read_text("新的默认收货地址")
        self.services.auth.update_address(self.session, address)
        console.success("默认收货地址已更新")
