import json
from datetime import datetime

# 读取活动数据
with open("activity_list.json", "r", encoding="utf-8") as f:
    activities = json.load(f)

# 按运营商分组
operator_groups = {}
for act in activities:
    op = act["operator"]
    if op not in operator_groups:
        operator_groups[op] = []
    operator_groups[op].append(act)

# 读取更新日期
try:
    with open("update_time.txt", "r", encoding="utf-8") as f:
        update_date = f.read().strip()
except:
    update_date = datetime.now().strftime("%Y年%m月%d日 更新")

# 生成 Markdown 内容
md_content = f"""# 三大运营商免费流量领取攻略
> {update_date} | 人工整理·官方渠道·安全无套路

---

## 重要说明
1. 所有活动均为三大运营商官方免费活动，无需付费
2. 部分活动存在地域、套餐、网龄限制，以页面实际显示为准
3. 标注「APP内专属」的活动需在对应运营商手机APP中操作
4. 本资料仅为入口整理，不含任何代充、代领服务

---
"""

# 按运营商逐个生成
for op_name, op_acts in operator_groups.items():
    md_content += f"\n## {op_name}\n\n"
    for i, act in enumerate(op_acts, 1):
        # 标记活动类型
        tag = "【APP内专属】" if act.get("app_only", False) else "【网页/微信可领】"
        md_content += f"### {i}. {act['name']} {tag}\n"
        md_content += f"- **流量额度**：{act['flow']}\n"
        md_content += f"- **有效期**：{act['validity']}\n"
        
        # 有链接就显示，没有就提示APP内操作
        if act["url"].strip():
            md_content += f"- **官方入口**：{act['url']}\n"
        else:
            md_content += f"- **入口路径**：运营商APP内搜索对应名称\n"
        
        md_content += f"- **操作步骤**：{act['steps']}\n"
        md_content += f"- **注意事项**：{act['note']}\n\n"

# 结尾免责声明
md_content += """
---

## 免责声明
本攻略仅作信息分享，所有活动最终解释权归对应运营商所有。
若活动规则调整，请以官方最新说明为准。
"""

# 保存为 Markdown 文件
with open("三大运营商流量领取攻略.md", "w", encoding="utf-8") as f:
    f.write(md_content)

print("攻略生成完成！文件：三大运营商流量领取攻略.md")