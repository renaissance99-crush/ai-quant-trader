"""
============================================
AI 交易确认服务器 —— 手机点一下，确认/拒绝交易
============================================

启动方式：
  python confirm_server.py            # 默认 0.0.0.0:5000（局域网可访问）
  python confirm_server.py --local    # 仅 127.0.0.1:5000（本机访问）

微信推送的确认链接指向此服务。用户点击后：
  /confirm/<token>?action=yes  → 确认交易，记录到持仓
  /confirm/<token>?action=no   → 拒绝交易
  /status                      → 查看当前状态
"""

import sys
import os
import json
from datetime import datetime, date

try:
    from flask import Flask, request, redirect, render_template_string
except ImportError:
    print("❌ 需要安装 flask: pip install flask")
    sys.exit(1)

# 路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PENDING_FILE = os.path.join(BASE_DIR, "pending_trades.json")
HOLDINGS_FILE = os.path.join(BASE_DIR, "holdings.json")
DAILY_LIMITS_FILE = os.path.join(BASE_DIR, "daily_limits.json")

app = Flask(__name__)

# ========================================
# 页面模板
# ========================================

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 量化交易 · 确认</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f5f7fa;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; padding: 20px;
        }
        .card {
            background: white; border-radius: 16px;
            padding: 30px 24px; max-width: 400px; width: 100%;
            box-shadow: 0 4px 16px rgba(0,0,0,0.08);
            text-align: center;
        }
        .icon { font-size: 60px; margin-bottom: 16px; }
        .title { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
        .info { font-size: 14px; color: #666; margin-bottom: 4px; }
        .reason {
            background: #fffbe6; border: 1px solid #ffe58f;
            border-radius: 8px; padding: 10px; margin: 16px 0;
            font-size: 13px; color: #874d00; line-height: 1.5;
        }
        .btn-row { display: flex; gap: 12px; margin-top: 20px; }
        .btn {
            flex: 1; padding: 12px; border-radius: 10px;
            font-size: 16px; font-weight: 600; border: none; cursor: pointer;
            text-decoration: none; display: block; text-align: center;
        }
        .btn-yes { background: #52c41a; color: white; }
        .btn-no { background: #ff4d4f; color: white; }
        .note { font-size: 12px; color: #999; margin-top: 16px; }
    </style>
</head>
<body>
    <div class="card">
        {{ content | safe }}
    </div>
</body>
</html>"""


# ========================================
# 辅助函数
# ========================================

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return default if default is not None else []

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def process_confirmation(token, confirmed):
    """处理确认/拒绝，更新持仓和待确认列表"""
    pending = load_json(PENDING_FILE, [])
    trade = next((t for t in pending if t.get("token") == token and t.get("status") == "pending"), None)

    if not trade:
        return None, "该交易已处理或不存在"

    if confirmed:
        # 更新持仓
        holdings = load_json(HOLDINGS_FILE, {"positions": [], "cash_available": 50000, "total_invested": 0})
        limits = load_json(DAILY_LIMITS_FILE, {"date": date.today().isoformat(), "total_bought": 0, "trade_count": 0})

        code = trade["code"]
        name = trade["name"]
        amount = trade["amount"]

        if trade["action"] == "buy":
            # 从可用资金扣减
            holdings["cash_available"] = holdings.get("cash_available", 0) - amount
            holdings["total_invested"] = holdings.get("total_invested", 0) + amount
            limits["total_bought"] = limits.get("total_bought", 0) + amount
            limits["trade_count"] = limits.get("trade_count", 0) + 1

            # 估算份额（按最近净值，实际会有出入）
            from ai_tools import _fetch_fund_hist
            df = _fetch_fund_hist(code, days=5)
            cost_nav = float(df["nav"].iloc[-1]) if df is not None and len(df) > 0 else 1.0
            shares = amount / cost_nav

            holdings["positions"].append({
                "code": code,
                "name": name,
                "shares": round(shares, 2),
                "cost_nav": round(cost_nav, 4),
                "buy_date": datetime.now().strftime("%Y-%m-%d"),
                "buy_amount": amount,
            })

        elif trade["action"] == "sell":
            # 从持仓移除
            pos = next((p for p in holdings.get("positions", []) if p["code"] == code), None)
            if pos:
                holdings["cash_available"] = holdings.get("cash_available", 0) + amount
                holdings["positions"].remove(pos)

        save_json(HOLDINGS_FILE, holdings)
        save_json(DAILY_LIMITS_FILE, limits)

        # 更新待确认状态
        trade["status"] = "confirmed"
        trade["confirmed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        for t in pending:
            if t.get("token") == token:
                t["status"] = "confirmed"
                t["confirmed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_json(PENDING_FILE, pending)

        return trade, "confirmed"
    else:
        trade["status"] = "rejected"
        for t in pending:
            if t.get("token") == token:
                t["status"] = "rejected"
        save_json(PENDING_FILE, pending)
        return trade, "rejected"


# ========================================
# 路由
# ========================================

@app.route("/confirm/<token>")
def confirm(token):
    action = request.args.get("action", "yes")
    confirmed = action == "yes"

    trade, status = process_confirmation(token, confirmed)

    if trade is None:
        content = f"""
        <div class="icon">🤔</div>
        <div class="title">无法处理</div>
        <div class="info">{status}</div>
        <div class="note">可能该交易已确认/拒绝，或链接已过期</div>
        <a href="/status" class="btn btn-yes" style="margin-top:16px;">查看状态</a>
        """
    elif status == "confirmed":
        action_label = "买入" if trade["action"] == "buy" else "卖出"
        content = f"""
        <div class="icon">✅</div>
        <div class="title">{action_label} 已确认</div>
        <div class="info">{trade['name']} ({trade['code']})</div>
        <div class="info">金额: {trade['amount']} 元</div>
        <div class="reason">{trade.get('reason', '')}</div>
        <div class="note">已记录到持仓，AI 将在下一轮看到更新</div>
        <a href="/status" class="btn btn-yes" style="margin-top:16px;">查看持仓</a>
        """
    else:
        content = f"""
        <div class="icon">❌</div>
        <div class="title">已拒绝</div>
        <div class="info">{trade['name']} ({trade['code']})</div>
        <div class="info">AI 将收到拒绝反馈</div>
        <a href="/status" class="btn btn-no" style="margin-top:16px;">查看状态</a>
        """

    return render_template_string(PAGE_TEMPLATE, content=content)


@app.route("/status")
def status():
    holdings = load_json(HOLDINGS_FILE, {"positions": [], "cash_available": 50000, "total_invested": 0})
    pending = load_json(PENDING_FILE, [])
    limits = load_json(DAILY_LIMITS_FILE, {"date": date.today().isoformat(), "total_bought": 0, "trade_count": 0})

    pos_html = ""
    for p in holdings.get("positions", []):
        pos_html += f"<div style='text-align:left;padding:8px;background:#f6f8fa;border-radius:8px;margin:4px 0;font-size:13px;'>"
        pos_html += f"<b>{p.get('name','?')}</b> ({p.get('code','?')})<br>"
        pos_html += f"成本: {p.get('cost_nav',0):.4f} | 份额: {p.get('shares',0):.0f} | 金额: {p.get('buy_amount',0)}元"
        pos_html += f"</div>"

    pending_waiting = [t for t in pending if t.get("status") == "pending"]

    content = f"""
    <div class="icon">📊</div>
    <div class="title">AI 交易状态</div>
    <div class="info">💵 可用资金: {holdings.get('cash_available', 0):.0f} 元</div>
    <div class="info">📈 已投资: {holdings.get('total_invested', 0):.0f} 元</div>
    <div class="info">📅 今日买入: {limits.get('total_bought', 0)} / 10000 元</div>
    <div style="margin-top:12px;font-weight:600;">持仓 ({len(holdings.get('positions',[]))} 只)</div>
    {pos_html if pos_html else '<div class="info">暂无持仓</div>'}
    <div style="margin-top:12px;font-weight:600;">待确认 ({len(pending_waiting)} 笔)</div>
    <div class="note">刷新查看最新状态</div>
    """

    return render_template_string(PAGE_TEMPLATE, content=content)


@app.route("/")
def index():
    return redirect("/status")


# ========================================
# 启动
# ========================================

if __name__ == "__main__":
    local_only = "--local" in sys.argv
    host = "127.0.0.1" if local_only else "0.0.0.0"
    port = 5000

    print(f"""
╔══════════════════════════════════════╗
║  📱 AI 交易确认服务器               ║
║  地址: http://{host}:{port}             ║
║  确认页: /confirm/<token>          ║
║  状态页: /status                   ║
╚══════════════════════════════════════╝
""")
    app.run(host=host, port=port, debug=False)
