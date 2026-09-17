"""会话状态管理 —— SQLite 持久化（连接池优化版）"""

import asyncio
import json
import uuid
import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator

from config import DB_PATH, encrypt_value, decrypt_value

# 需要加密存储的 key 名称列表
_ENCRYPTED_SETTING_KEYS = {
    "anthropic_api_key",
    "moonshot_api_key",
    "zhipu_api_key",
    "deepseek_api_key",
    "qwen_api_key",
    "s2_api_key",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabasePool:
    """SQLite 连接池，提高并发性能。"""
    
    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._initialized = False
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """初始化连接池。"""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            for _ in range(self.pool_size):
                conn = await aiosqlite.connect(self.db_path)
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA foreign_keys=ON")
                await conn.execute("PRAGMA busy_timeout=5000")  # 5秒超时
                conn.row_factory = aiosqlite.Row
                await self._pool.put(conn)
            
            self._initialized = True
    
    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """获取数据库连接（上下文管理器）。"""
        if not self._initialized:
            await self.initialize()
        
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)
    
    async def close(self):
        """关闭所有连接。"""
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()


class StateTracker:
    """管理会话状态，持久化到 SQLite。

    使用连接池提高并发性能，避免单连接瓶颈。
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        self._initialized = False
        self._pool = DatabasePool(self.db_path, pool_size=5)
        self._lock = asyncio.Lock()

    async def _execute(self, sql: str, params=None):
        """执行 SQL 语句，写操作自动提交（确保提交在同一连接上）。"""
        async with self._pool.get_connection() as db:
            if params is not None:
                cursor = await db.execute(sql, params)
            else:
                cursor = await db.execute(sql)
            # 写操作自动在同一连接上提交，避免跨连接提交导致数据丢失
            upper = sql.strip().upper()
            if any(upper.startswith(kw) for kw in ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP')):
                await db.commit()
            return cursor

    async def _fetchall(self, sql: str, params=None) -> list:
        """查询所有结果。"""
        async with self._pool.get_connection() as db:
            if params is not None:
                cursor = await db.execute(sql, params)
            else:
                cursor = await db.execute(sql)
            return await cursor.fetchall()

    async def _commit(self):
        """事务提交（保留接口兼容，写操作已在 _execute 中自动提交）。"""
        pass

    async def _ensure_initialized(self):
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            async with self._pool.get_connection() as db:
                await db.executescript("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        skill_name TEXT NOT NULL,
                        mode_name TEXT NOT NULL,
                        title TEXT,
                        status TEXT DEFAULT 'active',
                        passport TEXT,
                        current_phase TEXT,
                        user_id TEXT NOT NULL DEFAULT 'default',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT,
                        agent_name TEXT,
                        phase_name TEXT,
                        metadata TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        artifact_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        format TEXT DEFAULT 'markdown',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL DEFAULT 'default',
                        value TEXT,
                        updated_at TEXT NOT NULL
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_settings_user_key ON settings(user_id, key);
                    CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
                    CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
                    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                """)

                # Migration: add user_id columns if missing
                for tbl, col, defval in [("sessions", "user_id", "'default'"), ("settings", "user_id", "'default'")]:
                    try:
                        await db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT NOT NULL DEFAULT {defval}")
                    except Exception:
                        pass

                await db.commit()
            self._initialized = True

    # ── 会话管理 ──

    async def create_session(
        self, skill_name: str, mode_name: str, title: Optional[str] = None, user_id: str = "default"
    ) -> dict:
        await self._ensure_initialized()
        session_id = str(uuid.uuid4())
        now = _now()
        await self._execute(
            "INSERT INTO sessions (id, skill_name, mode_name, title, status, user_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (session_id, skill_name, mode_name, title or f"{skill_name} 会话", user_id, now, now),
        )
        await self._commit()
        return {
            "id": session_id,
            "skill_name": skill_name,
            "mode_name": mode_name,
            "title": title,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }

    async def list_sessions(self, page: int = 1, limit: int = 20, skill: str = "", user_id: str = "") -> dict:
        await self._ensure_initialized()
        offset = (page - 1) * limit
        wheres = []
        params = []
        if skill:
            wheres.append("skill_name = ?")
            params.append(skill)
        if user_id:
            wheres.append("user_id = ?")
            params.append(user_id)
        where_clause = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        rows = await self._fetchall(
            f"SELECT id, skill_name, mode_name, title, status, user_id, created_at, updated_at FROM sessions{where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        total_rows = await self._fetchall(f"SELECT COUNT(*) as cnt FROM sessions{where_clause}", params)
        total = total_rows[0][0] if total_rows else 0
        return {
            "data": [dict(r) for r in rows],
            "meta": {"total": total, "page": page, "limit": limit},
        }

    async def get_session(self, session_id: str) -> Optional[dict]:
        await self._ensure_initialized()
        rows = await self._fetchall(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        if not rows:
            return None
        return dict(rows[0])

    async def get_session_detail(self, session_id: str) -> Optional[dict]:
        session = await self.get_session(session_id)
        if not session:
            return None
        messages = await self.get_messages(session_id)
        artifacts = await self.get_artifacts(session_id)
        return {"session": session, "messages": messages, "artifacts": artifacts}

    async def update_session_status(self, session_id: str, status: str):
        await self._ensure_initialized()
        await self._execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), session_id),
        )
        await self._commit()

    async def update_session_phase(self, session_id: str, phase: str):
        await self._ensure_initialized()
        await self._execute(
            "UPDATE sessions SET current_phase = ?, updated_at = ? WHERE id = ?",
            (phase, _now(), session_id),
        )
        await self._commit()

    async def update_session_title(self, session_id: str, title: str):
        await self._ensure_initialized()
        await self._execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title.strip()[:120], _now(), session_id),
        )
        await self._commit()

    async def delete_session(self, session_id: str):
        await self._ensure_initialized()
        await self._execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))
        await self._execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._commit()


    # ── 消息管理 ──

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_name: Optional[str] = None,
        phase_name: Optional[str] = None,
        metadata: Optional[str] = None,
    ) -> int:
        await self._ensure_initialized()
        cursor = await self._execute(
            "INSERT INTO messages (session_id, role, content, agent_name, phase_name, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, agent_name, phase_name, metadata, _now()),
        )
        await self._commit()
        return cursor.lastrowid

    async def get_messages(self, session_id: str) -> list[dict]:
        await self._ensure_initialized()
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        return [dict(r) for r in rows]

    # ── 产出物管理 ──

    async def add_artifact(
        self, session_id: str, artifact_type: str, content: str, fmt: str = "markdown"
    ) -> int:
        await self._ensure_initialized()
        cursor = await self._execute(
            "INSERT INTO artifacts (session_id, artifact_type, content, format, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, artifact_type, content, fmt, _now()),
        )
        await self._commit()
        return cursor.lastrowid

    async def get_artifacts(self, session_id: str) -> list[dict]:
        await self._ensure_initialized()
        rows = await self._fetchall(
            "SELECT * FROM artifacts WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        return [dict(r) for r in rows]

    # ── 设置管理 ──

    async def get_setting(self, key: str, user_id: str = "default") -> Optional[str]:
        await self._ensure_initialized()
        rows = await self._fetchall(
            "SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key)
        )
        if not rows:
            return None
        value = rows[0][0]
        if key in _ENCRYPTED_SETTING_KEYS and value:
            try:
                return decrypt_value(value)
            except Exception:
                return value
        return value

    async def set_setting(self, key: str, value: str, user_id: str = "default"):
        await self._ensure_initialized()
        store_value = encrypt_value(value) if key in _ENCRYPTED_SETTING_KEYS else value
        now = _now()
        # UPDATE 优先（大多数场景 key 已存在），失败则 INSERT
        cursor = await self._execute(
            "UPDATE settings SET value = ?, updated_at = ? WHERE user_id = ? AND key = ?",
            (store_value, now, user_id, key),
        )
        if cursor.rowcount == 0:
            await self._execute(
                "INSERT INTO settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, key, store_value, now),
            )
        await self._commit()

    async def get_settings(self, user_id: str = "default") -> dict:
        await self._ensure_initialized()
        rows = await self._fetchall("SELECT key, value FROM settings WHERE user_id = ?", (user_id,))
        return {r[0]: r[1] for r in rows}

    # ── 跨域设置 (如 auth token) ──
    # 这些设置不属于任何具体用户，使用 "system" 作为 user_id
    _SYSTEM_USER = "system"

    async def get_setting_ex(self, scope: str, key: str) -> str | None:
        """获取 scope 域下的 key。"""
        await self._ensure_initialized()
        full_key = f"{scope}/{key}"
        rows = await self._fetchall(
            "SELECT value FROM settings WHERE user_id = ? AND key = ?",
            (self._SYSTEM_USER, full_key),
        )
        return rows[0][0] if rows else None

    async def set_setting_ex(self, scope: str, key: str, value: str):
        await self._ensure_initialized()
        full_key = f"{scope}/{key}"
        await self._execute(
            "DELETE FROM settings WHERE user_id = ? AND key = ?",
            (self._SYSTEM_USER, full_key),
        )
        await self._execute(
            "INSERT INTO settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (self._SYSTEM_USER, full_key, value, _now()),
        )
        await self._commit()

    async def delete_setting_ex(self, scope: str, key: str):
        await self._ensure_initialized()
        full_key = f"{scope}/{key}"
        await self._execute(
            "DELETE FROM settings WHERE user_id = ? AND key = ?",
            (self._SYSTEM_USER, full_key),
        )
        await self._commit()


    def _reset_for_test(self, db_path: str):
        """测试专用：重置单例状态以指向新的数据库。"""
        self.db_path = db_path
        self._initialized = False
        self._pool = DatabasePool(db_path, pool_size=5)


# 进程内共享单例，避免各 router 各自持有独立的 _initialized 状态
tracker = StateTracker()
