"""店铺领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row
from typing import Mapping

from takeout.enums import ShopStatus
from takeout.errors import InvalidTransitionError
from takeout.utils import parse_time


@dataclass
class Shop:
    """店铺。状态在待审核、营业、歇业、审核驳回之间切换。"""

    shop_id: int = 0
    merchant_id: int = 0
    name: str = ""
    license_no: str = ""
    status: ShopStatus = ShopStatus.PENDING
    business_hours: str = "07:00-23:00"
    audit_remark: str = ""
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, object]) -> "Shop":
        """从数据库行构造店铺。"""
        return cls(
            shop_id=int(row["shop_id"]),
            merchant_id=int(row["merchant_id"]),
            name=str(row["name"]),
            license_no=str(row["license_no"]),
            status=ShopStatus(row["status"]),
            business_hours=str(row["business_hours"]),
            audit_remark=str(row["audit_remark"]),
            created_at=parse_time(row["created_at"]),
        )

    def submit_audit(self) -> None:
        """重新提交审核，只允许待审核或驳回状态。"""
        if self.status not in (ShopStatus.PENDING, ShopStatus.REJECTED):
            raise InvalidTransitionError(f"店铺当前为「{self.status}」，无需重复提交审核")
        self.status = ShopStatus.PENDING
        self.audit_remark = ""

    def approve(self, remark: str = "资质审核通过") -> None:
        """管理员审核通过，店铺进入营业状态。"""
        if self.status != ShopStatus.PENDING:
            raise InvalidTransitionError("只有待审核店铺可以审核通过")
        self.status = ShopStatus.OPEN
        self.audit_remark = remark

    def reject(self, remark: str) -> None:
        """管理员驳回审核。"""
        if self.status != ShopStatus.PENDING:
            raise InvalidTransitionError("只有待审核店铺可以驳回")
        self.status = ShopStatus.REJECTED
        self.audit_remark = remark

    def open(self) -> None:
        """开始营业。"""
        if self.status != ShopStatus.CLOSED:
            raise InvalidTransitionError(f"店铺当前为「{self.status}」，不能开始营业")
        self.status = ShopStatus.OPEN

    def close(self) -> None:
        """暂停营业。"""
        if self.status != ShopStatus.OPEN:
            raise InvalidTransitionError(f"店铺当前为「{self.status}」，不能暂停营业")
        self.status = ShopStatus.CLOSED

    def can_order(self) -> bool:
        """顾客能否在本店下单。"""
        return self.status == ShopStatus.OPEN

    @property
    def status_text(self) -> str:
        """状态文本。"""
        return str(self.status)
