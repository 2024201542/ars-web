"""用户管理器 — 注册、登录、认证中间件"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import Request, HTTPException

from services.state_tracker import tracker as state_tracker


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str) -> str:
    """PBKDF2-SHA256 + salt 密码哈希 (10 万次迭代)。"""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return f"pbkdf2:{salt}:{h}"


def _verify_password(password: str, stored: str) -> bool:
    """验证密码（兼容 sha256 旧格式 + pbkdf2 新格式）。"""
    try:
        algo, salt, h = stored.split(":", 2)
        if algo == "pbkdf2":
            expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
            return secrets.compare_digest(h, expected)
        if algo == "sha256":
            expected = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
            return secrets.compare_digest(h, expected)
        return False
    except ValueError:
        return False


def _generate_token() -> str:
    return secrets.token_hex(32)


class UserManager:
    """用户认证与管理。"""

    def __init__(self, tracker):
        self.tracker = tracker

    async def init_user_table(self):
        """初始化 users 表。"""
        await self.tracker._ensure_initialized()
        await self.tracker._execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                display_name TEXT,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
        """)
        await self.tracker._commit()

    async def init_token_table(self):
        """token 存 settings 表，scope='auth_token'。"""
        pass  # settings 表已支持 (user_id, key, value)

    async def register(self, username: str, password: str, display_name: str = "", role: str = "user") -> dict:
        """注册新用户。"""
        await self.init_user_table()

        user_id = str(uuid.uuid4())
        password_hash = _hash_password(password)
        now = _now()

        # 检查是否首个用户（首个自动变 admin）
        rows = await self.tracker._fetchall("SELECT COUNT(*) as cnt FROM users")
        if not rows or rows[0][0] == 0:
            role = "admin"

        # 检查用户名唯一性
        exist = await self.tracker._fetchall("SELECT id FROM users WHERE username = ?", (username,))
        if exist:
            raise ValueError(f"用户名 '{username}' 已被使用")

        await self.tracker._execute(
            "INSERT INTO users (id, username, password_hash, role, display_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, password_hash, role, display_name or username, now),
        )
        await self.tracker._commit()

        # 创建默认 admin 时同时初始化邀请码（可选）
        return {"id": user_id, "username": username, "role": role}

    async def login(self, username: str, password: str) -> dict:
        """登录，返回 token + 用户信息。"""
        await self.init_user_table()

        rows = await self.tracker._fetchall(
            "SELECT id, username, password_hash, role, display_name FROM users WHERE username = ?",
            (username,),
        )
        if not rows:
            raise ValueError("用户名或密码错误")

        user = dict(rows[0])
        if not _verify_password(password, user["password_hash"]):
            raise ValueError("用户名或密码错误")

        # 生成 token
        token = _generate_token()
        now = _now()

        # 存 token → user_id 映射到 settings (key: auth_token/{token})
        await self.tracker.set_setting_ex("auth", f"auth_token/{token}", user["id"])

        # 更新最后登录时间
        await self.tracker._execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (now, user["id"]),
        )
        await self.tracker._commit()

        return {
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user.get("display_name") or user["username"],
                "role": user["role"],
                "created_at": "",
            },
        }

    async def get_user_by_token(self, token: str) -> dict | None:
        """通过 token 获取用户信息。"""
        user_id = await self.tracker.get_setting_ex("auth", f"auth_token/{token}")
        if not user_id:
            return None

        rows = await self.tracker._fetchall(
            "SELECT id, username, role, display_name, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        if not rows:
            return None
        return dict(rows[0])

    async def logout(self, token: str):
        """登出，删除 token。"""
        await self.tracker.delete_setting_ex("auth", f"auth_token/{token}")

    # ── 管理员方法 ──

    async def list_users(self) -> list[dict]:
        await self.init_user_table()
        rows = await self.tracker._fetchall(
            "SELECT id, username, role, display_name, created_at, last_login_at FROM users ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def get_user_sessions(self, target_user_id: str) -> list[dict]:
        return await self.tracker.list_sessions(1, 200, user_id=target_user_id)

    async def create_user(self, username: str, password: str, display_name: str = "", role: str = "user") -> dict:
        return await self.register(username, password, display_name, role)

    async def delete_user(self, target_user_id: str):
        await self.init_user_table()
        await self.tracker._execute("DELETE FROM users WHERE id = ?", (target_user_id,))
        await self.tracker._execute("DELETE FROM sessions WHERE user_id = ?", (target_user_id,))
        await self.tracker._execute("DELETE FROM settings WHERE user_id = ?", (target_user_id,))
        await self.tracker._commit()

    async def get_stats(self) -> dict:
        users = await self.tracker._fetchall("SELECT COUNT(*) as cnt FROM users")
        sessions = await self.tracker._fetchall("SELECT COUNT(*) as cnt FROM sessions")
        return {
            "user_count": users[0][0] if users else 0,
            "session_count": sessions[0][0] if sessions else 0,
        }


# 全局单例
user_manager = UserManager(state_tracker)


# ── FastAPI 认证中间件依赖 ──

async def _resolve_user_from_request(request: Request) -> dict | None:
    """从请求中解析用户（支持 Authorization header 和 ?token= query 参数）。"""
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        # 回退到 query 参数（用于 img/iframe/a 等无法带 header 的场景）
        token = request.query_params.get("token", "")
    if not token:
        return None
    user = await user_manager.get_user_by_token(token)
    if user:
        request.state.user_id = user["id"]
        request.state.user_role = user["role"]
    return user


async def get_current_user(request: Request) -> dict:
    """FastAPI 依赖：从 Authorization header 获取当前用户。"""
    user = await _resolve_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录，请先登录")
    return user


async def get_admin_user(request: Request) -> dict:
    """FastAPI 依赖：仅管理员可访问。"""
    user = await get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def get_user_id(request: Request) -> str:
    """FastAPI 依赖：从 Authorization header 获取 user_id（同时支持 ?token= query 回退）。"""
    # 优先从 header，回退到 query param
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = request.query_params.get("token", "")

    if token:
        user = await user_manager.get_user_by_token(token)
        if user:
            request.state.user_id = user["id"]
            return user["id"]
    raise HTTPException(status_code=401, detail="未登录")


async def get_optional_user(request: Request) -> str | None:
    """FastAPI 依赖：可选的用户认证。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        user = await user_manager.get_user_by_token(token)
        if user:
            request.state.user_id = user["id"]
            return user["id"]
    return None
