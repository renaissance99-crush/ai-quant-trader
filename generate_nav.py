import json
from datetime import datetime

# 读取活动数据
with open("activity_list.json", "r", encoding="utf-8") as f:
    activities = json.load(f)

# 按运营商分组（保持JSON原始顺序，按出现顺序分组）
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
except (FileNotFoundError, OSError):
    update_date = datetime.now().strftime("%Y年%m月%d日 更新")

# 类型对应中文标签
type_label = {
    "browser": "浏览器直达",
    "wechat": "微信内打开",
    "app": "APP内操作"
}


def get_activity_type(act):
    """优先使用JSON中的type字段，否则从app_only/url字段推断"""
    if "type" in act and act["type"] in type_label:
        return act["type"]
    # 回退：从数据推断类型
    if act.get("app_only") or not act.get("url", "").strip():
        return "app"
    url = act["url"].lower()
    if "wx." in url or "wechat" in url or "weixin" in url:
        return "wechat"
    return "browser"

# 生成HTML内容
html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>三大运营商流量领取导航</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f7fa;
            color: #333;
            padding-bottom: 40px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px 20px;
            text-align: center;
        }}
        .header h1 {{ font-size: 22px; margin-bottom: 8px; }}
        .header p {{ font-size: 13px; opacity: 0.9; }}
        .container {{ padding: 15px; }}
        .section {{ margin-bottom: 20px; }}
        .section-title {{
            font-size: 17px;
            font-weight: bold;
            margin: 10px 5px 12px;
            padding-left: 8px;
            border-left: 4px solid #667eea;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        .card-title {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .tag {{
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            color: white;
        }}
        .tag-browser {{ background: #52c41a; }}
        .tag-wechat {{ background: #07c160; }}
        .tag-app {{ background: #faad14; }}
        .card-desc {{
            font-size: 13px;
            color: #666;
            margin-bottom: 8px;
            line-height: 1.5;
        }}
        .btn {{
            display: block;
            width: 100%;
            padding: 10px;
            text-align: center;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
        }}
        .btn-gray {{
            background: #ccc;
            pointer-events: none;
        }}
        .notice {{
            background: #fffbe6;
            border: 1px solid #ffe58f;
            border-radius: 8px;
            padding: 12px;
            margin: 15px;
            font-size: 12px;
            line-height: 1.6;
            color: #874d00;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #999;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>三大运营商免费流量导航</h1>
        <p>{update_date} · 官方入口 · 安全直达</p>
    </div>

    <div class="notice">
        <strong>重要说明：</strong><br>
        1. 所有入口均为运营商官方活动，免费领取，无需付费<br>
        2. 部分活动存在地域、套餐限制，以页面实际显示为准<br>
        3. 「APP内操作」需在对应运营商手机APP中查找入口
    </div>

    <div class="container">
"""

# 逐个运营商生成卡片
for op_name, op_acts in operator_groups.items():
    html_content += f'        <div class="section">\n'
    html_content += f'            <div class="section-title">{op_name}</div>\n'
    
    for act in op_acts:
        act_type = get_activity_type(act)
        tag_class = f"tag-{act_type}"
        tag_text = type_label.get(act_type, "未知")
        
        if act['url'].strip():
            btn_html = f'<a href="{act["url"]}" target="_blank" class="btn">直达领取页</a>'
        else:
            btn_html = f'<div class="btn btn-gray">APP内操作</div>'
        
        html_content += f"""
        <div class="card">
            <div class="card-title">
                {act['name']}
                <span class="tag {tag_class}">{tag_text}</span>
            </div>
            <div class="card-desc">
                流量：{act['flow']}<br>
                说明：{act['note']}
            </div>
            {btn_html}
        </div>
"""
    html_content += '        </div>\n'

# 结尾
html_content += f"""
    </div>

    <div class="footer">
        本页面仅作官方入口汇总，所有活动最终解释权归对应运营商所有
    </div>
</body>
</html>
"""

# 保存HTML文件
with open("流量领取导航页.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print("导航页生成完成！文件：流量领取导航页.html")