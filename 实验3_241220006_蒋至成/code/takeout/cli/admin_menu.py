"""平台管理员菜单。"""

from takeout.cli import console, helpers
from takeout.enums import OrderStatus, UserRole
from takeout.errors import AppError
from takeout.utils import format_time


class AdminMenu:
    """管理员端：店铺审核、异常订单、平台统计、日志与用户。"""

    def __init__(self, app, session) -> None:
        self.app = app
        self.session = session
        self.services = app.container

    def run(self) -> None:
        """管理员主菜单循环。"""
        while True:
            choice = console.show_menu(
                f"管理员菜单（{self.session.phone}）",
                [
                    "待审核店铺",
                    "全部店铺",
                    "异常订单处理",
                    "平台统计与店铺对比",
                    "操作日志查询",
                    "用户列表",
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
            1: self._pending_shops,
            2: self._all_shops,
            3: self._exceptions,
            4: self._stats,
            5: self._logs,
            6: self._users,
            7: self._notices,
        }
        actions[choice]()

    # ------------------------------------------------------------------
    # 店铺审核
    # ------------------------------------------------------------------
    def _shop_rows(self, shops: list) -> list[list[object]]:
        rows = []
        for shop in shops:
            merchant = self.services.users.get_by_id(shop.merchant_id)
            rows.append(
                [
                    shop.shop_id,
                    shop.name,
                    merchant.phone if merchant else shop.merchant_id,
                    shop.status,
                    shop.business_hours,
                    shop.audit_remark or "—",
                ]
            )
        return rows

    def _pending_shops(self) -> None:
        shops = self.services.shop_service.list_pending(self.session)
        console.print_table(
            ["编号", "店铺", "商家手机号", "状态", "营业时段", "备注"],
            self._shop_rows(shops),
            aligns=["right", "left", "left", "left", "left", "left"],
            max_cell=20,
        )
        if not shops:
            return
        shop_id = console.read_int("待审核店铺编号", minimum=1)
        approved = console.confirm("是否审核通过？", default=True)
        if approved:
            remark = console.read_text("审核备注", default="证照齐全，审核通过")
        else:
            remark = console.read_text("驳回原因")
        shop = self.services.shop_service.audit(
            self.session, shop_id, approved, remark
        )
        console.success(f"店铺「{shop.name}」当前状态：{shop.status}")

    def _all_shops(self) -> None:
        shops = self.services.shop_service.list_all(self.session)
        console.print_table(
            ["编号", "店铺", "商家手机号", "状态", "营业时段", "备注"],
            self._shop_rows(shops),
            aligns=["right", "left", "left", "left", "left", "left"],
            max_cell=20,
        )

    # ------------------------------------------------------------------
    # 异常订单
    # ------------------------------------------------------------------
    def _exceptions(self) -> None:
        orders = self.services.order_service.list_orders(
            self.session, OrderStatus.PENDING_HANDLE
        )
        helpers.print_order_table(self.app, orders)
        if not orders:
            console.info("当前没有待处理异常订单")
            return
        order_no = console.read_text("订单号")
        order = self.services.order_service.get_visible(self.session, order_no)
        helpers.print_order_detail(self.app, order)
        choice = console.show_menu("异常处理", ["重新分配配送员", "同意退款"])
        if choice == 1:
            courier_ids = self.services.delivery_service.available_couriers()
            rows = []
            for courier_id in courier_ids:
                user = self.services.auth.get_user(courier_id)
                rows.append([courier_id, user.phone, user.work_status])
            console.print_table(
                ["编号", "手机号", "状态"], rows, aligns=["right", "left", "left"]
            )
            if not courier_ids:
                console.warning("没有空闲配送员")
                return
            courier_id = console.read_int("配送员编号", minimum=1)
            task = self.services.delivery_service.admin_reassign(
                self.session, order_no, courier_id
            )
            console.success(f"已重新分配，配送单状态：{task.status}")
        elif choice == 2:
            reason = console.read_text("退款原因")
            order = self.services.order_service.admin_refund_exception(
                self.session, order_no, reason
            )
            console.success(f"已退款，订单状态：{order.status}")

    # ------------------------------------------------------------------
    # 统计、日志与用户
    # ------------------------------------------------------------------
    def _stats(self) -> None:
        overview = self.services.stats_service.platform_overview(self.session)
        console.section("平台概览")
        rows = [
            ["店铺总数", overview["shop_count"]],
            ["订单总数", overview["order_count"]],
            ["已完成订单", overview["completed_count"]],
            ["平台成交额", f"{overview['gmv']:.2f} 元"],
        ]
        console.print_table(["指标", "数值"], rows, aligns=["left", "right"])
        console.section("订单状态分布")
        status_counts = overview["status_counts"]
        status_rows = [
            [status, status_counts.get(str(status), 0)] for status in OrderStatus
        ]
        console.print_table(
            ["状态", "订单数"], status_rows, aligns=["left", "right"]
        )
        console.section("各店铺订单量对比")
        comparison = self.services.stats_service.shop_comparison(self.session)
        console.print_table(
            ["店铺编号", "店铺", "订单量"],
            [[shop_id, name, total] for shop_id, name, total in comparison],
            aligns=["right", "left", "right"],
        )

    def _logs(self) -> None:
        action = console.read_text("操作类型关键词（可留空）")
        date_from = helpers.read_optional_date("开始日期")
        date_to = helpers.read_optional_date("结束日期")
        logs = self.services.logs.query(self.session, action, date_from, date_to)
        rows = [
            [
                format_time(log.created_at),
                log.operator_role,
                log.operator_id,
                log.action,
                f"{log.target_type}#{log.target_id}",
                log.before_state or "—",
                log.after_state or "—",
            ]
            for log in logs
        ]
        console.print_table(
            ["时间", "角色", "操作人", "操作", "对象", "变更前", "变更后"],
            rows,
            max_cell=16,
        )

    def _users(self) -> None:
        role = console.read_text("角色筛选（顾客/商家/配送员/管理员，可留空）")
        role_filter = None
        if role:
            try:
                role_filter = UserRole(role)
            except ValueError:
                console.warning(f"未知角色「{role}」，已显示全部用户")
        users = self.services.auth.list_users(role_filter)
        rows = [
            [
                user.user_id,
                user.phone,
                user.role,
                user.account_status,
                format_time(user.lock_until) or "—",
                user.work_status or "—",
            ]
            for user in users
        ]
        console.print_table(
            ["编号", "手机号", "角色", "账号状态", "锁定至", "工作状态"],
            rows,
            aligns=["right", "left", "left", "left", "left", "left"],
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
