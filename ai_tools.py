"""
============================================
AI 交易工具箱 —— AI 的"手"和"眼睛"
============================================
这里的每个函数都是 AI 通过 function calling 可调用的工具。
AI 自己决定何时调用哪个工具，Python 只负责执行和风控。

硬风控规则（AI 不可逾越，Python 层直接拦截）：
  - 单次买入 ≤ 5000 元
  - 单日买入 ≤ 10000 元
  - 持仓不超过 5 只
  - 单只止损线 -8%
"""

import sys
import os
import json
import hashlib
import time
import uuid
from datetime import datetime, time as dtime, date
from typing import Optional

import pandas as pd
import numpy as np
import akshare as ak
import requests

# 检测运行环境
IS_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"

# ========================================
# 文件路径
# ========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOLDINGS_FILE = os.path.join(BASE_DIR, "holdings.json")
PENDING_FILE = os.path.join(BASE_DIR, "pending_trades.json")
DECISION_LOG_FILE = os.path.join(BASE_DIR, "decision_log.json")
DAILY_LIMITS_FILE = os.path.join(BASE_DIR, "daily_limits.json")

# ========================================
# 风控硬限制（AI 不可改）
# ========================================
MAX_SINGLE_BUY = 5000       # 单次买入上限（元）
MAX_DAILY_BUY = 10000       # 单日买入总上限（元）
MAX_POSITIONS = 5           # 最大持仓数量
STOP_LOSS_PCT = -0.08       # 止损线（-8%）
MIN_CASH_RESERVE = 5000     # 最少保留现金（元）

# ========================================
# 自选基金池
# ========================================
FUNDS = {
    "011369": "华商均衡成长混合A",
    "006751": "富国互联科技股票A",
    "014143": "银河创新成长混合C",
    "012734": "易方达人工智能ETF联接C",
    "021580": "华夏人工智能ETF联接D",
    "016470": "广发纳斯达克生物科技C",
}

# ========================================
# 微信推送（优先本地 wechat_notify.py，无需依赖 quant-fund-trend）
# ========================================
try:
    from wechat_notify import _push
    WECHAT_AVAILABLE = True
except ImportError:
    WECHAT_AVAILABLE = False

    def _push(title, desp, tags=""):
        """Fallback: 只打印到控制台"""
        print(f"\n  📱 [微信推送] {title}")
        print(f"  {desp[:200]}...")
        return None


# ========================================
# 持仓管理
# ========================================

def load_holdings():
    """加载持仓数据"""
    if os.path.exists(HOLDINGS_FILE):
        try:
            with open(HOLDINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "positions": [],       # [{code, name, shares, cost_nav, buy_date, buy_amount}]
        "cash_available": 50000,
        "total_invested": 0,
    }


def save_holdings(data):
    """保存持仓数据"""
    with open(HOLDINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_daily_limits():
    """加载当日交易限额"""
    today = date.today().isoformat()
    if os.path.exists(DAILY_LIMITS_FILE):
        try:
            with open(DAILY_LIMITS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get("date") == today:
                    return data
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": today, "total_bought": 0, "trade_count": 0}


def save_daily_limits(data):
    """保存当日交易限额"""
    with open(DAILY_LIMITS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_pending_trades():
    """加载待确认的交易"""
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_pending_trades(data):
    """保存待确认的交易"""
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_decision_log():
    """加载决策日志（最近 20 条）"""
    if os.path.exists(DECISION_LOG_FILE):
        try:
            with open(DECISION_LOG_FILE, 'r', encoding='utf-8') as f:
                log = json.load(f)
                return log[-20:] if isinstance(log, list) else []
        except (json.JSONDecodeError, IOError):
            pass
    return []


def append_decision(entry):
    """追加决策记录"""
    log = load_decision_log()
    log.append(entry)
    # 只保留最近 50 条
    if len(log) > 50:
        log = log[-50:]
    with open(DECISION_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def get_lan_ip():
    """获取局域网 IP，用于生成确认链接"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ========================================
# 🔧 工具 1: 获取市场状态
# ========================================

def get_market_status() -> dict:
    """
    AI 调用此工具获取当前市场全景：
    - 交易时段（盘前/上午/午休/下午/盘后）
    - 沪深300 指数涨跌
    - 均线排列趋势
    - 最近 5 日涨跌幅
    """
    now = datetime.now()
    t = now.time()

    # 交易时段判断
    morning_s = dtime(9, 30); morning_e = dtime(11, 30)
    afternoon_s = dtime(13, 0); afternoon_e = dtime(15, 0)

    if t < morning_s:
        session = "盘前"
        is_trading = False
    elif morning_s <= t <= morning_e:
        session = "上午交易中"
        is_trading = True
    elif t < afternoon_s:
        session = "午间休市"
        is_trading = False
    elif afternoon_s <= t <= afternoon_e:
        session = "下午交易中"
        is_trading = True
    else:
        session = "已收盘"
        is_trading = False

    # 拉沪深300
    try:
        df = ak.stock_zh_index_daily(symbol="sh000300")
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        last5 = df.tail(5)
        latest = last5.iloc[-1]
        prev = last5.iloc[-2]

        close = df["close"]
        change_today = (latest["close"] - prev["close"]) / prev["close"] * 100
        change_5d = (latest["close"] - last5.iloc[0]["close"]) / last5.iloc[0]["close"] * 100

        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]

        if latest["close"] > ma20 > ma60:
            trend = "🟢 多头排列"
        elif latest["close"] > ma60:
            trend = "🟡 震荡偏强"
        elif latest["close"] > ma20:
            trend = "🟠 震荡偏弱"
        else:
            trend = "🔴 空头排列"

        return {
            "time": now.strftime("%H:%M"),
            "date": now.strftime("%Y-%m-%d"),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
            "session": session,
            "is_trading": is_trading,
            "index_name": "沪深300",
            "index_price": round(float(latest["close"]), 2),
            "change_today_pct": round(change_today, 2),
            "change_5d_pct": round(change_5d, 2),
            "ma_trend": trend,
            "ma20": round(float(ma20), 2),
            "ma60": round(float(ma60), 2),
        }
    except Exception as e:
        return {
            "time": now.strftime("%H:%M"),
            "date": now.strftime("%Y-%m-%d"),
            "session": session,
            "is_trading": is_trading,
            "error": f"获取指数数据失败: {str(e)[:100]}",
        }


# ========================================
# 🔧 工具 2: 扫描自选基金
# ========================================

def _fetch_fund_hist(code, days=120):
    """内部：拉单只基金近期净值"""
    for indicator in ["累计净值走势", "单位净值走势"]:
        try:
            df = ak.fund_open_fund_info_em(symbol=code, indicator=indicator)
            if df is None or df.empty:
                continue
            df.columns = ["date", "nav", "daily_return"]
            df["date"] = pd.to_datetime(df["date"])
            df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
            df = df.dropna(subset=["nav"])
            df = df.sort_values("date").tail(days).set_index("date")
            if len(df) >= 20:
                return df
        except Exception:
            continue
    return None


def _calc_quick_indicators(nav_series):
    """快速计算核心指标（精简版，供 AI 快照用）"""
    close = pd.Series(nav_series)
    if len(close) < 20:
        return {}

    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else float('nan')

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
    rsi = 100 - (100 / (1 + rs)) if rs != float('inf') else 100

    # MACD
    ema12 = close.ewm(span=12).mean().iloc[-1]
    ema26 = close.ewm(span=26).mean().iloc[-1]
    dif = ema12 - ema26
    dea_series = (close.ewm(span=12).mean() - close.ewm(span=26).mean()).ewm(span=9).mean()
    dea = dea_series.iloc[-1]
    prev_dif = (close.ewm(span=12).mean().iloc[-2] - close.ewm(span=26).mean().iloc[-2])
    prev_dea = dea_series.iloc[-2]

    # 动量
    momentum_5 = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0
    momentum_20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0

    # 波动率
    vol_20 = close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252) * 100

    # 距60日高点
    high_60 = close.rolling(60).max().iloc[-1] if len(close) >= 60 else close.max()
    from_high = (close.iloc[-1] / high_60 - 1) * 100

    return {
        "latest_nav": round(float(close.iloc[-1]), 4),
        "ma5": round(float(ma5), 4),
        "ma20": round(float(ma20), 4),
        "ma60": round(float(ma60), 4) if not np.isnan(ma60) else None,
        "ma_trend": "多头" if close.iloc[-1] > ma5 > ma20 else ("空头" if close.iloc[-1] < ma5 < ma20 else "震荡"),
        "rsi_14": round(float(rsi), 1),
        "rsi_zone": "超买" if rsi > 70 else ("超卖" if rsi < 30 else "中性"),
        "macd_dif": round(float(dif), 6),
        "macd_dea": round(float(dea), 6),
        "macd_signal": "金叉" if dif > dea and prev_dif <= prev_dea else ("死叉" if dif < dea and prev_dif >= prev_dea else ("多头" if dif > dea else "空头")),
        "momentum_5d": round(momentum_5, 2),
        "momentum_20d": round(momentum_20, 2),
        "volatility_annual": round(float(vol_20), 1),
        "from_60d_high_pct": round(from_high, 2),
        "data_days": len(close),
    }


def scan_watchlist() -> dict:
    """
    AI 调用此工具快速扫描所有自选基金。
    返回每只基金的核心指标快照，供 AI 判断哪些值得深入分析。
    """
    results = {}
    errors = []

    for code, name in FUNDS.items():
        try:
            df = _fetch_fund_hist(code, days=120)
            if df is None or len(df) < 20:
                errors.append(f"{code} {name}: 数据不足")
                continue
            indicators = _calc_quick_indicators(df["nav"].values)
            indicators["name"] = name
            indicators["code"] = code
            results[code] = indicators
        except Exception as e:
            errors.append(f"{code} {name}: {str(e)[:80]}")

    return {
        "scanned": len(results),
        "errors": errors,
        "funds": results,
    }


# ========================================
# 🔧 工具 3: 深度分析单只基金
# ========================================

def _calc_full_indicators(df):
    """完整技术指标（复用 quant_fund_trend 的逻辑）"""
    close = df["nav"].values
    data = pd.DataFrame({"nav": close})

    # 均线
    data["ma5"] = data["nav"].rolling(5).mean()
    data["ma10"] = data["nav"].rolling(10).mean()
    data["ma20"] = data["nav"].rolling(20).mean()
    data["ma60"] = data["nav"].rolling(60).mean()

    # RSI
    delta = data["nav"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    data["rsi"] = np.where(avg_loss == 0, np.where(avg_gain == 0, 50, 100), 100 - (100 / (1 + rs)))

    # MACD
    ema12 = data["nav"].ewm(span=12).mean()
    ema26 = data["nav"].ewm(span=26).mean()
    data["macd_dif"] = ema12 - ema26
    data["macd_dea"] = data["macd_dif"].ewm(span=9).mean()
    data["macd_hist"] = 2 * (data["macd_dif"] - data["macd_dea"])

    # 布林带
    data["bb_mid"] = data["nav"].rolling(20).mean()
    bb_std = data["nav"].rolling(20).std()
    data["bb_upper"] = data["bb_mid"] + 2 * bb_std
    data["bb_lower"] = data["bb_mid"] - 2 * bb_std
    data["bb_position"] = (data["nav"] - data["bb_lower"]) / (data["bb_upper"] - data["bb_lower"] + 1e-10)

    # 动量
    data["momentum_5"] = data["nav"].pct_change(5) * 100
    data["momentum_10"] = data["nav"].pct_change(10) * 100
    data["momentum_20"] = data["nav"].pct_change(20) * 100

    # 成交量（净值变化幅度作为替代）
    data["volatility_20"] = data["nav"].pct_change().rolling(20).std() * np.sqrt(252) * 100

    # 距各均线距离
    latest = data.iloc[-1]
    return {
        "latest_nav": round(float(latest["nav"]), 4),
        "ma5": round(float(latest["ma5"]), 4) if not np.isnan(latest["ma5"]) else None,
        "ma10": round(float(latest["ma10"]), 4) if not np.isnan(latest["ma10"]) else None,
        "ma20": round(float(latest["ma20"]), 4) if not np.isnan(latest["ma20"]) else None,
        "ma60": round(float(latest["ma60"]), 4) if not np.isnan(latest["ma60"]) else None,
        "price_vs_ma20": round((latest["nav"] / latest["ma20"] - 1) * 100, 2) if not np.isnan(latest["ma20"]) else None,
        "price_vs_ma60": round((latest["nav"] / latest["ma60"] - 1) * 100, 2) if not np.isnan(latest["ma60"]) else None,
        "rsi_14": round(float(latest["rsi"]), 1) if not np.isnan(latest["rsi"]) else None,
        "rsi_zone": "超买(>70)" if latest["rsi"] > 70 else ("超卖(<30)" if latest["rsi"] < 30 else "中性(30-70)"),
        "macd_dif": round(float(latest["macd_dif"]), 6),
        "macd_dea": round(float(latest["macd_dea"]), 6),
        "macd_hist": round(float(latest["macd_hist"]), 6),
        "macd_direction": "多头增强" if latest["macd_hist"] > data["macd_hist"].iloc[-2] else "多头减弱",
        "bb_position": round(float(latest["bb_position"]) * 100, 1),  # 0-100, 0=下轨 100=上轨
        "bb_zone": "上轨附近" if latest["bb_position"] > 0.8 else ("下轨附近" if latest["bb_position"] < 0.2 else "中轨附近"),
        "momentum_5d": round(float(latest["momentum_5"]), 2) if not np.isnan(latest["momentum_5"]) else None,
        "momentum_10d": round(float(latest["momentum_10"]), 2) if not np.isnan(latest["momentum_10"]) else None,
        "momentum_20d": round(float(latest["momentum_20"]), 2) if not np.isnan(latest["momentum_20"]) else None,
        "volatility_annual_pct": round(float(latest["volatility_20"]), 1) if not np.isnan(latest["volatility_20"]) else None,
    }


def analyze_fund(code: str) -> dict:
    """
    AI 调用此工具深度分析单只基金。
    返回完整技术指标 + 近期走势描述。
    """
    if code not in FUNDS:
        return {"error": f"未知基金代码: {code}，自选池: {list(FUNDS.keys())}"}

    name = FUNDS[code]

    try:
        df = _fetch_fund_hist(code, days=365)
        if df is None or len(df) < 60:
            return {"error": f"{code} {name}: 数据不足（需要至少60个交易日）", "available_days": len(df) if df is not None else 0}

        indicators = _calc_full_indicators(df.reset_index())

        # 近期走势描述
        recent = df.tail(20)
        recent_nav = recent["nav"].values
        trend_desc = "上升" if recent_nav[-1] > recent_nav[0] else "下降"
        high_20 = recent_nav.max()
        low_20 = recent_nav.min()
        range_pct = (high_20 - low_20) / low_20 * 100

        return {
            "code": code,
            "name": name,
            "data_days": len(df),
            "date_range": f"{df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}",
            "indicators": indicators,
            "recent_20d": {
                "trend": f"{trend_desc}（{round((recent_nav[-1]/recent_nav[0]-1)*100, 2)}%）",
                "high": round(float(high_20), 4),
                "low": round(float(low_20), 4),
                "range_pct": round(range_pct, 2),
            },
            "suggestion_for_ai": "请基于以上技术指标，独立判断该基金的买卖时机。不要依赖固定公式，结合市场环境综合判断。",
        }
    except Exception as e:
        return {"error": f"分析 {code} {name} 失败: {str(e)[:200]}"}


# ========================================
# 🔧 工具 4: 查看持仓
# ========================================

def get_holdings() -> dict:
    """
    AI 调用此工具查看当前持仓、可用资金、盈亏情况。
    如果持仓中有亏损接近止损线的，会特别标注。
    """
    data = load_holdings()
    limits = load_daily_limits()
    positions = data.get("positions", [])

    # 更新每只持仓的估算（用最新净值）
    enriched = []
    alerts = []
    for pos in positions:
        code = pos.get("code", "")
        try:
            df = _fetch_fund_hist(code, days=10)
            if df is not None and len(df) > 0:
                current_nav = float(df["nav"].iloc[-1])
                pnl_pct = (current_nav - pos["cost_nav"]) / pos["cost_nav"] * 100
                current_value = pos.get("shares", 0) * current_nav
            else:
                current_nav = pos["cost_nav"]
                pnl_pct = 0
                current_value = pos.get("buy_amount", 0)
        except Exception:
            current_nav = pos["cost_nav"]
            pnl_pct = 0
            current_value = pos.get("buy_amount", 0)

        pos_info = {
            **pos,
            "current_nav": round(current_nav, 4),
            "pnl_pct": round(pnl_pct, 2),
            "current_value": round(current_value, 2),
        }
        enriched.append(pos_info)

        if pnl_pct <= STOP_LOSS_PCT * 100:
            alerts.append(f"⚠️ 止损警告: {pos.get('name', code)} 亏损 {pnl_pct:.1f}%（止损线 {STOP_LOSS_PCT*100:.0f}%）")

    return {
        "positions": enriched,
        "position_count": len(enriched),
        "max_positions": MAX_POSITIONS,
        "cash_available": round(data.get("cash_available", 0), 2),
        "total_invested": round(data.get("total_invested", 0), 2),
        "daily_bought_today": round(limits.get("total_bought", 0), 2),
        "daily_buy_limit": MAX_DAILY_BUY,
        "daily_buy_remaining": round(MAX_DAILY_BUY - limits.get("total_bought", 0), 2),
        "single_buy_limit": MAX_SINGLE_BUY,
        "alerts": alerts,
    }


# ========================================
# 🔧 工具 5: 提议交易（核心）
# ========================================

def propose_trade(action: str, code: str, amount: float, reason: str) -> dict:
    """
    AI 提议一笔交易。这个函数会：
    1. 硬风控检查（AI 不可绕过）
    2. 通过 → 生成确认链接，推微信
    3. 拒绝 → 返回拒绝原因
    4. 记录到待确认列表

    参数：
      action: "buy" | "sell"
      code: 基金代码
      amount: 金额（元）
      reason: AI 的交易理由
    """
    if action not in ("buy", "sell"):
        return {"status": "rejected", "reason": f"无效操作: {action}，只允许 buy/sell"}

    if code not in FUNDS:
        return {"status": "rejected", "reason": f"未知基金: {code}"}

    name = FUNDS[code]
    holdings = load_holdings()
    limits = load_daily_limits()

    # ---- 买入风控 ----
    if action == "buy":
        if amount > MAX_SINGLE_BUY:
            return {"status": "rejected", "reason": f"单次买入 {amount}元 超过上限 {MAX_SINGLE_BUY}元"}
        if limits["total_bought"] + amount > MAX_DAILY_BUY:
            remaining = MAX_DAILY_BUY - limits["total_bought"]
            return {"status": "rejected", "reason": f"今日已买 {limits['total_bought']}元，剩余额度 {remaining}元，本次 {amount}元 超出"}
        if len(holdings.get("positions", [])) >= MAX_POSITIONS:
            return {"status": "rejected", "reason": f"持仓已达上限 {MAX_POSITIONS} 只，先卖出再买入"}
        if amount > holdings.get("cash_available", 0) - MIN_CASH_RESERVE:
            return {"status": "rejected", "reason": f"可用资金不足（可用 {holdings.get('cash_available', 0)}，需保留 {MIN_CASH_RESERVE}）"}

    # ---- 卖出风控 ----
    if action == "sell":
        pos = next((p for p in holdings.get("positions", []) if p["code"] == code), None)
        if not pos:
            return {"status": "rejected", "reason": f"未持有 {code} {name}，无法卖出"}

    # ---- 通过！生成确认 ----
    token = uuid.uuid4().hex[:12]
    trade = {
        "token": token,
        "action": action,
        "code": code,
        "name": name,
        "amount": amount,
        "reason": reason,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": "pending",
    }

    # 保存待确认
    pending = load_pending_trades()
    pending.append(trade)
    save_pending_trades(pending)

    # 推微信
    action_label = "🟢 买入" if action == "buy" else "🔴 卖出"

    if IS_GITHUB_ACTIONS:
        # GitHub Actions 模式：无确认服务器，推送完整分析信息
        desp = f"""## 🤖 AI 交易建议

**操作**: {action_label}
**基金**: {name} ({code})
**金额**: {amount} 元

### AI 分析理由
{reason}

---
> ⚠️ 本消息由 AI 交易 Agent 自动生成（GitHub Actions）
> 场外基金请在支付宝手动操作，15:00 前下单按当日净值成交
"""
        push_result = _push(f"🤖 AI建议: {action_label} {name} {amount}元", desp, tags="AI量化|交易建议")
        return {
            "status": "pending_confirmation",
            "token": token,
            "message": f"已推送微信（GitHub Actions模式）：{action_label} {name} {amount}元",
            "note": "GitHub Actions 环境无确认服务器，请根据推送内容在支付宝手动操作",
            "push_result": str(push_result)[:100] if push_result else "推送失败",
        }
    else:
        # 本地模式：带确认链接
        lan_ip = get_lan_ip()
        confirm_url_yes = f"http://{lan_ip}:5000/confirm/{token}?action=yes"
        confirm_url_no = f"http://{lan_ip}:5000/confirm/{token}?action=no"

        desp = f"""## {action_label} 提议

**基金**: {name} ({code})
**金额**: {amount} 元
**理由**: {reason}

---

[✅ 确认]({confirm_url_yes})　|　[❌ 拒绝]({confirm_url_no})

> ⚠️ AI 量化信号，请独立判断后确认
"""
        push_result = _push(f"{action_label} {name} {amount}元", desp, tags="量化交易|确认")

        return {
            "status": "pending_confirmation",
            "token": token,
            "message": f"已推送微信确认：{action_label} {name} {amount}元",
            "confirm_url": confirm_url_yes,
            "push_result": str(push_result)[:100] if push_result else "推送失败",
        }


# ========================================
# 🔧 工具 6: 等待观察（不做操作）
# ========================================

def wait_and_observe(note: str) -> dict:
    """
    AI 决定本轮不做任何操作，继续观察市场。
    记录观察结论供后续参考。
    """
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "action": "observe",
        "note": note,
    }
    append_decision(entry)
    return {
        "status": "observed",
        "message": f"已记录观察: {note[:100]}",
    }


# ========================================
# 🔧 工具 7: 检查待确认交易状态
# ========================================

def check_pending_trades() -> dict:
    """
    AI 调用此工具查看之前提议的交易是否已被用户确认/拒绝。
    """
    pending = load_pending_trades()
    confirmed = [t for t in pending if t.get("status") == "confirmed"]
    rejected = [t for t in pending if t.get("status") == "rejected"]
    waiting = [t for t in pending if t.get("status") == "pending"]

    # 将已处理的移出等待列表
    still_pending = [t for t in pending if t.get("status") == "pending"]

    return {
        "waiting": waiting,
        "confirmed_today": [t for t in confirmed if t["time"][:10] == date.today().isoformat()],
        "rejected_today": [t for t in rejected if t["time"][:10] == date.today().isoformat()],
    }


# ========================================
# 🔧 工具 8: 获取决策历史摘要
# ========================================

def get_recent_decisions() -> dict:
    """
    AI 调用此工具查看最近的决策历史，了解之前的判断和结果。
    """
    log = load_decision_log()
    pending = load_pending_trades()

    recent_trades = [t for t in pending if t.get("status") in ("confirmed", "rejected")]
    recent_trades = sorted(recent_trades, key=lambda x: x.get("time", ""), reverse=True)[:10]

    return {
        "decision_count": len(log),
        "recent_observations": log[-5:] if log else [],
        "recent_trades": recent_trades,
        "today_summary": f"今日已记录 {sum(1 for d in log if d['time'][:10] == date.today().isoformat())} 条观察",
    }


# ========================================
# 工具注册表（供 ai_trader.py 使用）
# ========================================

# JSON Schema 定义（给 API）
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_market_status",
            "description": "获取当前市场全景：交易时段、沪深300涨跌、均线排列趋势。每次决策前应先调用此工具了解大环境。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_watchlist",
            "description": "快速扫描所有自选基金（6只），返回每只的核心技术指标快照（RSI/MACD/动量/均线）。适合首次了解全局。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_fund",
            "description": "深度分析单只基金：完整技术指标（均线/RSI/MACD/布林带/动量/波动率）+ 近20日走势。当你对某只基金感兴趣时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "基金代码，如 011369、006751"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_holdings",
            "description": "查看当前持仓、可用资金、每日已用额度、止损警告。提议交易前必须先调用此工具。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_trade",
            "description": "提议一笔交易。会经过硬风控检查（单次≤5000/单日≤10000/持仓≤5只），通过后推微信给用户确认。这是AI表达交易意图的唯一出口。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["buy", "sell"], "description": "买入或卖出"},
                    "code": {"type": "string", "description": "基金代码"},
                    "amount": {"type": "number", "description": "金额（元），建议1000-5000之间"},
                    "reason": {"type": "string", "description": "交易理由，简洁说明为什么（技术信号+市场环境），会显示在微信推送中"},
                },
                "required": ["action", "code", "amount", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_and_observe",
            "description": "本轮不做任何操作，记录观察结论。当市场没有明确机会时使用此工具，而非不做任何调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "观察备注：为什么不做操作？在等什么信号？"},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_pending_trades",
            "description": "查看之前提议的交易是否已被用户确认或拒绝。可用于跟进待确认交易的状态。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_decisions",
            "description": "查看最近的决策历史和交易记录，了解之前的判断。每次启动或需要回顾时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# Python 函数映射
TOOL_FUNCTIONS = {
    "get_market_status": get_market_status,
    "scan_watchlist": scan_watchlist,
    "analyze_fund": analyze_fund,
    "get_holdings": get_holdings,
    "propose_trade": propose_trade,
    "wait_and_observe": wait_and_observe,
    "check_pending_trades": check_pending_trades,
    "get_recent_decisions": get_recent_decisions,
}


def execute_tool(name: str, args: dict) -> str:
    """执行工具调用，返回 JSON 字符串"""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    try:
        result = func(**args) if args else func()
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"工具执行失败: {str(e)[:200]}"}, ensure_ascii=False)


if __name__ == "__main__":
    # 测试
    print("=== 市场状态 ===")
    print(json.dumps(get_market_status(), ensure_ascii=False, indent=2))
    print("\n=== 扫描自选 ===")
    print(json.dumps(scan_watchlist(), ensure_ascii=False, indent=2))
