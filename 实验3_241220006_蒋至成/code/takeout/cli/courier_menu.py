"""配送员菜单。"""

from takeout.cli import console, helpers
from takeout.errors import AppError
from takeout.utils import format_time


class CourierMenu:
    """配送员端：查看任务、取餐、送达、失败上报与工作状态。"""

    def __init__(self, app, session) -> None:
        self.app = app
        self.session = session
        self.services = app.container

    def run(self) -> None:
        """配送员主菜单循环。"""
        while True:
            choice = console.show_menu(
                f"配送员菜单（{self.session.phone}）",
                [
                    "我的配送任务",
                    "取餐",
                    "确认送达",
                    "上报配送失败",
                    "切换空闲/忙碌",
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
            1: self._tasks,
            2: self._pickup,
            3: self._delivered,
            4: self._fail,
            5: self._toggle_status,
            6: self._notices,
        }
        actions[choice]()

    def _show_tasks(self) -> None:
        tasks = self.services.delivery_service.list_my_tasks(self.session)
        names = helpers.shop_name_map(self.app)
        rows = []
        for task in tasks:
            order = self.services.order_service.get_by_id(task.order_id)
            rows.append(
                [
                    task.task_id,
                    order.order_no,
                    task.status,
                    names.get(order.shop_id, order.shop_id),
                    order.address_snapshot,
                    format_time(task.assigned_at),
                ]
            )
        console.print_table(
            ["配送单", "订单号", "状态", "店铺", "收货地址", "分配时间"],
            rows,
            max_cell=20,
        )

    def _tasks(self) -> None:
        self._show_tasks()

    def _pickup(self) -> None:
        self._show_tasks()
        task_id = console.read_int("配送单号", minimum=1)
        task = self.services.delivery_service.pickup(self.session, task_id)
        console.success(f"已取餐，配送单状态：{task.status}")

    def _delivered(self) -> None:
        self._show_tasks()
        task_id = console.read_int("配送单号", minimum=1)
        task = self.services.delivery_service.delivered(self.session, task_id)
        console.success(f"已确认送达，配送单状态：{task.status}")

    def _fail(self) -> None:
        self._show_tasks()
        task_id = console.read_int("配送单号", minimum=1)
        reason = console.read_text("失败原因")
        task = self.services.delivery_service.report_fail(
            self.session, task_id, reason
        )
        console.success(f"已上报失败，配送单状态：{task.status}，等待管理员处理")

    def _toggle_status(self) -> None:
        user = self.services.auth.get_user(self.session.user_id)
        console.info(f"当前工作状态：{user.work_status}")
        choice = console.show_menu("切换工作状态", ["空闲", "忙碌"])
        if choice == 0:
            return
        status = "空闲" if choice == 1 else "忙碌"
        self.services.delivery_service.set_work_status(self.session, status)
        console.success(f"工作状态已切换为：{status}")

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
