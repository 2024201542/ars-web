"""输入验证中间件 - 防止注入攻击和恶意输入"""

import re
import html
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional
import logging

_logger = logging.getLogger(__name__)

# 危险字符模式
DANGEROUS_PATTERNS = [
    r'<script[^>]*>.*?</script>',  # XSS
    r'javascript:',  # JavaScript 协议
    r'on\w+\s*=',  # 事件处理器
    r'union\s+select',  # SQL 注入
    r'insert\s+into',
    r'delete\s+from',
    r'drop\s+table',
    r'exec\s*\(',
    r'eval\s*\(',
]

# 最大输入长度限制
MAX_INPUT_LENGTHS = {
    'message': 50000,
    'title': 200,
    'skill_name': 50,
    'mode_name': 50,
    'username': 50,
    'password': 100,
}


def sanitize_input(text: str, max_length: Optional[int] = None) -> str:
    """清理输入文本，防止注入攻击。"""
    if not text:
        return text
    
    # 长度限制
    if max_length and len(text) > max_length:
        raise HTTPException(status_code=400, detail=f"输入长度超过限制（最大 {max_length} 字符）")
    
    # HTML 转义
    sanitized = html.escape(text)
    
    # 检查危险模式
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            _logger.warning(f"检测到潜在恶意输入: {pattern}")
            raise HTTPException(status_code=400, detail="输入包含不允许的内容")
    
    return sanitized


class InputValidationMiddleware(BaseHTTPMiddleware):
    """输入验证中间件。"""
    
    async def dispatch(self, request: Request, call_next):
        # 只检查需要验证的路由
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                # 读取请求体
                body = await request.body()
                # 将 body 缓存回 request，避免下游路由无法读取
                request._body = body
                if body:
                    import json
                    try:
                        data = json.loads(body)
                        # 验证输入
                        self._validate_data(data, request.url.path)
                    except json.JSONDecodeError:
                        pass  # 非 JSON 数据，跳过验证
            except Exception as e:
                _logger.error(f"输入验证失败: {e}")
                raise HTTPException(status_code=400, detail="请求格式错误")

        return await call_next(request)
    
    def _validate_data(self, data: dict, path: str):
        """验证请求数据。"""
        # 验证消息内容
        if 'message' in data:
            sanitize_input(data['message'], MAX_INPUT_LENGTHS['message'])
        
        # 验证标题
        if 'title' in data:
            sanitize_input(data['title'], MAX_INPUT_LENGTHS['title'])
        
        # 验证用户名
        if 'username' in data:
            sanitize_input(data['username'], MAX_INPUT_LENGTHS['username'])
        
        # 验证密码
        if 'password' in data:
            sanitize_input(data['password'], MAX_INPUT_LENGTHS['password'])
        
        # 验证技能名称
        if 'skill_name' in data:
            sanitize_input(data['skill_name'], MAX_INPUT_LENGTHS['skill_name'])
        
        # 验证模式名称
        if 'mode_name' in data:
            sanitize_input(data['mode_name'], MAX_INPUT_LENGTHS['mode_name'])
