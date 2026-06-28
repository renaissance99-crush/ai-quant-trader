"""GitHub Actions 诊断 —— 测试微信推送是否正常"""
import os
import requests

key = os.environ.get("SCT_KEY", "")
if not key:
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
if result.get("code") == 0:
    print("✅ 推送成功！请检查微信")
else:
    print(f"⚠️ 推送返回非0: {result}")
