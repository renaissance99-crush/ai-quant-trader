import requests
import json
from datetime import datetime

# 读取活动清单
with open("activity_list.json", "r", encoding="utf-8") as f:
    activities = json.load(f)

# 模拟普通浏览器的请求头，降低被拦截概率
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

print("开始检测活动链接有效性...")
print("-" * 50)

valid_count = 0
invalid_list = []
skip_count = 0

for act in activities:
    # 双重判断：标记为仅APP内 或 没有网页链接的，直接跳过检测
    if act.get("app_only", False) or not act["url"].strip():
        status = "📱 仅APP内"
        skip_count += 1
        print(f"[{act['operator']}] {act['name']} → {status}")
        continue

    try:
        resp = requests.get(
            act["url"],
            headers=headers,
            timeout=8,
            allow_redirects=True,
            stream=True
        )
        # 200/301/302 都视为正常（运营商页面常有跳转）
        if resp.status_code in [200, 301, 302]:
            status = "✅ 正常"
            valid_count += 1
        else:
            status = f"❌ 异常(状态码 {resp.status_code})"
            invalid_list.append(act["name"])
    except Exception as e:
        status = "❌ 无法访问"
        invalid_list.append(act["name"])
    
    print(f"[{act['operator']}] {act['name']} → {status}")

print("-" * 50)
print(f"检测完成：共 {len(activities)} 个活动")
print(f"网页正常 {valid_count} 个 | 异常 {len(invalid_list)} 个 | 仅APP内 {skip_count} 个")
if invalid_list:
    print("异常活动列表：")
    for name in invalid_list:
        print(f"  - {name}")

# 保存更新日期，供生成攻略使用
with open("update_time.txt", "w", encoding="utf-8") as f:
    f.write(datetime.now().strftime("%Y年%m月%d日 更新"))