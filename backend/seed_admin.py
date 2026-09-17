#!/usr/bin/env python3
"""初始化管理员账号。API Key 请在 Web 设置页面自行配置。"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from services.user_manager import user_manager
from services.state_tracker import tracker

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_DISPLAY_NAME = os.environ.get("ADMIN_DISPLAY_NAME", "管理员")

# 可选的初始化 DeepSeek Key（仅当环境变量设置时）
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

async def main():
    # 创建管理员
    try:
        await user_manager.register(ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_DISPLAY_NAME)
        print(f"[OK] 管理员账号已创建: {ADMIN_USERNAME}")
    except ValueError:
        print(f"[OK] 管理员账号已存在: {ADMIN_USERNAME}")

    # 登录获取 user_id
    r = await user_manager.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    uid = r['user']['id']
    print(f"[OK] 登录成功, user_id={uid[:12]}...")

    # 如果提供了 DeepSeek API Key，则预置
    if DEEPSEEK_KEY:
        await tracker.set_setting('deepseek_api_key', DEEPSEEK_KEY, uid)
        await tracker.set_setting('model', 'deepseek-chat', uid)
        print("[OK] DeepSeek API Key 已预置")
        # 验证
        val = await tracker.get_setting('deepseek_api_key', uid)
        if val and val.startswith('sk-'):
            print("[OK] 验证通过: Key 已正确保存")
        else:
            print(f"[警告] 验证失败: 读取到的值异常")
    else:
        print("[提示] 未设置 DEEPSEEK_API_KEY 环境变量，跳过 Key 预置")
        print("       请在 Web 设置页面手动配置 API Key")

if __name__ == '__main__':
    asyncio.run(main())
