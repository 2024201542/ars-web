"""应用配置管理"""

import os
import pathlib

# 项目根目录 (ars-web/)
PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()


def _default_skills_path() -> pathlib.Path:
    """解析 ARS 技能目录：支持 monorepo 与旁挂两种布局。"""
    env = os.environ.get("ARS_SKILLS_PATH")
    if env:
        return pathlib.Path(env)

    # 布局 A：ars-web 嵌在技能仓库内（如 academic-research-skills-main/ars-web）
    monorepo = PROJECT_ROOT.parent
    if (monorepo / "deep-research" / "SKILL.md").exists():
        return monorepo

    # 布局 B：技能仓库与 ars-web 并列（文档默认）
    sibling = PROJECT_ROOT.parent / "academic-research-skills"
    return sibling


# ARS 技能套件路径
ARS_SKILLS_PATH = _default_skills_path()

# SQLite 数据库路径
DB_PATH = pathlib.Path(
    os.environ.get("ARS_WEB_DB_PATH", str(PROJECT_ROOT / "backend" / "data" / "ars.db"))
)

# Fernet 加密密钥 (用于加密存储 API Key)
# 安全优化：生产环境必须通过环境变量提供密钥
import base64
import logging
from cryptography.fernet import Fernet as _Fernet

_logger = logging.getLogger(__name__)

def _get_encryption_key() -> bytes:
    """获取加密密钥，优先级：环境变量 > 密钥文件 > 开发环境自动生成"""
    import hashlib

    # 1. 优先从环境变量获取
    env_key = os.environ.get("ARS_WEB_SECRET_KEY", "")
    if env_key:
        _logger.info("使用环境变量 ARS_WEB_SECRET_KEY 作为加密密钥")
        # 如果是 44 字符且以 '=' 结尾，视为已格式化的 Fernet 密钥
        if len(env_key) == 44 and env_key.endswith('='):
            return env_key.encode()
        # 否则使用 SHA256 派生 32 字节密钥，再 base64 编码为 Fernet 格式
        derived = hashlib.sha256(env_key.encode()).digest()
        return base64.urlsafe_b64encode(derived)
    
    # 2. 检查是否为生产环境
    is_production = os.environ.get("ENVIRONMENT", "development").lower() in ("production", "prod", "live")
    if is_production:
        raise ValueError(
            "生产环境必须设置 ARS_WEB_SECRET_KEY 环境变量！"
            "请生成密钥：python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    
    # 3. 开发环境：尝试从密钥文件读取
    _KEY_FILE = DB_PATH.parent / ".fernet_key"
    if _KEY_FILE.exists():
        _logger.warning("开发环境使用密钥文件（不推荐生产环境使用）")
        return _KEY_FILE.read_bytes()
    
    # 4. 开发环境：自动生成密钥并保存
    _logger.warning("开发环境自动生成加密密钥（仅用于开发测试）")
    generated_key = _Fernet.generate_key()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_bytes(generated_key)
    # 设置文件权限为仅所有者可读写
    os.chmod(_KEY_FILE, 0o600)
    return generated_key

# 初始化 Fernet 实例
try:
    _FERNET = _Fernet(_get_encryption_key())
except Exception as e:
    _logger.error(f"初始化加密密钥失败: {e}")
    raise


def encrypt_value(plain: str) -> str:
    """Fernet 加密，返回 base64 密文。"""
    return _FERNET.encrypt(plain.encode()).decode()


def decrypt_value(cipher: str) -> str:
    """Fernet 解密，返回明文。"""
    return _FERNET.decrypt(cipher.encode()).decode()

# 默认模型（当用户未在设置中选择时使用）
DEFAULT_MODEL = "deepseek-chat"

# 速率限制
RATE_LIMIT_CHAT_PER_MINUTE = 30
RATE_LIMIT_EXPORT_PER_HOUR = 20

# 消息长度限制
MAX_MESSAGE_LENGTH = 50000

# Claude CLI 代理端点（非 Anthropic 模型通过此端点翻译为 OpenAI 格式）
PROXY_BASE_URL = os.environ.get("ARS_WEB_PROXY_URL", "http://localhost:8000/v1/proxy")

# 工作区目录
WORKSPACE_DIR = pathlib.Path(
    os.environ.get("ARS_WORKSPACE_DIR", str(PROJECT_ROOT / "backend" / "data" / "workspaces"))
)

# 确保数据目录存在
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
