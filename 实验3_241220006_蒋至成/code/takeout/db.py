"""SQLite 数据库连接与建表脚本。

数据库结构由 UML 类图的 17 个类映射而来：每个类对应一张表，类之间的
组合、关联通过外键体现；5 个枚举以文本形式保存，便于直接查看数据。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from takeout import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    phone           TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL,
    account_status  TEXT    NOT NULL DEFAULT '正常',
    lock_until      TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    default_address TEXT    NOT NULL DEFAULT '',
    shop_id         INTEGER,
    work_status     TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS shops (
    shop_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id    INTEGER NOT NULL UNIQUE REFERENCES users(user_id),
    name           TEXT    NOT NULL UNIQUE,
    license_no     TEXT    NOT NULL,
    status         TEXT    NOT NULL,
    business_hours TEXT    NOT NULL,
    audit_remark   TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS dishes (
    dish_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id    INTEGER NOT NULL REFERENCES shops(shop_id),
    name       TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    price      TEXT    NOT NULL,
    stock      INTEGER NOT NULL DEFAULT 0,
    status     TEXT    NOT NULL,
    version    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS carts (
    cart_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL UNIQUE REFERENCES users(user_id),
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS cart_items (
    cart_id        INTEGER NOT NULL REFERENCES carts(cart_id),
    dish_id        INTEGER NOT NULL REFERENCES dishes(dish_id),
    quantity       INTEGER NOT NULL,
    price_snapshot TEXT    NOT NULL,
    PRIMARY KEY (cart_id, dish_id)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no          TEXT    NOT NULL UNIQUE,
    customer_id       INTEGER NOT NULL REFERENCES users(user_id),
    shop_id           INTEGER NOT NULL REFERENCES shops(shop_id),
    status            TEXT    NOT NULL,
    total_amount      TEXT    NOT NULL,
    delivery_fee      TEXT    NOT NULL,
    address_snapshot  TEXT    NOT NULL,
    idempotency_key   TEXT    NOT NULL UNIQUE,
    created_at        TEXT    NOT NULL,
    pay_time          TEXT,
    cancel_reason     TEXT    NOT NULL DEFAULT '',
    updated_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id           INTEGER NOT NULL REFERENCES orders(order_id),
    dish_id            INTEGER NOT NULL REFERENCES dishes(dish_id),
    dish_name_snapshot TEXT    NOT NULL,
    unit_price_snapshot TEXT   NOT NULL,
    quantity           INTEGER NOT NULL,
    subtotal           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    pay_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(order_id),
    trade_no TEXT    NOT NULL UNIQUE,
    amount   TEXT    NOT NULL,
    channel  TEXT    NOT NULL,
    status   TEXT    NOT NULL,
    paid_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(order_id),
    refund_no   TEXT    NOT NULL UNIQUE,
    amount      TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    refunded_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_tasks (
    task_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL UNIQUE REFERENCES orders(order_id),
    courier_id  INTEGER NOT NULL REFERENCES users(user_id),
    status      TEXT    NOT NULL,
    assigned_at TEXT    NOT NULL,
    pickup_at   TEXT,
    delivered_at TEXT,
    fail_reason TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS operation_logs (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_id   INTEGER NOT NULL,
    operator_role TEXT    NOT NULL,
    action        TEXT    NOT NULL,
    target_type   TEXT    NOT NULL,
    target_id     TEXT    NOT NULL,
    before_state  TEXT    NOT NULL DEFAULT '',
    after_state   TEXT    NOT NULL DEFAULT '',
    shop_id       INTEGER,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    notice_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    title      TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    read_flag  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dishes_shop ON dishes(shop_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_shop ON orders(shop_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_courier ON delivery_tasks(courier_id);
CREATE INDEX IF NOT EXISTS idx_logs_created ON operation_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_notices_user ON notifications(user_id, read_flag);
"""


class Database:
    """轻量数据库封装，负责连接、事务与通用查询。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else config.DB_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.isolation_level = None
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(self.path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._depth = 0
        self.create_schema()

    def create_schema(self) -> None:
        """执行建表脚本，可重复执行。"""
        self.conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文，支持服务层嵌套调用（仅最外层提交）。"""
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield self.conn
        except Exception:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("ROLLBACK")
            raise
        self._depth -= 1
        if self._depth == 0:
            self.conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[object] = ()) -> sqlite3.Cursor:
        """执行写语句。"""
        return self.conn.execute(sql, params)

    def query_all(
        self, sql: str, params: Sequence[object] = ()
    ) -> list[sqlite3.Row]:
        """查询多行。"""
        return list(self.conn.execute(sql, params).fetchall())

    def query_one(
        self, sql: str, params: Sequence[object] = ()
    ) -> sqlite3.Row | None:
        """查询单行。"""
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[object] = ()) -> object:
        """查询单个值。"""
        row = self.query_one(sql, params)
        return None if row is None else row[0]

    def close(self) -> None:
        """关闭连接。"""
        self.conn.close()
