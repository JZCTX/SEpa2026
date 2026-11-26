"""密码哈希与会话管理。

密码使用 PBKDF2-HMAC-SHA256 加随机盐做不可逆哈希，符合 REQ-016 对
“密码不得明文存储”的要求；登录成功后签发随机令牌，服务层据此校验身份。
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from takeout import config
from takeout.enums import UserRole
from takeout.errors import AuthError
from takeout.utils import now

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 240_000


def hash_password(password: str) -> str:
    """生成 ``pbkdf2_sha256$迭代次数$盐$摘要`` 格式的密码哈希。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    )
    return f"{ALGORITHM}${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码与存储的哈希是否匹配。"""
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


@dataclass(frozen=True)
class Session:
    """登录态：后续服务调用都携带该对象做角色与数据归属校验。"""

    user_id: int
    phone: str
    role: UserRole
    shop_id: int | None = None
    display_name: str = ""


@dataclass(frozen=True)
class Token:
    """登录令牌，对应 UML 中 ``login()`` 的返回值。"""

    value: str
    session: Session
    issued_at: datetime
    expires_at: datetime

    @property
    def expired(self) -> bool:
        """令牌是否过期。"""
        return now() >= self.expires_at


class SessionStore:
    """进程内令牌表。

    命令行程序只有一个进程，使用内存字典即可；令牌随进程退出失效，
    不会把口令或身份信息写入磁盘。
    """

    def __init__(self) -> None:
        self._tokens: dict[str, Token] = {}

    def issue(self, session: Session) -> Token:
        """签发新令牌。"""
        issued = now()
        token = Token(
            value=secrets.token_urlsafe(24),
            session=session,
            issued_at=issued,
            expires_at=issued + timedelta(hours=config.TOKEN_HOURS),
        )
        self._tokens[token.value] = token
        return token

    def resolve(self, value: str) -> Session:
        """根据令牌取得会话，过期或不存在时抛出异常。"""
        token = self._tokens.get(value)
        if token is None:
            raise AuthError("登录状态无效，请重新登录")
        if token.expired:
            self._tokens.pop(value, None)
            raise AuthError("登录已过期，请重新登录")
        return token.session

    def revoke(self, value: str) -> None:
        """注销令牌。"""
        self._tokens.pop(value, None)

    def clear(self) -> None:
        """清空全部令牌，测试使用。"""
        self._tokens.clear()
