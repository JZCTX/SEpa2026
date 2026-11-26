"""应用入口与登录/注册流程。"""

from datetime import datetime, timedelta

from takeout import config
from takeout.cli import console
from takeout.cli.admin_menu import AdminMenu
from takeout.cli.courier_menu import CourierMenu
from takeout.cli.customer_menu import CustomerMenu
from takeout.cli.merchant_menu import MerchantMenu
from takeout.container import Container
from takeout.demo import seed_demo
from takeout.enums import UserRole
from takeout.errors import AppError
from takeout.security import Session


ROLE_MENUS = {
    UserRole.CUSTOMER: CustomerMenu,
    UserRole.MERCHANT: MerchantMenu,
    UserRole.COURIER: CourierMenu,
    UserRole.ADMIN: AdminMenu,
}


class Application:
    """把容器、登录态与角色菜单组合起来。"""

    def __init__(self, db_path=None, demo: bool = False) -> None:
        self.container = Container(db_path)
        self.session: Session | None = None
        self.token_value: str | None = None
        self.demo = demo
        self._last_tick = datetime.min

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self) -> None:
        """启动程序主循环。"""
        self._print_banner()
        if self.demo:
            self._prepare_demo()
        self._tick(force=True)
        try:
            while True:
                if self.session is None:
                    try:
                        if not self._login_menu():
                            break
                    except AppError as exc:
                        console.error(exc.message)
                        console.pause()
                else:
                    menu_class = ROLE_MENUS[self.session.role]
                    menu_class(self, self.session).run()
                    self._logout()
                self._tick()
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            self.container.close()
        console.info("感谢使用，再见。")

    def _print_banner(self) -> None:
        print("=" * 78)
        print(f"  {config.APP_NAME}  v{config.VERSION}")
        print("  软件工程实验三 · Python 3.12 + SQLite 命令行版")
        print("=" * 78)

    def _prepare_demo(self) -> None:
        created = seed_demo(self.container)
        if created:
            console.success("演示数据已创建，账号密码均为 123456：")
            console.info("管理员 13800000000 / 顾客 13800000001")
            console.info("商家 13800000002（仙林小馆）/ 配送员 13800000003")
        else:
            console.info("数据库已有数据，跳过演示数据初始化")

    def _login_menu(self) -> bool:
        choice = console.show_menu(
            "欢迎，请选择操作",
            [
                "登录",
                "注册顾客",
                "注册商家（同时提交店铺资料）",
                "注册配送员",
                "注册管理员",
            ],
        )
        if choice == 0:
            return False
        if choice == 1:
            self._login()
        else:
            self._register(choice)
        return True

    def _login(self) -> None:
        phone = console.read_text("手机号")
        password = console.read_text("密码")
        token = self.container.auth.login(phone, password)
        self.token_value = token.value
        self.session = token.session
        console.success(
            f"登录成功，{self.session.role}（用户编号 {self.session.user_id}）"
        )
        unread = self.container.notices.unread_count(self.session)
        if unread:
            console.info(f"你有 {unread} 条未读消息")

    def _register(self, choice: int) -> None:
        phone = console.read_text("手机号")
        password = console.read_text("密码（至少 6 位）")
        auth = self.container.auth
        if choice == 2:
            address = console.read_text("默认收货地址")
            auth.register_customer(phone, password, address)
        elif choice == 3:
            shop_name = console.read_text("店铺名称")
            license_no = console.read_text("营业执照/资质编号")
            auth.register_merchant(phone, password, shop_name, license_no)
        elif choice == 4:
            auth.register_courier(phone, password)
        else:
            auth.register_admin(phone, password)
        console.success("注册成功，请使用手机号和密码登录")
        if choice == 3:
            console.info("店铺已提交审核，需管理员审核通过后方可营业")

    def _logout(self) -> None:
        if self.token_value:
            self.container.auth.logout(self.token_value)
        self.token_value = None
        self.session = None
        console.info("已退出登录")

    # ------------------------------------------------------------------
    # 定时任务
    # ------------------------------------------------------------------
    def _tick(self, force: bool = False) -> None:
        moment = datetime.now()
        if not force and moment - self._last_tick < timedelta(
            seconds=config.SCHEDULER_INTERVAL_SECONDS
        ):
            return
        self._last_tick = moment
        try:
            result = self.container.scheduler.tick()
        except AppError as exc:  # 定时任务失败不应中断主流程
            console.warning(f"定时任务执行失败：{exc.message}")
            return
        total = sum(result.values())
        if total:
            console.warning(
                "系统扫描：超时未接单取消 {timeout_cancelled} 单，"
                "超时自动完成 {auto_completed} 单，清理日志 {logs_cleaned} 条".format(
                    **result
                )
            )

    def reload_session(self) -> None:
        """商家开店审核后刷新会话中的店铺编号。"""
        if self.session is not None:
            user = self.container.auth.get_user(self.session.user_id)
            self.session = Session(
                user_id=user.user_id,
                phone=user.phone,
                role=user.role,
                shop_id=user.shop_id,
                display_name=self.session.display_name,
            )
