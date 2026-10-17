"""模擬交易頁 — 虛擬帳戶、下單、持倉損益、資產走勢"""

import json
import os
from datetime import datetime

import altair as alt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.indicators import DATA_DIR, STOCK_NAMES, get_stock_ids, load_stock

# ── 模擬帳戶儲存路徑 ──────────────────────────────────────────────────────────
PORTFOLIO_FILE = os.path.join(DATA_DIR, "paper_portfolio.json")
BUY_FEE  = 0.001425   # 買入手續費 0.1425%
SELL_FEE = 0.004425   # 賣出手續費 0.1425% + 交易稅 0.3%
LOT_SIZE = 1_000      # 台股 1 張 = 1,000 股


# ══════════════════════════════════════════════════════════════════════════════
# 帳戶讀寫
# ══════════════════════════════════════════════════════════════════════════════

def load_portfolio() -> dict:
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "initial_capital": 1_000_000,
        "cash": 1_000_000,
        "holdings": {},       # {sid: {shares, avg_cost, total_cost}}
        "transactions": [],   # 交易紀錄
        "equity_history": [], # [{date, equity}]
    }


def save_portfolio(pf: dict) -> None:
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(pf, f, ensure_ascii=False, indent=2)


def get_latest_price(sid: str) -> float | None:
    df = load_stock(sid)
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def get_latest_date(sid: str) -> str:
    df = load_stock(sid)
    if df.empty:
        return "—"
    return df.index[-1].strftime("%Y/%m/%d")


def record_equity(pf: dict, today: str, total_equity: float) -> None:
    """每次操作時記錄當前資產快照。"""
    if pf["equity_history"] and pf["equity_history"][-1]["date"] == today:
        pf["equity_history"][-1]["equity"] = total_equity
    else:
        pf["equity_history"].append({"date": today, "equity": total_equity})
    # 只保留最近 365 筆
    pf["equity_history"] = pf["equity_history"][-365:]


# ══════════════════════════════════════════════════════════════════════════════
# 計算帳戶市值
# ══════════════════════════════════════════════════════════════════════════════

def calc_total_equity(pf: dict) -> float:
    total = pf["cash"]
    for sid, pos in pf["holdings"].items():
        price = get_latest_price(sid)
        if price is not None:
            total += pos["shares"] * price
    return total


# ══════════════════════════════════════════════════════════════════════════════
# 主頁面
# ══════════════════════════════════════════════════════════════════════════════

pf = load_portfolio()
stock_ids = get_stock_ids()
today_str = datetime.now().strftime("%Y/%m/%d")

# ── Sidebar：下單面板 ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header(":material/shopping_cart: 下單", divider=True)

    order_sid = st.selectbox(
        "選擇股票",
        stock_ids,
        format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
        key="pt_order_sid",
    )

    latest_price = get_latest_price(order_sid)
    latest_date  = get_latest_date(order_sid)

    if latest_price is not None:
        st.metric(
            f"最新收盤價 ({latest_date})",
            f"NT${latest_price:.2f}",
        )
    else:
        st.warning("無法取得最新價格")

    order_lots = st.number_input(
        "張數（1 張 = 1,000 股）",
        min_value=1, max_value=500, value=1, step=1,
    )
    order_shares = order_lots * LOT_SIZE

    if latest_price is not None:
        buy_total  = order_shares * latest_price * (1 + BUY_FEE)
        sell_total = order_shares * latest_price * (1 - SELL_FEE)
        st.caption(f"買入預估金額：NT${buy_total:,.0f}（含手續費）")
        st.caption(f"賣出預估入帳：NT${sell_total:,.0f}（扣手續費＋稅）")

    st.space("small")
    bcol, scol = st.columns(2)

    # ── 買入 ─────────────────────────────────────────────────────────────────
    with bcol:
        if st.button("🔴 買入", use_container_width=True, type="primary"):
            if latest_price is None:
                st.error("無法取得價格")
            elif buy_total > pf["cash"]:
                st.error(f"現金不足！\n需要 NT${buy_total:,.0f}\n可用 NT${pf['cash']:,.0f}")
            else:
                cost = order_shares * latest_price * (1 + BUY_FEE)
                pf["cash"] -= cost

                sid = order_sid
                if sid in pf["holdings"]:
                    old = pf["holdings"][sid]
                    new_shares = old["shares"] + order_shares
                    new_cost   = old["total_cost"] + cost
                    pf["holdings"][sid] = {
                        "shares":     new_shares,
                        "avg_cost":   new_cost / new_shares,
                        "total_cost": new_cost,
                    }
                else:
                    pf["holdings"][sid] = {
                        "shares":     order_shares,
                        "avg_cost":   cost / order_shares,
                        "total_cost": cost,
                    }

                pf["transactions"].append({
                    "時間": datetime.now().strftime("%Y/%m/%d %H:%M"),
                    "股票": f"{sid} {STOCK_NAMES.get(sid, '')}",
                    "操作": "買入 🔴",
                    "張數": order_lots,
                    "成交價": round(latest_price, 2),
                    "金額": round(cost, 0),
                    "損益": None,
                })

                total_eq = calc_total_equity(pf)
                record_equity(pf, today_str, total_eq)
                save_portfolio(pf)
                st.success(f"買入 {sid} {order_lots} 張 @ {latest_price:.2f}")
                st.rerun()

    # ── 賣出 ─────────────────────────────────────────────────────────────────
    with scol:
        if st.button("🟢 賣出", use_container_width=True):
            sid = order_sid
            if latest_price is None:
                st.error("無法取得價格")
            elif sid not in pf["holdings"]:
                st.error(f"未持有 {sid}")
            elif pf["holdings"][sid]["shares"] < order_shares:
                held_lots = pf["holdings"][sid]["shares"] // LOT_SIZE
                st.error(f"持有不足！只有 {held_lots} 張")
            else:
                pos       = pf["holdings"][sid]
                proceeds  = order_shares * latest_price * (1 - SELL_FEE)
                avg_cost  = pos["avg_cost"]
                pnl       = proceeds - order_shares * avg_cost
                pf["cash"] += proceeds

                new_shares = pos["shares"] - order_shares
                if new_shares == 0:
                    del pf["holdings"][sid]
                else:
                    pf["holdings"][sid] = {
                        "shares":     new_shares,
                        "avg_cost":   avg_cost,
                        "total_cost": avg_cost * new_shares,
                    }

                pf["transactions"].append({
                    "時間": datetime.now().strftime("%Y/%m/%d %H:%M"),
                    "股票": f"{sid} {STOCK_NAMES.get(x, '')}" if (x := sid) else sid,
                    "操作": "賣出 🟢",
                    "張數": order_lots,
                    "成交價": round(latest_price, 2),
                    "金額": round(proceeds, 0),
                    "損益": round(pnl, 0),
                })

                total_eq = calc_total_equity(pf)
                record_equity(pf, today_str, total_eq)
                save_portfolio(pf)
                pnl_str = f"+NT${pnl:,.0f}" if pnl >= 0 else f"-NT${abs(pnl):,.0f}"
                st.success(f"賣出 {sid} {order_lots} 張 @ {latest_price:.2f}，損益 {pnl_str}")
                st.rerun()

    st.divider()

    # ── 重置帳戶 ─────────────────────────────────────────────────────────────
    with st.expander(":material/warning: 危險操作"):
        new_capital = st.number_input(
            "初始資金 (NTD)", min_value=100_000, max_value=10_000_000,
            value=1_000_000, step=100_000, format="%d",
        )
        if st.button("🔄 重置帳戶", type="secondary", use_container_width=True):
            fresh = {
                "initial_capital": new_capital,
                "cash": new_capital,
                "holdings": {},
                "transactions": [],
                "equity_history": [{"date": today_str, "equity": new_capital}],
            }
            save_portfolio(fresh)
            st.success("帳戶已重置！")
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# 主畫面
# ══════════════════════════════════════════════════════════════════════════════

# ── 帳戶 KPI ──────────────────────────────────────────────────────────────────
total_equity  = calc_total_equity(pf)
stock_value   = total_equity - pf["cash"]
initial_cap   = pf["initial_capital"]
total_pnl     = total_equity - initial_cap
total_pnl_pct = total_pnl / initial_cap * 100

with st.container(horizontal=True):
    st.metric("總資產",  f"NT${total_equity:,.0f}",
              delta=f"{total_pnl:+,.0f} ({total_pnl_pct:+.2f}%)", border=True)
    st.metric("現金",    f"NT${pf['cash']:,.0f}",
              delta=f"{pf['cash']/total_equity*100:.1f}% 佔比", border=True)
    st.metric("持股市值", f"NT${stock_value:,.0f}",
              delta=f"{stock_value/total_equity*100:.1f}% 佔比", border=True)
    st.metric("初始資金", f"NT${initial_cap:,.0f}", border=True)

# ── 資產走勢圖 ────────────────────────────────────────────────────────────────
if len(pf["equity_history"]) >= 2:
    with st.container(border=True):
        st.subheader(":material/show_chart: 資產走勢", anchor=False)

        eq_df = pd.DataFrame(pf["equity_history"])
        eq_df["date"] = pd.to_datetime(eq_df["date"])
        eq_df = eq_df.set_index("date").sort_index()
        eq_df["pnl_pct"] = (eq_df["equity"] / initial_cap - 1) * 100

        eq_color = "#ef4444" if float(eq_df["pnl_pct"].iloc[-1]) >= 0 else "#22c55e"

        fig_eq = go.Figure()
        fig_eq.add_hline(y=initial_cap, line_dash="dash", line_color="#64748b",
                         annotation_text="初始資金", annotation_position="right")
        fig_eq.add_trace(go.Scatter(
            x=eq_df.index, y=eq_df["equity"],
            fill="tozeroy", fillcolor=f"rgba({'239,68,68' if eq_color == '#ef4444' else '34,197,94'},0.15)",
            line=dict(color=eq_color, width=2),
            name="總資產",
            hovertemplate="資產: NT$%{y:,.0f}<extra></extra>",
        ))
        fig_eq.update_layout(
            height=280,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            margin=dict(t=20, b=20, l=80, r=20),
            yaxis_title="資產 (NTD)",
            showlegend=False,
            hovermode="x",
        )
        fig_eq.update_xaxes(gridcolor="#1e2535")
        fig_eq.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_eq, use_container_width=True)

# ── 持倉明細 ──────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/account_balance_wallet: 持倉明細", anchor=False)

    if not pf["holdings"]:
        st.info("目前無持倉，請在左側下單面板買入股票。", icon=":material/info:")
    else:
        holdings_rows = []
        for sid, pos in pf["holdings"].items():
            price = get_latest_price(sid)
            if price is None:
                continue
            market_val = pos["shares"] * price
            cost_val   = pos["total_cost"]
            pnl        = market_val - cost_val
            pnl_pct    = pnl / cost_val * 100
            holdings_rows.append({
                "股票":     f"{sid} {STOCK_NAMES.get(sid, '')}",
                "持有張數": pos["shares"] // LOT_SIZE,
                "平均成本": round(pos["avg_cost"], 2),
                "現價":     round(price, 2),
                "市值":     round(market_val, 0),
                "未實現損益": round(pnl, 0),
                "損益%":    round(pnl_pct, 2),
            })

        if holdings_rows:
            h_df = pd.DataFrame(holdings_rows).set_index("股票")
            st.dataframe(
                h_df.style.map(
                    lambda v: "color: #ef4444" if isinstance(v, (int, float)) and v > 0
                              else ("color: #22c55e" if isinstance(v, (int, float)) and v < 0 else ""),
                    subset=["未實現損益", "損益%"]
                ).format({
                    "平均成本":   "{:.2f}",
                    "現價":       "{:.2f}",
                    "市值":       "NT${:,.0f}",
                    "未實現損益": "NT${:+,.0f}",
                    "損益%":      "{:+.2f}%",
                }),
                use_container_width=True,
            )

            # 持倉比例圓餅圖
            pie_data = [
                {"標的": "現金", "市值": pf["cash"]},
            ] + [
                {"標的": f"{sid} {STOCK_NAMES.get(sid, '')}", "市值": r["市值"]}
                for sid, r in zip(pf["holdings"].keys(), holdings_rows)
            ]
            pie_df = pd.DataFrame(pie_data)
            pie_chart = alt.Chart(pie_df).mark_arc(innerRadius=50).encode(
                alt.Theta("市值:Q"),
                alt.Color("標的:N", legend=alt.Legend(title="標的")),
                alt.Tooltip(["標的:N", "市值:Q"]),
            ).properties(title="持倉分配", height=260)
            st.altair_chart(pie_chart, use_container_width=True)

# ── 交易紀錄 ──────────────────────────────────────────────────────────────────
with st.expander(":material/receipt_long: 交易紀錄", expanded=False):
    if not pf["transactions"]:
        st.caption("尚無交易紀錄。")
    else:
        tx_df = pd.DataFrame(list(reversed(pf["transactions"])))
        tx_df["損益"] = tx_df["損益"].apply(
            lambda x: f"NT${x:+,.0f}" if x is not None else "—"
        )
        tx_df["金額"] = tx_df["金額"].apply(lambda x: f"NT${x:,.0f}")
        st.dataframe(tx_df, hide_index=True, use_container_width=True)
