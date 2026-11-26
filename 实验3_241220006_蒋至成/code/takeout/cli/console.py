"""命令行界面基础组件：输入、提示与中文表格。"""

from decimal import Decimal, InvalidOperation

from takeout.utils import pad, text_width, truncate

LINE_WIDTH = 78


def title(text: str) -> None:
    """打印分节标题。"""
    print()
    print("=" * LINE_WIDTH)
    print(text)
    print("=" * LINE_WIDTH)


def section(text: str) -> None:
    """打印小节标题。"""
    print()
    print(f"—— {text} ——")


def info(message: str) -> None:
    """普通提示。"""
    print(f"[提示] {message}")


def success(message: str) -> None:
    """成功提示。"""
    print(f"[成功] {message}")


def error(message: str) -> None:
    """错误提示。"""
    print(f"[错误] {message}")


def warning(message: str) -> None:
    """警告提示。"""
    print(f"[警告] {message}")


def read_text(prompt: str, default: str = "") -> str:
    """读取一行文本，空输入返回默认值。"""
    suffix = f"（默认：{default}）" if default else ""
    value = input(f"{prompt}{suffix}：").strip()
    return value or default


def read_int(
    prompt: str,
    minimum: int | None = None,
    maximum: int | None = None,
    default: int | None = None,
) -> int:
    """读取整数并校验范围。"""
    while True:
        raw = input(f"{prompt}：").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            error("请输入整数")
            continue
        if minimum is not None and value < minimum:
            error(f"不能小于 {minimum}")
            continue
        if maximum is not None and value > maximum:
            error(f"不能大于 {maximum}")
            continue
        return value


def read_decimal(prompt: str, default: Decimal | None = None) -> Decimal:
    """读取金额。"""
    while True:
        raw = input(f"{prompt}：").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = Decimal(raw)
        except InvalidOperation:
            error("请输入数字金额")
            continue
        if value < 0:
            error("金额不能为负数")
            continue
        return value


def confirm(prompt: str, default: bool = False) -> bool:
    """读取是/否。"""
    hint = "Y/n" if default else "y/N"
    raw = input(f"{prompt}（{hint}）：").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "是", "1")


def pause(message: str = "按回车键继续…") -> None:
    """等待用户确认。"""
    input(message)


def show_menu(heading: str, options: list[str]) -> int:
    """显示菜单并返回用户选择，0 表示返回/退出。"""
    title(heading)
    for index, text in enumerate(options, start=1):
        print(f"  {index}. {text}")
    print("  0. 返回")
    return read_int("请选择", minimum=0, maximum=len(options))


def render_table(
    headers: list[str],
    rows: list[list[object]],
    aligns: list[str] | None = None,
    max_cell: int = 24,
) -> str:
    """生成对齐的中文文本表格。"""
    if not rows:
        return "（暂无数据）"
    aligns = aligns or ["left"] * len(headers)
    text_rows = [
        [truncate("" if cell is None else str(cell), max_cell) for cell in row]
        for row in rows
    ]
    widths = [text_width(header) for header in headers]
    for row in text_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], text_width(cell))
    header_line = " | ".join(
        pad(header, widths[index], "center")
        for index, header in enumerate(headers)
    )
    separator = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(
            pad(cell, widths[index], aligns[index])
            for index, cell in enumerate(row)
        )
        for row in text_rows
    ]
    return "\n".join([header_line, separator, *body])


def print_table(
    headers: list[str],
    rows: list[list[object]],
    aligns: list[str] | None = None,
    max_cell: int = 24,
) -> None:
    """打印表格。"""
    print(render_table(headers, rows, aligns=aligns, max_cell=max_cell))
