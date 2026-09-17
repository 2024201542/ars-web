"""ARS Web 后端入口 —— FastAPI 应用"""

import os
import sys
import pathlib

# 将 backend 目录加入 Python 路径
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from deps import limiter
from routers import session, chat, export, skills, settings_router, proxy, workspace, auth, admin, share


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化，关闭时清理。"""
    from logging_config import setup_logging

    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))

    from services.export_cleaner import start_cleanup_scheduler, stop_cleanup_scheduler
    start_cleanup_scheduler()
    yield
    await stop_cleanup_scheduler()


app = FastAPI(
    title="ARS Web API",
    description="Academic Research Skills Web API - 学术研究助手后端服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置 - 安全优化

# 从环境变量读取允许的域名，多个域名用逗号分隔
# 开发环境默认允许 localhost，生产环境必须明确配置
_allowed_origins_str = os.environ.get("ALLOWED_ORIGINS", "")
if _allowed_origins_str:
    ALLOWED_ORIGINS = [origin.strip() for origin in _allowed_origins_str.split(",") if origin.strip()]
else:
    # 开发环境默认配置
    ALLOWED_ORIGINS = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://8.160.123.92:5173",
        "http://8.160.123.92",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 速率限制中间件
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# 输入验证中间件
from middleware.validation import InputValidationMiddleware
app.add_middleware(InputValidationMiddleware)

# 性能监控中间件
from middleware.performance import PerformanceMonitorMiddleware
app.add_middleware(PerformanceMonitorMiddleware)

# 请求审计日志中间件
from starlette.middleware.base import BaseHTTPMiddleware
from logging_config import get_logger
_audit_log = get_logger("audit")

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if "/chat" in path or "/settings" in path or path.startswith("/api/admin"):
            uid = getattr(request.state, "user_id", "anon")
            label = uid[:12] if uid and uid != "anon" else "anon"
            _audit_log.info("%s | %s %s | %d", label, request.method, path, response.status_code)
        return response

app.add_middleware(AuditMiddleware)

# 注册路由 — 公开路由放前面
app.include_router(auth.router)
app.include_router(skills.router)
app.include_router(proxy.router)

# 需要认证的路由
app.include_router(session.router)
app.include_router(chat.router)
app.include_router(export.router)
app.include_router(share.router)
app.include_router(settings_router.router)
app.include_router(workspace.router)
app.include_router(admin.router)


@app.get("/api/health")
async def health_check():
    """健康检查接口。"""
    return {"status": "ok", "version": "1.0.0"}
