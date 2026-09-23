"""策略回測頁 — 四種策略 + Sharpe/Sortino/Calmar + CSV 匯出"""

import io
import math

import altair as alt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.indicators import STOCK_NAMES, get_horizon_slice, get_stock_ids, load_stock

# ═══════════════════════════════════════════════════════════════════════════════
# 回測引擎
# ═══════════════════════════════════════════════════════════════════════════════

BUY_FEE  = 0.001425   # 買進手續費 0.1425%
SELL_FEE = 0.004425   # 賣出手續費 0.1425% + 交易稅 0.3%
LOT_SIZE = 1_000      # 台股 1 張 = 1,000 股


def run_backtest(df: pd.DataFrame, signals: pd.Series,
                 initial_capital: float = 100_000.0) -> tuple:
    capital  = initial_capital
    shares   = 0
    avg_cost = 0.0
    trades   = []
    equity   = []

    for date, row in df.iterrows():
        close = row["Close"]
        sig   = signals.get(date, 0)

        if sig == 1 and shares == 0:
            unit_cost = close * (1 + BUY_FEE)
            max_lots  = int(capital / (unit_cost * LOT_SIZE))
            if max_lots > 0:
                shares   = max_lots * LOT_SIZE
                spent    = shares * unit_cost
                capital -= spent
                avg_cost = unit_cost
                trades.append({
                    "日期": date.strftime("%Y/%m/%d"), "操作": "買入 🔴",
                    "成交價": round(close, 2), "股數": shares,
                    "交易金額": round(spent, 0), "剩餘資金": round(capital, 0),
                    "損益": None, "持倉成本": round(avg_cost, 4),
                })

        elif sig == -1 and shares > 0:
            proceeds = shares * close * (1 - SELL_FEE)
            pnl      = proceeds - shares * avg_cost
            capital += proceeds
            trades.append({
                "日期": date.strftime("%Y/%m/%d"), "操作": "賣出 🟢",
                "成交價": round(close, 2), "股數": shares,
                "交易金額": round(proceeds, 0), "剩餘資金": round(capital, 0),
                "損益": round(pnl, 0), "持倉成本": round(avg_cost, 4),
            })
            shares = 0; avg_cost = 0.0

        equity.append({"Date": date, "Strategy": capital + shares * close})

    final_close  = df["Close"].iloc[-1]
    final_equity = capital + shares * final_close * (1 - SELL_FEE)

    equity_df = pd.DataFrame(equity).set_index("Date")

    # Buy & Hold 基準
    bh_shares    = int(initial_capital / (df["Close"].iloc[0] * (1 + BUY_FEE) * LOT_SIZE)) * LOT_SIZE
    bh_spent     = bh_shares * df["Close"].iloc[0] * (1 + BUY_FEE)
    bh_remaining = initial_capital - bh_spent
    equity_df["BH"] = bh_remaining + bh_shares * df["Close"]

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    # ── 績效指標 ──────────────────────────────────────────────────────────────
    wins   = [t for t in trades if t["損益"] is not None and t["損益"] > 0]
    loses  = [t for t in trades if t["損益"] is not None and t["損益"] <= 0]
    total_pnl = sum(t["損益"] for t in trades if t["損益"] is not None)

    years        = len(df) / 252
    strat_return = (final_equity / initial_capital - 1) * 100
    bh_return    = (float(equity_df["BH"].iloc[-1]) / initial_capital - 1) * 100
    ann_return   = ((final_equity / initial_capital) ** (1 / max(years, 0.1)) - 1) * 100

    # 最大回撤
    roll_max = equity_df["Strategy"].cummax()
    drawdown = (equity_df["Strategy"] / roll_max - 1).min() * 100

    # 日報酬率（用於 Sharpe / Sortino）
    daily_rets = equity_df["Strategy"].pct_change().dropna()
    rf_daily   = 0.02 / 252  # 無風險利率 2% 年化
    excess     = daily_rets - rf_daily
    sharpe     = (excess.mean() / excess.std()) * math.sqrt(252) if excess.std() > 0 else 0.0
    downside   = daily_rets[daily_rets < rf_daily]
    sortino_std = downside.std() if len(downside) > 0 else 1e-9
    sortino    = (excess.mean() / sortino_std) * math.sqrt(252)
    calmar     = ann_return / abs(drawdown) if drawdown != 0 else 0.0

    metrics = {
        "初始資金":      f"NT${initial_capital:,.0f}",
        "策略期末資產":  f"NT${final_equity:,.0f}",
        "策略總報酬":    f"{strat_return:+.2f}%",
        "年化報酬率":    f"{ann_return:+.2f}%",
        "B&H 報酬":     f"{bh_return:+.2f}%",
        "超額報酬 α":   f"{strat_return - bh_return:+.2f}%",
        "交易次數":      len(wins) + len(loses),
        "勝率":          f"{len(wins) / max(len(wins)+len(loses), 1)*100:.1f}%",
        "最大回撤":      f"{drawdown:.2f}%",
        "淨損益":        f"NT${total_pnl:+,.0f}",
        "Sharpe Ratio":  f"{sharpe:.3f}",
        "Sortino Ratio": f"{sortino:.3f}",
        "Calmar Ratio":  f"{calmar:.3f}",
    }

    return trades_df, equity_df, metrics


# ── 訊號產生函數 ───────────────────────────────────────────────────────────────
def gen_ma_signals(df, fast=5, slow=20):
    fma = df["Close"].rolling(fast).mean()
    sma = df["Close"].rolling(slow).mean()
    sig = pd.Series(0, index=df.index)
    sig[(fma > sma) & (fma.shift(1) <= sma.shift(1))] =  1
    sig[(fma < sma) & (fma.shift(1) >= sma.shift(1))] = -1
    return sig


def gen_bb_signals(df, period=20, std_num=2.0):
    mid = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std(ddof=0)
    b_up = mid + std * std_num
    b_low = mid - std * std_num
    in_pos = False
    result = pd.Series(0, index=df.index)
    for date in df.index:
        c = df.loc[date, "Close"]
        if c < b_low.loc[date] and not in_pos:
            result[date] = 1; in_pos = True
        elif c > b_up.loc[date] and in_pos:
            result[date] = -1; in_pos = False
    return result


def gen_rsi_signals(df, period=14, oversold=30, overbought=70):
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rsi   = 100 - 100 / (1 + gain / loss)
    sig   = pd.Series(0, index=df.index)
    sig[(rsi < oversold)   & (rsi.shift(1) >= oversold)]   =  1
    sig[(rsi > overbought) & (rsi.shift(1) <= overbought)] = -1
    return sig


def gen_macd_signals(df):
    exp12  = df["Close"].ewm(span=12, adjust=False).mean()
    exp26  = df["Close"].ewm(span=26, adjust=False).mean()
    macd   = exp12 - exp26
    signal = macd.ewm(span=9, adjust=False).mean()
    sig    = pd.Series(0, index=df.index)
    sig[(macd > signal) & (macd.shift(1) <= signal.shift(1))] =  1
    sig[(macd < signal) & (macd.shift(1) >= signal.shift(1))] = -1
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.header(":material/tune: 回測設定", divider=True)

    stock_ids = get_stock_ids()
    selected = st.selectbox(
        "選擇股票",
        stock_ids,
        format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
        key="bt_stock",
    )

    horizon = st.pills(
        "回測區間",
        ["1個月", "3個月", "6個月", "1年", "3年", "全部"],
        default="3年",
        key="bt_horizon",
    )

    initial_cap = st.number_input(
        "初始資金 (NTD)", min_value=10_000, max_value=10_000_000,
        value=100_000, step=10_000, format="%d",
    )

    st.divider()

    strategy = st.radio(
        "選擇策略",
        ["MA 黃金/死亡交叉", "布林通道策略", "RSI 超買超賣", "MACD 黃金交叉"],
    )

    st.divider()
    st.caption("策略參數")

    if strategy == "MA 黃金/死亡交叉":
        ma_fast = st.slider("快線", 3, 30, 5)
        ma_slow = st.slider("慢線", 10, 120, 20)
        st.caption(f"MA{ma_fast} 上穿 MA{ma_slow} → 買入")

    elif strategy == "布林通道策略":
        bt_period = st.slider("BB 週期", 5, 60, 20)
        bt_std    = st.slider("BB 倍數", 1.0, 3.0, 2.0, step=0.5)

    elif strategy == "RSI 超買超賣":
        rsi_period    = st.slider("RSI 週期", 5, 30, 14)
        rsi_oversold  = st.slider("超賣線（買入）", 10, 40, 30)
        rsi_overbought = st.slider("超買線（賣出）", 60, 90, 70)

    # MACD 無額外參數

    run_bt = st.button(":material/play_arrow: 執行回測", type="primary", use_container_width=True)

# ── 載入資料 ──────────────────────────────────────────────────────────────────
df_full = load_stock(selected)
if df_full.empty:
    st.error(f"找不到 {selected}.csv"); st.stop()

df = get_horizon_slice(df_full, horizon or "3年")
stock_name = STOCK_NAMES.get(selected, "")

st.subheader(f"{selected} {stock_name} — 策略回測", anchor=False)

if not run_bt:
    st.info("設定好策略參數後，點擊左側「執行回測」開始計算。", icon=":material/info:")
    with st.expander("策略說明"):
        st.markdown("""
| 策略 | 買入訊號 | 賣出訊號 | 適合行情 |
|---|---|---|---|
| **MA 黃金/死亡交叉** | 快均線上穿慢均線 | 快均線下穿慢均線 | 趨勢行情 |
| **布林通道策略** | 收盤跌破布林下軌 | 收盤突破布林上軌 | 震盪行情 |
| **RSI 超買超賣** | RSI 從超賣區反彈 | RSI 從超買區回落 | 大幅波動 |
| **MACD 黃金交叉** | MACD 線上穿訊號線 | MACD 線下穿訊號線 | 趨勢行情 |

> ⚠️ 回測結果僅供學習參考，不構成投資建議。手續費：買入 0.1425%，賣出 0.4425%（含交易稅）。
        """)
    st.stop()

# ── 產生訊號 ──────────────────────────────────────────────────────────────────
if strategy == "MA 黃金/死亡交叉":
    signals_full = gen_ma_signals(df_full, ma_fast, ma_slow)
elif strategy == "布林通道策略":
    signals_full = gen_bb_signals(df_full, bt_period, bt_std)
elif strategy == "RSI 超買超賣":
    signals_full = gen_rsi_signals(df_full, rsi_period, rsi_oversold, rsi_overbought)
else:  # MACD
    signals_full = gen_macd_signals(df_full)

signals = signals_full.loc[df.index]

with st.spinner("計算中..."):
    trades_df, equity_df, metrics = run_backtest(df, signals, initial_cap)

# ── 績效 KPI ──────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/leaderboard: 績效摘要", anchor=False)

    kpi_row1 = st.columns(5)
    kpi_items1 = [
        ("策略總報酬",  metrics["策略總報酬"]),
        ("B&H 報酬",   metrics["B&H 報酬"]),
        ("超額報酬 α", metrics["超額報酬 α"]),
        ("年化報酬率",  metrics["年化報酬率"]),
        ("最大回撤",   metrics["最大回撤"]),
    ]
    for col, (label, val) in zip(kpi_row1, kpi_items1):
        col.metric(label, val, border=True)

    kpi_row2 = st.columns(6)
    kpi_items2 = [
        ("交易次數",     f"{metrics['交易次數']} 次"),
        ("勝率",         metrics["勝率"]),
        ("淨損益",       metrics["淨損益"]),
        ("Sharpe Ratio", metrics["Sharpe Ratio"]),
        ("Sortino Ratio",metrics["Sortino Ratio"]),
        ("Calmar Ratio", metrics["Calmar Ratio"]),
    ]
    for col, (label, val) in zip(kpi_row2, kpi_items2):
        col.metric(label, val, border=True)

    # Sharpe 解讀
    sh = float(metrics["Sharpe Ratio"])
    if sh >= 2:
        st.badge(f"Sharpe {sh:.2f} — 優異", color="green", icon=":material/thumb_up:")
    elif sh >= 1:
        st.badge(f"Sharpe {sh:.2f} — 良好", color="blue",  icon=":material/check:")
    elif sh >= 0:
        st.badge(f"Sharpe {sh:.2f} — 尚可", color="orange",icon=":material/warning:")
    else:
        st.badge(f"Sharpe {sh:.2f} — 不佳", color="red",   icon=":material/error:")

# ── 權益曲線（Plotly 互動）────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/show_chart: 權益曲線 vs Buy & Hold", anchor=False)

    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(
        x=equity_df.index, y=equity_df["Strategy"],
        name=f"{strategy}", line=dict(color="#f59e0b", width=2),
        hovertemplate="策略: NT$%{y:,.0f}<extra></extra>",
    ))
    fig_eq.add_trace(go.Scatter(
        x=equity_df.index, y=equity_df["BH"],
        name="Buy & Hold", line=dict(color="#64748b", width=2, dash="dash"),
        hovertemplate="B&H: NT$%{y:,.0f}<extra></extra>",
    ))
    fig_eq.update_layout(
        height=320,
        hovermode="x unified",
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
        legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(t=40, b=20, l=70, r=20),
        yaxis_title="資產淨值 (NTD)",
    )
    fig_eq.update_xaxes(gridcolor="#1e2535", showgrid=True)
    fig_eq.update_yaxes(gridcolor="#1e2535", showgrid=True)
    st.plotly_chart(fig_eq, use_container_width=True)

# ── K 線 + 買賣訊號（Plotly）────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/candlestick_chart: K 線 + 買賣訊號", anchor=False)

    buy_sig  = signals[signals ==  1]
    sell_sig = signals[signals == -1]

    # 計算持倉區間（用於背景高亮）
    holding_periods = []
    in_trade = False
    buy_date = None
    for date, s in signals.items():
        if s == 1 and not in_trade:
            buy_date = date; in_trade = True
        elif s == -1 and in_trade:
            holding_periods.append((buy_date, date)); in_trade = False
    if in_trade and buy_date is not None:
        holding_periods.append((buy_date, df.index[-1]))

    fig_k = go.Figure()

    # 持倉期間高亮
    for bdate, edate in holding_periods:
        fig_k.add_vrect(
            x0=bdate, x1=edate,
            fillcolor="rgba(245,158,11,0.10)", line_width=0,
            annotation_text="", annotation_position="top left",
        )

    # K 線
    fig_k.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        name="K線",
        increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
        increasing_fillcolor="#ef4444", decreasing_fillcolor="#22c55e",
    ))

    # 買入標記
    if len(buy_sig) > 0:
        valid_buy = buy_sig.index.intersection(df.index)
        if len(valid_buy):
            fig_k.add_trace(go.Scatter(
                x=valid_buy,
                y=df.loc[valid_buy, "Low"] * 0.97,
                mode="markers+text",
                name="買入",
                marker=dict(symbol="triangle-up", color="#ef4444", size=14),
                text=["買" for _ in valid_buy],
                textposition="bottom center",
                textfont=dict(color="#ef4444", size=10),
            ))

    # 賣出標記
    if len(sell_sig) > 0:
        valid_sell = sell_sig.index.intersection(df.index)
        if len(valid_sell):
            fig_k.add_trace(go.Scatter(
                x=valid_sell,
                y=df.loc[valid_sell, "High"] * 1.03,
                mode="markers+text",
                name="賣出",
                marker=dict(symbol="triangle-down", color="#22c55e", size=14),
                text=["賣" for _ in valid_sell],
                textposition="top center",
                textfont=dict(color="#22c55e", size=10),
            ))

    fig_k.update_layout(
        height=420,
        showlegend=True,
        hovermode="x unified",
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
        legend=dict(orientation="h", y=1.02, x=0),
        xaxis_rangeslider_visible=False,
        margin=dict(t=40, b=20, l=60, r=20),
    )
    fig_k.update_xaxes(gridcolor="#1e2535", showgrid=True)
    fig_k.update_yaxes(gridcolor="#1e2535", showgrid=True)
    st.plotly_chart(fig_k, use_container_width=True)
    st.caption("▲ 紅色三角 = 買入　▼ 綠色三角 = 賣出　🟡 淡黃背景 = 持倉期間")

# ── 交易明細 ──────────────────────────────────────────────────────────────────
if not trades_df.empty:
    with st.expander(":material/receipt_long: 交易明細", expanded=False):
        disp = trades_df.copy()
        disp["損益"] = disp["損益"].apply(
            lambda x: f"NT${x:+,.0f}" if pd.notna(x) else "—"
        )
        st.dataframe(
            disp.drop(columns=["持倉成本"]),
            column_config={
                "日期":     st.column_config.TextColumn("日期"),
                "操作":     st.column_config.TextColumn("操作"),
                "成交價":   st.column_config.NumberColumn("成交價",      format="%.2f"),
                "股數":     st.column_config.NumberColumn("股數",        format="%d"),
                "交易金額": st.column_config.NumberColumn("交易金額 (NTD)", format="%.0f"),
                "剩餘資金": st.column_config.NumberColumn("剩餘資金 (NTD)", format="%.0f"),
                "損益":     st.column_config.TextColumn("損益"),
            },
            hide_index=True,
        )

        # ── 匯出 CSV ──────────────────────────────────────────────────────────
        csv_buf = io.StringIO()
        trades_df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
        st.download_button(
            label=":material/download: 下載交易明細 CSV",
            data=csv_buf.getvalue().encode("utf-8-sig"),
            file_name=f"{selected}_{strategy.replace('/', '_')}_trades.csv",
            mime="text/csv",
        )
else:
    st.info("此區間內未產生交易訊號，請調整策略參數或拉長回測區間。",
            icon=":material/info:")
