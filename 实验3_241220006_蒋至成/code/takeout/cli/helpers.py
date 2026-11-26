"""命令行界面共用展示函数。"""

from datetime import date, datetime

from takeout.cli import console
from takeout.domain.order import Order
from takeout.enums import OrderStatus
from takeout.utils import format_time, parse_date


def shop_name_map(app) -> dict[int, str]:
    """店铺编号到名称的映射。"""
    return {shop.shop_id: shop.name for shop in app.container.shops.list_all()}


def customer_phone(app, customer_id: int) -> str:
    """顾客手机号。"""
    user = app.container.users.get_by_id(customer_id)
    return user.phone if user else str(customer_id)


def read_optional_date(prompt: str) -> date | None:
    """读取可选日期，格式 YYYY-MM-DD，空值返回 None。"""
    while True:
        raw = console.read_text(f"{prompt}（YYYY-MM-DD，可留空）")
        if not raw:
            return None
        try:
            return parse_date(raw)
        except ValueError:
            console.error("日期格式不正确，请按 YYYY-MM-DD 输入")


def choose_status(allow_all: bool = True) -> OrderStatus | None:
    """选择订单状态过滤条件。"""
    statuses = list(OrderStatus)
    console.section("订单状态筛选")
    for index, status in enumerate(statuses, start=1):
        print(f"  {index}. {status}")
    if allow_all:
        print("  0. 全部状态")
    choice = console.read_int("请选择", minimum=0, maximum=len(statuses))
    if choice == 0:
        return None
    return statuses[choice - 1]


def print_order_detail(app, order: Order) -> None:
    """打印订单完整信息，包括明细、支付与退款。"""
    console.section(f"订单详情 {order.order_no}")
    names = shop_name_map(app)
    rows = [
        ["订单号", order.order_no],
        ["状态", order.status],
        ["店铺", names.get(order.shop_id, str(order.shop_id))],
        ["顾客", customer_phone(app, order.customer_id)],
        ["下单时间", format_time(order.created_at)],
        ["支付时间", format_time(order.pay_time) or "—"],
        ["收货地址", order.address_snapshot],
        ["商品金额", f"{order.subtotal:.2f} 元"],
        ["配送费", f"{order.delivery_fee:.2f} 元"],
        ["订单总额", f"{order.total_amount:.2f} 元"],
        ["取消/退款原因", order.cancel_reason or "—"],
    ]
    console.print_table(["字段", "内容"], rows, max_cell=48)
    if order.items:
        console.section("订单明细（下单时快照）")
        item_rows = [
            [
                item.dish_name_snapshot,
                f"{item.unit_price_snapshot:.2f}",
                item.quantity,
                f"{item.subtotal:.2f}",
            ]
            for item in order.items
        ]
        console.print_table(
            ["菜品", "单价", "数量", "小计"],
            item_rows,
            aligns=["left", "right", "right", "right"],
        )
    payment = app.container.orders.get_payment(order.order_id)
    if payment:
        console.info(
            f"支付记录：流水号 {payment.trade_no}，金额 {payment.amount:.2f} 元，"
            f"时间 {format_time(payment.paid_at)}"
        )
    refund = app.container.orders.get_refund(order.order_id)
    if refund:
        console.warning(
            f"退款记录：退款单 {refund.refund_no}，金额 {refund.amount:.2f} 元，"
            f"原因 {refund.reason}"
        )


def order_rows(app, orders: list[Order]) -> list[list[object]]:
    """把订单列表转换为表格行。"""
    names = shop_name_map(app)
    return [
        [
            order.order_no,
            names.get(order.shop_id, order.shop_id),
            order.status,
            f"{order.total_amount:.2f}",
            format_time(order.created_at),
        ]
        for order in orders
    ]


def print_order_table(app, orders: list[Order]) -> None:
    """打印订单列表。"""
    console.print_table(
        ["订单号", "店铺", "状态", "金额", "下单时间"],
        order_rows(app, orders),
        aligns=["left", "left", "left", "right", "left"],
        max_cell=22,
    )


def current_time_text(moment: datetime | None = None) -> str:
    """当前时间文本。"""
    return format_time(moment or datetime.now())
