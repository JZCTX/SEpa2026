"""业务异常定义。

界面层只捕获 ``AppError``，把 ``message`` 原样提示给用户；其余未预期异常
说明是程序缺陷，应当在开发阶段暴露出来。
"""


class AppError(Exception):
    """所有可预期业务异常的基类。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(AppError):
    """参数校验失败。"""


class NotFoundError(AppError):
    """查询的对象不存在。"""


class PermissionDeniedError(AppError):
    """当前用户没有执行该操作的权限。"""


class ConflictError(AppError):
    """业务规则冲突，例如手机号已注册、店铺歇业。"""


class AuthError(AppError):
    """登录或会话校验失败。"""


class AccountLockedError(AuthError):
    """账号因连续输错密码被临时锁定。"""


class InvalidTransitionError(AppError):
    """订单或配送单不允许进行该状态转换。"""


class SoldOutError(ConflictError):
    """菜品库存不足或已售罄。"""


class PriceChangedError(ConflictError):
    """下单时菜品价格与加入购物车时不一致。"""

    def __init__(self, dish_name: str, old_price: str, new_price: str) -> None:
        message = (
            f"菜品「{dish_name}」价格已由 {old_price} 元调整为 {new_price} 元，"
            "请刷新购物车后重新确认"
        )
        super().__init__(message)
        self.dish_name = dish_name
        self.old_price = old_price
        self.new_price = new_price
