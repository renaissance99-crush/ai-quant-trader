"""GitHub Actions 诊断 —— 测试微信推送是否正常"""
import os
import requests

key = os.environ.get("SCT_KEY", "")
if not key:
    # 回退到 wechat_notify.py 中的 key（代码里已配置正确的 key）
    try:
        from wechat_notify import SCT_KEY as fallback_key
        key = fallback_key
        if key:
            print(f"ℹ️ SCT_KEY 未设环境变量，使用 wechat_notify.py 中的 key")
        else:
            print("❌ SCT_KEY 环境变量未设置，且 wechat_notify.py 中也没有 key！")
            print("   请在 GitHub Settings → Secrets → Actions 中添加 SCT_KEY")
            exit(1)
    except ImportError:
        print("❌ SCT_KEY 环境变量未设置！")
        print("   请在 GitHub Settings → Secrets → Actions 中添加 SCT_KEY")
        exit(1)

print(f"✅ SCT_KEY 已设置 (长度: {len(key)})")
print("📱 发送测试推送...")

url = f"https://sctapi.ftqq.com/{key}.send"
r = requests.post(url, data={
    "title": "GitHub Actions 诊断",
    "desp": "如果你看到这条消息，说明 SCT_KEY 配置正确！AI 量化系统推送通道正常。",
}, timeout=15)

print(f"响应: {r.text[:300]}")
result = r.json()
code = result.get("code")
if code == 0:
    print("✅ 推送成功！请检查微信")
elif code == 40001:
    print(f"❌ SCT_KEY 无效（40001 错误的Key）！")
    print(f"   当前 key 前6位: {key[:6]}... 末尾: ...{key[-4:]}")
    print(f"   请在 GitHub Settings → Secrets → Actions → SCT_KEY 中更新为正确的 SendKey")
    print(f"   获取 SendKey: https://sct.ftqq.com/")
    exit(1)
else:
    print(f"❌ 推送失败 [{code}]: {result.get('message', result)}")
    exit(1)
