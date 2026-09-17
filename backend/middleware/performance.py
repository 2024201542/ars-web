"""性能监控中间件"""

import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

_logger = logging.getLogger(__name__)


class PerformanceMonitorMiddleware(BaseHTTPMiddleware):
    """性能监控中间件，记录慢请求和性能指标。"""
    
    # 慢请求阈值（秒）
    SLOW_REQUEST_THRESHOLD = 1.0
    
    async def dispatch(self, request: Request, call_next):
        # 记录开始时间
        start_time = time.time()
        
        # 执行请求
        response = await call_next(request)
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 添加处理时间到响应头
        response.headers["X-Process-Time"] = f"{process_time:.3f}"
        
        # 记录慢请求
        if process_time > self.SLOW_REQUEST_THRESHOLD:
            _logger.warning(
                f"慢请求警告: {request.method} {request.url.path} "
                f"耗时 {process_time:.2f}s "
                f"状态码 {response.status_code}"
            )
        
        # 记录所有请求的性能数据（可选）
        if request.url.path.startswith("/api/"):
            _logger.info(
                f"请求统计: {request.method} {request.url.path} "
                f"{process_time:.3f}s {response.status_code}"
            )
        
        return response
