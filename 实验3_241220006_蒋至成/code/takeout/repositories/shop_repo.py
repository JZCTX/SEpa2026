"""店铺仓储。"""

from datetime import datetime

from takeout.db import Database
from takeout.domain.shop import Shop
from takeout.enums import ShopStatus
from takeout.utils import format_time


class ShopRepository:
    """shops 表的读写。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        merchant_id: int,
        name: str,
        license_no: str,
        status: ShopStatus,
        business_hours: str,
        created_at: datetime,
    ) -> int:
        """新增店铺。"""
        cursor = self.db.execute(
            """
            INSERT INTO shops
                (merchant_id, name, license_no, status, business_hours,
                 audit_remark, created_at)
            VALUES (?, ?, ?, ?, ?, '', ?)
            """,
            (
                merchant_id,
                name,
                license_no,
                str(status),
                business_hours,
                format_time(created_at),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, shop_id: int) -> Shop | None:
        """按主键查询。"""
        row = self.db.query_one("SELECT * FROM shops WHERE shop_id = ?", (shop_id,))
        return Shop.from_row(row) if row else None

    def get_by_merchant(self, merchant_id: int) -> Shop | None:
        """查询商家自己的店铺。"""
        row = self.db.query_one(
            "SELECT * FROM shops WHERE merchant_id = ?", (merchant_id,)
        )
        return Shop.from_row(row) if row else None

    def get_by_name(self, name: str) -> Shop | None:
        """按店铺名称查询，用于唯一性校验。"""
        row = self.db.query_one("SELECT * FROM shops WHERE name = ?", (name,))
        return Shop.from_row(row) if row else None

    def list_all(self, status: ShopStatus | None = None) -> list[Shop]:
        """列出店铺，可按状态过滤。"""
        if status is None:
            rows = self.db.query_all("SELECT * FROM shops ORDER BY shop_id")
        else:
            rows = self.db.query_all(
                "SELECT * FROM shops WHERE status = ? ORDER BY shop_id",
                (str(status),),
            )
        return [Shop.from_row(row) for row in rows]

    def update(self, shop: Shop) -> None:
        """保存店铺状态、营业时间与审核备注。"""
        self.db.execute(
            """
            UPDATE shops
               SET status = ?, business_hours = ?, audit_remark = ?
             WHERE shop_id = ?
            """,
            (
                str(shop.status),
                shop.business_hours,
                shop.audit_remark,
                shop.shop_id,
            ),
        )
