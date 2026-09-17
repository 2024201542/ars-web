"""结构化日志配置。

使用方式:
    from logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("something happened", extra={"session_id": "..."})
"""

import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


# 日志格式: 时间 - 模块 - 级别 - 消息
_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志目录
_LOG_DIR = Path(__file__).parent / "logs"


class SensitiveDataFilter(logging.Filter):
    """过滤日志中的敏感信息（API Key 等）。"""

    _SENSITIVE_KEYS = {
        "api_key", "anthropic_api_key", "moonshot_api_key",
        "zhipu_api_key", "deepseek_api_key", "qwen_api_key",
        "s2_api_key", "authorization", "x-api-key",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        # 检查消息和 extra 字段中是否包含敏感 key
        msg = record.getMessage().lower()
        for key in self._SENSITIVE_KEYS:
            if key in msg:
                record.msg = record.msg.replace(key, "***REDACTED***")
                record.msg = _sanitize(record.msg)
                break
        return True


def _sanitize(text: str) -> str:
    """简单脱敏：移除可能的 API Key 格式。"""
    import re
    # sk-ant-xxx, sk-xxx 格式
    text = re.sub(r'sk-[a-zA-Z0-9_-]{20,}', '***REDACTED_KEY***', text)
    return text


def setup_logging(level: str = "INFO") -> None:
    """初始化全局日志配置。

    在 main.py 的 lifespan 中调用。
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler（避免重复添加）
    root_logger.handlers.clear()

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT))
    console_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(console_handler)

    # 文件 handler（滚动日志，最大 10MB × 5 个备份）
    try:
        file_handler = RotatingFileHandler(
            _LOG_DIR / "ars-web.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT))
        file_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(file_handler)
    except OSError:
        pass  # 文件日志不可用时仅使用控制台


def get_logger(name: str) -> logging.Logger:
    """获取指定模块的 logger。"""
    return logging.getLogger(name)
