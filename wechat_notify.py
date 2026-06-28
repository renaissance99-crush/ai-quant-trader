"""
============================================
微信推送通知模块 —— Server酱 直连版
============================================
本地使用：直接改下面的 SCT_KEY
GitHub Actions：设置 Secret SCT_KEY 即可
"""

import requests
import os

# ==========================
# 配置 —— 优先从环境变量读取
# ==========================

SCT_KEY = os.environ.get("SCT_KEY") or ""
ENABLE_PUSH = os.environ.get("ENABLE_PUSH", "true").lower() != "false"


def _push(title, desp, tags=""):
    """
    Server酱 · 直接 HTTP 调用
    API 文档: https://sct.ftqq.com/
    """
    if not ENABLE_PUSH:
        print("🔕 微信推送已关闭")
        return None

    url = f"https://sctapi.ftqq.com/{SCT_KEY}.send"

    data = {
        "title": title,
        "desp": desp,
    }
    if tags:
        data["tags"] = tags

    try:
        resp = requests.post(url, data=data, timeout=15)
        result = resp.json()
        code = result.get("code")
        msg = result.get("message", str(result))

        if code == 0:
            print(f"📱 微信推送成功: {msg}")
        else:
            print(f"📱 微信推送失败 [{code}]: {msg}")
            print(f"   完整响应: {resp.text[:300]}")

        return result
    except requests.exceptions.Timeout:
        print("⚠️ 推送超时: 15秒内无响应，检查 SCT_KEY 或网络")
        return None
    except Exception as e:
        print(f"⚠️ 推送异常: {e}")
        return None


def send_simple_alert(title, content, tags="量化提醒"):
    """发送简单提醒"""
    return _push(title, content, tags=tags)
