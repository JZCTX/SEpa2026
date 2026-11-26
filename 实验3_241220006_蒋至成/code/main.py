"""外卖点餐与配送系统启动入口。

运行方式：
    python main.py            # 使用 data/takeout.db
    python main.py --demo     # 首次运行时写入演示账号与菜品
    python main.py --db my.db # 指定数据库文件
"""

import argparse
import sys

from takeout import config
from takeout.cli.application import Application


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description=config.APP_NAME)
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite 数据库路径，默认 data/takeout.db",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="首次运行时创建四类演示账号、店铺与菜品",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {config.VERSION}"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """程序入口。"""
    args = parse_args(argv)
    try:
        Application(args.db, args.demo).run()
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # 顶层保护，避免把堆栈直接抛给普通用户
        print(f"[严重错误] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
