"""
============================================
AI 量化交易 Agent —— AI 是操盘手，Python 是手和眼
============================================

运行方式：
  python ai_trader.py            # 交易时段自动运行，盘后自动休眠
  python ai_trader.py --once     # 只跑一轮，测试用
  python ai_trader.py --force    # 无视交易时段，强制执行

核心区别 vs 传统量化脚本：
  ❌ 传统：Python 硬编码 if score>55 → BUY，AI 只写报告
  ✅ 本系统：AI 自己决定看什么数据、如何判断、何时出手
       Python 只提供工具（数据/指标/推送），AI 是决策主体
"""

import sys
import os
import json
import time
from datetime import datetime, time as dtime
from openai import OpenAI

# 导入工具箱
from ai_tools import (
    TOOL_DEFINITIONS, TOOL_FUNCTIONS, execute_tool,
    get_market_status, append_decision, load_decision_log,
    get_lan_ip,
)

# ========================================
# 配置
# ========================================

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY") or ""
DEEPSEEK_BASE = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"

# 交易时段配置
MORNING_START = dtime(9, 30)
MORNING_END = dtime(11, 30)
AFTERNOON_START = dtime(13, 0)
AFTERNOON_END = dtime(15, 0)

# 循环间隔（秒）：交易时段每 3 分钟一轮
CYCLE_INTERVAL = 180  # 3 分钟

# 最大工具调用轮次（防无限循环）
MAX_TOOL_ROUNDS = 8

# ========================================
# AI 角色定义（系统提示词）
# ========================================

SYSTEM_PROMPT = """你是一位经验丰富的中国公募基金经理，负责管理一个场外基金组合。

## 你的职责
你持续监控市场，自主做出投资决策。你通过调用工具来获取数据、分析基金、提议交易。

## 投资原则
- 趋势跟踪为主：寻找处于上升趋势的基金，在回调到支撑位时买入
- 风险第一：单只基金不要过于集中，注意止损
- 耐心等待：没有好机会就等待，不要为了交易而交易
- 结合大盘：大盘环境好时更积极，大盘走弱时更谨慎
- 技术面为主：主要看均线排列、MACD方向、RSI区间、布林带位置、动量变化

## 决策流程建议（不是硬性规则，你可以灵活调整）
1. 先了解大盘环境（get_market_status）
2. 扫描自选基金（scan_watchlist），快速了解全局
3. 从扫描结果中挑 1-2 只最有潜力的，深入分析（analyze_fund）
4. 检查持仓和资金（get_holdings）
5. 做出决定：propose_trade（有把握时）或 wait_and_observe（观望时）

## 效率要求
- 扫描完选 1-2 只分析即可，不要逐只全部分析（浪费时间）
- 整个决策过程控制在 4-6 次工具调用内
- 非交易时段 → 快速扫描后 wait_and_observe，不要做交易提议

## 交易时机参考（你是专业基金经理,用你的判断来权衡,不要机械套用）
- 理想买入：价格在MA20附近或略高于MA20、RSI 40-60、MACD金叉或即将金叉、大盘环境不差
- 理想卖出：价格跌破MA20且无法快速收回、RSI进入超买区(>70)后回落、MACD死叉确认、达到止损线
- 避免：RSI>75追高、大盘暴跌时逆势买入、连续下跌中接飞刀

## 重要规则
- 每次循环必须至少调用一个工具
- 如果没有明确机会，调用 wait_and_observe 并说明在等什么
- 每次只提议一笔交易（最有把握的那只）
- 买入金额建议 1000-3000 元，不要每次都满额
- 用中文思考和表达
- 保持独立判断，不同市场环境灵活调整策略"""

# ========================================
# 上下文构建
# ========================================

def build_context():
    """为 AI 构建当前上下文消息"""
    now = datetime.now()
    recent = load_decision_log()[-5:] if load_decision_log() else []

    # 最近的决策摘要
    recent_summary = ""
    if recent:
        items = []
        for d in recent[-3:]:
            items.append(f"[{d.get('time', '?')}] {d.get('action', '?')}: {d.get('note', '')[:80]}")
        recent_summary = "\n".join(items)

    return f"""当前时间: {now.strftime('%Y-%m-%d %H:%M')}（{['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]}）

最近的决策记录:
{recent_summary if recent_summary else '（无记录，这是启动后首次运行）'}

请开始你的判断。先了解市场环境，再决定下一步行动。"""

# ========================================
# AI 对话循环
# ========================================

def run_ai_cycle(client):
    """
    执行一轮 AI 决策循环。
    返回 AI 的最终决策摘要。
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_context()},
    ]

    tool_rounds = 0
    final_decision = None

    while tool_rounds < MAX_TOOL_ROUNDS:
        tool_rounds += 1

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.3,
                timeout=60,
            )
        except Exception as e:
            print(f"  ❌ API 调用失败: {e}")
            break

        msg = response.choices[0].message

        # 如果 AI 没有调用工具（纯文本回复）
        if not msg.tool_calls:
            if msg.content:
                print(f"\n  💬 AI: {msg.content[:200]}")
            # AI 没调工具，推动它做决定
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": "请调用一个工具来做出决策：扫描市场、分析基金、提议交易、或 wait_and_observe。"})
            continue

        # 处理工具调用
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

            print(f"\n  🔧 AI 调用: {name}({json.dumps(args, ensure_ascii=False)})")

            result = execute_tool(name, args)
            result_preview = result[:200] + "..." if len(result) > 200 else result
            print(f"  📋 结果: {result_preview}")

            # 记录到 messages
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call.id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

            # 如果是终结性工具，记录决策
            if name == "propose_trade":
                final_decision = {
                    "type": "trade",
                    "action": args.get("action"),
                    "code": args.get("code"),
                    "amount": args.get("amount"),
                    "reason": args.get("reason"),
                    "result": json.loads(result),
                }
            elif name == "wait_and_observe":
                final_decision = {
                    "type": "observe",
                    "note": args.get("note"),
                }

        # 如果 AI 已经做出了终结决策（propose_trade 或 wait_and_observe），结束本轮
        if final_decision:
            break

    # 记录决策
    if final_decision:
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "action": final_decision["type"],
            "note": final_decision.get("reason") or final_decision.get("note") or str(final_decision)[:100],
        }
        append_decision(entry)

    return final_decision


# ========================================
# 交易时段判断
# ========================================

def is_trading_time(now=None):
    """判断当前是否在 A 股交易时段"""
    if now is None:
        now = datetime.now()
    t = now.time()
    # 周末不交易
    if now.weekday() >= 5:
        return False, "周末休市"
    if MORNING_START <= t <= MORNING_END:
        return True, "上午交易中"
    if AFTERNOON_START <= t <= AFTERNOON_END:
        return True, "下午交易中"
    if t < MORNING_START:
        return False, "盘前等待"
    if MORNING_END < t < AFTERNOON_START:
        return False, "午间休市"
    return False, "已收盘"


def sleep_until_next(now=None):
    """计算到下一轮的休眠时间"""
    if now is None:
        now = datetime.now()
    t = now.time()

    # 如果在交易时段 → 等 CYCLE_INTERVAL
    if is_trading_time(now)[0]:
        return CYCLE_INTERVAL

    # 如果在午休 → 等到下午开盘
    if MORNING_END < t < AFTERNOON_START:
        afternoon = now.replace(hour=13, minute=0, second=0, microsecond=0)
        wait = (afternoon - now).total_seconds()
        return min(wait, 3600)

    # 如果在盘后 → 等到明天 9:30
    if t >= AFTERNOON_END:
        tomorrow = now.replace(hour=9, minute=30, second=0, microsecond=0)
        from datetime import timedelta
        tomorrow = tomorrow + timedelta(days=1)
        # 跳过周末
        while tomorrow.weekday() >= 5:
            tomorrow = tomorrow + timedelta(days=1)
        wait = (tomorrow - now).total_seconds()
        return min(wait, 3600 * 12)  # 最多等 12 小时

    # 盘前 → 等到开盘
    if t < MORNING_START:
        open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        wait = (open_time - now).total_seconds()
        return max(wait, 10)  # 至少等 10 秒

    return 300  # fallback: 5 分钟


# ========================================
# 单次运行摘要推送（GitHub Actions 用）
# ========================================

def _push_once_summary(decision, now):
    """每次 --once 运行结束时推一条摘要到微信，确保用户知道 AI 跑了"""
    from ai_tools import IS_GITHUB_ACTIONS, get_market_status

    print(f"\n📱 推送诊断: IS_GITHUB_ACTIONS={IS_GITHUB_ACTIONS}")

    # 只在 GitHub Actions 或明确要求时推送
    if not IS_GITHUB_ACTIONS:
        print("📱 跳过推送: 非 GitHub Actions 环境")
        return

    try:
        from wechat_notify import _push as do_push, SCT_KEY as _sct
        print(f"📱 wechat_notify 导入成功, SCT_KEY={'已设置' if _sct else '未设置或默认值'}")
    except ImportError as e:
        print(f"📱 wechat_notify 导入失败: {e}")
        return

    market = get_market_status()
    time_str = now.strftime("%m/%d %H:%M")

    if decision and decision["type"] == "trade":
        title = f"🤖 AI交易: {decision['action']} {decision.get('code','')} {decision.get('amount','')}元"
        desp = f"""## 🤖 AI 交易决策

**时间**: {time_str}
**操作**: {decision['action']} {decision.get('code','')} {decision.get('amount','')}元
**理由**: {decision.get('reason','')}

### 市场环境
- 沪深300: {market.get('index_price','?')} ({market.get('change_today_pct','?')}%)
- 趋势: {market.get('ma_trend','?')}

---
> ⚠️ 请在支付宝手动操作，15:00前下单"""
    else:
        note = decision.get('note', '无记录') if decision else 'AI 未给出决策'
        title = f"👀 AI观望 {time_str} | 沪深300 {market.get('change_today_pct','?')}%"
        desp = f"""## 👀 AI 本轮观望

**时间**: {time_str}
**市场**: 沪深300 {market.get('index_price','?')} ({market.get('change_today_pct','?')}%)
**趋势**: {market.get('ma_trend','?')}

### AI 判断
{note[:300]}

---
> 🤖 AI 量化 Agent · GitHub Actions 自动运行
> 下次运行: 下一个交易日"""

    print(f"📱 准备推送: {title}")
    result = do_push(title, desp, tags="AI量化|每日播报")
    print(f"📱 推送结果: {result}")


# ========================================
# 主循环
# ========================================

def main():
    once_mode = "--once" in sys.argv
    force_mode = "--force" in sys.argv

    print("\n" + "=" * 55)
    print("  🤖 AI 量化交易 Agent")
    print(f"  DeepSeek · 模型: {MODEL}")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if once_mode:
        print("  🔄 模式: 单次运行（测试）")
    elif force_mode:
        print("  ⚡ 模式: 强制执行（无视交易时段）")
    print("=" * 55)

    # 检查 API Key
    if not DEEPSEEK_KEY:
        print("\n❌ 未设置 DEEPSEEK_KEY 环境变量！")
        print("   GitHub Actions: Settings → Secrets → Actions → DEEPSEEK_KEY")
        print("   本地运行: set DEEPSEEK_KEY=sk-xxx && python ai_trader.py --once")
        return

    # 初始化客户端
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE)

    # 确认服务提示
    lan_ip = get_lan_ip()
    print(f"\n📱 确认服务: http://{lan_ip}:5000")
    print(f"   微信推送的确认链接将指向此地址")
    print(f"   请确保 confirm_server.py 已启动\n")

    cycle = 0

    while True:
        cycle += 1
        now = datetime.now()
        trading, status = is_trading_time(now)

        if not force_mode and not once_mode and not trading:
            wait = sleep_until_next(now)
            print(f"\n⏸️  [{now.strftime('%H:%M')}] {status}，休眠 {wait:.0f} 秒...")
            time.sleep(min(wait, 600))  # 每 10 分钟检查一次状态
            continue

        if not once_mode or cycle == 1:
            print(f"\n{'─' * 45}")
            print(f"🔄 第 {cycle} 轮 [{now.strftime('%H:%M')}] {status}")
            print(f"{'─' * 45}")

        try:
            decision = run_ai_cycle(client)

            if decision:
                if decision["type"] == "trade":
                    result = decision.get("result", {})
                    if result.get("status") == "pending_confirmation":
                        print(f"\n  ✅ AI 提议交易: {decision['action']} {decision['code']} {decision['amount']}元")
                        print(f"  📝 理由: {decision['reason']}")
                        print(f"  ⏳ 等待用户确认...")
                    else:
                        print(f"\n  ❌ 交易被风控拒绝: {result.get('reason', '未知原因')}")
                else:
                    print(f"\n  👀 AI 决定观望: {decision.get('note', '')[:100]}")
            else:
                print(f"\n  ⚠️ AI 未给出明确决策（可能 API 出错）")

        except KeyboardInterrupt:
            print("\n\n🛑 用户中断，退出。")
            break
        except Exception as e:
            print(f"\n  ❌ 循环异常: {e}")
            import traceback
            traceback.print_exc()

        if once_mode:
            print("\n✅ 单次运行完成")
            # GitHub Actions 模式：每次都推一条摘要到微信
            _push_once_summary(decision, now)
            break

        # 等待下一轮
        wait = CYCLE_INTERVAL if trading else sleep_until_next(now)
        print(f"\n  ⏳ 等待 {wait:.0f} 秒后下一轮...")
        try:
            time.sleep(min(wait, 600))
        except KeyboardInterrupt:
            print("\n\n🛑 用户中断，退出。")
            break


if __name__ == "__main__":
    main()
