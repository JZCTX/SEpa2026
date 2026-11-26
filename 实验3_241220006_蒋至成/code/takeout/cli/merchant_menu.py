"""商家菜单。"""

from takeout import config
from takeout.cli import console, helpers
from takeout.enums import OrderStatus
from takeout.errors import AppError
from takeout.utils import format_time, now


class MerchantMenu:
    """商家端：店铺、菜品、接单出餐、分配配送与统计。"""

    def __init__(self, app, session) -> None:
        self.app = app
        self.session = session
        self.services = app.container

    def run(self) -> None:
        """商家主菜单循环。"""
        while True:
            choice = console.show_menu(
                f"商家菜单（{self.session.phone}）",
                [
                    "店铺信息与营业状态",
                    "菜品管理",
                    "订单工作台",
                    "分配配送员",
                    "经营日报与统计",
                    "操作日志",
                    "消息通知",
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
            1: self._shop,
            2: self._dishes,
            3: self._workbench,
            4: self._assign,
            5: self._report,
            6: self._logs,
            7: self._notices,
        }
        actions[choice]()

    # ------------------------------------------------------------------
    # 店铺
    # ------------------------------------------------------------------
    def _shop(self) -> None:
        shop = self.services.shop_service.get_my_shop(self.session)
        rows = [
            ["店铺编号", shop.shop_id],
            ["店铺名称", shop.name],
            ["资质编号", shop.license_no],
            ["状态", shop.status],
            ["营业时段", shop.business_hours],
            ["审核备注", shop.audit_remark or "—"],
        ]
        console.print_table(["字段", "内容"], rows, max_cell=48)
        choice = console.show_menu(
            "店铺操作", ["开始营业", "暂停营业", "修改营业时段", "重新提交审核"]
        )
        if choice == 0:
            return
        if choice == 1:
            shop = self.services.shop_service.set_business(self.session, True)
        elif choice == 2:
            shop = self.services.shop_service.set_business(self.session, False)
        elif choice == 3:
            hours = console.read_text("营业时段", default=shop.business_hours)
            shop = self.services.shop_service.update_business_hours(
                self.session, hours
            )
        else:
            remark = console.read_text("补充说明（可留空）")
            shop = self.services.shop_service.submit_audit(self.session, remark)
        console.success(f"店铺当前状态：{shop.status}")

    # ------------------------------------------------------------------
    # 菜品
    # ------------------------------------------------------------------
    def _show_dishes(self) -> list:
        dishes = self.services.dish_service.list_mine(self.session)
        rows = [
            [
                dish.dish_id,
                dish.name,
                dish.category,
                f"{dish.price:.2f}",
                dish.stock,
                dish.status,
            ]
            for dish in dishes
        ]
        console.print_table(
            ["编号", "菜品", "分类", "价格", "库存", "状态"],
            rows,
            aligns=["right", "left", "left", "right", "right", "left"],
        )
        return dishes

    def _dishes(self) -> None:
        while True:
            self._show_dishes()
            choice = console.show_menu(
                "菜品操作", ["新增菜品", "菜品改价", "调整库存", "上架", "下架"]
            )
            if choice == 0:
                return
            try:
                if choice == 1:
                    self._create_dish()
                elif choice == 2:
                    dish_id = console.read_int("菜品编号", minimum=1)
                    price = console.read_decimal("新价格")
                    dish = self.services.dish_service.change_price(
                        self.session, dish_id, price
                    )
                    console.success(f"「{dish.name}」新价格 {dish.price:.2f} 元")
                elif choice == 3:
                    dish_id = console.read_int("菜品编号", minimum=1)
                    stock = console.read_int("新库存", minimum=0)
                    dish = self.services.dish_service.set_stock(
                        self.session, dish_id, stock
                    )
                    console.success(f"「{dish.name}」库存 {dish.stock}，状态 {dish.status}")
                elif choice == 4:
                    dish_id = console.read_int("菜品编号", minimum=1)
                    dish = self.services.dish_service.publish(self.session, dish_id)
                    console.success(f"「{dish.name}」状态 {dish.status}")
                elif choice == 5:
                    dish_id = console.read_int("菜品编号", minimum=1)
                    dish = self.services.dish_service.off_shelf(
                        self.session, dish_id
                    )
                    console.success(f"「{dish.name}」状态 {dish.status}")
            except AppError as exc:
                console.error(exc.message)
            console.pause()

    def _create_dish(self) -> None:
        name = console.read_text("菜品名称")
        category = console.read_text("分类", default="其他")
        price = console.read_decimal("价格")
        stock = console.read_int("初始库存", minimum=0, default=0)
        publish = console.confirm("是否立即上架？")
        dish = self.services.dish_service.create(
            self.session, name, category, price, stock, publish
        )
        console.success(f"菜品已创建：编号 {dish.dish_id}，状态 {dish.status}")

    # ------------------------------------------------------------------
    # 订单工作台
    # ------------------------------------------------------------------
    def _workbench(self) -> None:
        orders = []
        for status in (
            OrderStatus.PAID,
            OrderStatus.COOKING,
            OrderStatus.PENDING_DELIVERY,
        ):
            orders.extend(self.services.order_service.list_orders(self.session, status))
        helpers.print_order_table(self.app, orders)
        order_no = console.read_text("输入订单号处理（留空返回）")
        if not order_no:
            return
        order = self.services.order_service.get_visible(self.session, order_no)
        helpers.print_order_detail(self.app, order)
        if order.status == OrderStatus.PAID:
            if order.pay_time:
                elapsed = int((now() - order.pay_time).total_seconds() // 60)
                remain = config.ACCEPT_TIMEOUT_MINUTES - elapsed
                console.warning(
                    f"已支付 {elapsed} 分钟，剩余接单时间约 {max(remain, 0)} 分钟"
                )
            choice = console.show_menu("待接单操作", ["接单", "拒单并退款"])
            if choice == 1:
                order = self.services.order_service.merchant_accept(
                    self.session, order_no
                )
                console.success(f"已接单，订单状态：{order.status}")
            elif choice == 2:
                reason = console.read_text("拒单原因")
                order = self.services.order_service.merchant_reject(
                    self.session, order_no, reason
                )
                console.success(f"已拒单并退款，订单状态：{order.status}")
        elif order.status == OrderStatus.COOKING:
            if console.confirm("是否确认出餐？"):
                order = self.services.order_service.finish_cook(
                    self.session, order_no
                )
                console.success(f"已出餐，订单状态：{order.status}")
        else:
            console.info("该订单待配送，请使用「分配配送员」功能")

    def _assign(self) -> None:
        orders = self.services.order_service.list_orders(
            self.session, OrderStatus.PENDING_DELIVERY
        )
        helpers.print_order_table(self.app, orders)
        courier_ids = self.services.delivery_service.available_couriers()
        if not courier_ids:
            console.warning("当前没有空闲配送员")
            return
        rows = []
        for courier_id in courier_ids:
            user = self.services.auth.get_user(courier_id)
            rows.append([courier_id, user.phone, user.work_status])
        console.section("可用配送员")
        console.print_table(["编号", "手机号", "状态"], rows, aligns=["right", "left", "left"])
        order_no = console.read_text("订单号")
        courier_id = console.read_int("配送员编号", minimum=1)
        task = self.services.delivery_service.assign(
            self.session, order_no, courier_id
        )
        console.success(
            f"已分配配送员，配送单号 {task.task_id}，状态 {task.status}"
        )

    # ------------------------------------------------------------------
    # 统计与日志
    # ------------------------------------------------------------------
    def _report(self) -> None:
        report = self.services.stats_service.merchant_daily(self.session)
        console.section(f"{report.report_date} 经营日报（已完成订单）")
        console.info(f"完成订单 {report.order_count} 单，营业额 {report.gmv:.2f} 元")
        if report.top_dishes:
            console.print_table(
                ["热销菜品", "销量"],
                [[name, qty] for name, qty in report.top_dishes],
                aligns=["left", "right"],
            )
        recent = self.services.stats_service.merchant_recent(self.session, 7)
        console.section("最近 7 天")
        console.print_table(
            ["日期", "完成订单", "营业额"],
            [
                [item.report_date, item.order_count, f"{item.gmv:.2f}"]
                for item in recent
            ],
            aligns=["left", "right", "right"],
        )
        total = self.services.stats_service.merchant_revenue(self.session)
        console.info(f"累计营业额（已完成订单）：{total:.2f} 元")

    def _logs(self) -> None:
        action = console.read_text("操作类型关键词（可留空）")
        date_from = helpers.read_optional_date("开始日期")
        date_to = helpers.read_optional_date("结束日期")
        logs = self.services.logs.query(self.session, action, date_from, date_to)
        rows = [
            [
                format_time(log.created_at),
                log.operator_role,
                log.action,
                f"{log.target_type}#{log.target_id}",
                log.before_state or "—",
                log.after_state or "—",
            ]
            for log in logs
        ]
        console.print_table(
            ["时间", "角色", "操作", "对象", "变更前", "变更后"],
            rows,
            max_cell=18,
        )

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
            ["编号", "时间", "标题", "内容", "状态"], rows, max_cell=30
        )
        if notices and console.confirm("是否全部标记为已读？"):
            self.services.notices.mark_all_read(self.session)
            console.success("已全部标记为已读")
