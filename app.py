"""台灣股票分析 Dashboard — 完整互動式介面"""

import glob
import math
import os

import altair as alt
import mplfinance as mpf
import numpy as np
import pandas as pd
import streamlit as st

# ── 頁面設定 ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="台灣股票分析",
    page_icon=":material/candlestick_chart:",
    layout="wide",
)

# ── 股票名稱對照表 ─────────────────────────────────────────────────────────────
STOCK_NAMES = {
    "0050": "元大台灣50",
    "0056": "元大高股息",
    "2317": "鴻海",
    "2330": "台積電",
    "2610": "華航",
    "2618": "長榮航",
}

# ── 資料載入 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl="1h")
def load_stock(stock_id: str) -> pd.DataFrame:
    """載入股票 CSV 並做型別轉換。"""
    path = f"{stock_id}.csv"
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df.sort_index(inplace=True)
    return df


@st.cache_data
def calc_bbands(df: pd.DataFrame, period: int = 20, std_num: float = 2.0) -> pd.DataFrame:
    """計算雙布林通道及相關指標。"""
    res = df.copy()
    res["b_mid"] = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std(ddof=0)
    res["b_up"]      = res["b_mid"] + std * std_num
    res["b_up_long"] = res["b_mid"] + std * 3
    res["b_low"]      = res["b_mid"] - std * std_num
    res["b_low_long"] = res["b_mid"] - std * 3
    # 斜率 & 寬度
    b_slope, ma_slope, b_width = [np.nan], [np.nan], [np.nan]
    t = res.index
    for i in range(1, len(res)):
        b_slope.append(
            (res.loc[t[i], "b_up"] - res.loc[t[i - 1], "b_up"]) / res.loc[t[i - 1], "b_up"] * 100
        )
        ma_slope.append((res.loc[t[i], "b_mid"] / res.loc[t[i - 1], "b_mid"] - 1) * 100)
        b_width.append((res.loc[t[i], "b_up"] / res.loc[t[i], "b_low"] - 1) * 100)
    res["bband_slope"] = b_slope
    res["bband_width"] = b_width
    res["mid_slope"]   = ma_slope
    return res


@st.cache_data
def calc_ma(df: pd.DataFrame) -> pd.DataFrame:
    """計算常用均線 MA5 / MA10 / MA20 / MA60。"""
    res = df.copy()
    for w in [5, 10, 20, 60]:
        res[f"MA{w}"] = df["Close"].rolling(w).mean()
    return res


@st.cache_data
def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI 指標計算（不依賴 TA-Lib）。"""
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return 100 - 100 / (1 + rs)


@st.cache_data
def calc_macd(df: pd.DataFrame) -> pd.DataFrame:
    """MACD 指標（EMA12 - EMA26，Signal EMA9）。"""
    exp12 = df["Close"].ewm(span=12, adjust=False).mean()
    exp26 = df["Close"].ewm(span=26, adjust=False).mean()
    macd  = exp12 - exp26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return pd.DataFrame({"MACD": macd, "Signal": signal, "Histogram": hist}, index=df.index)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title(":material/candlestick_chart: 股票分析")
    st.space("small")

    csv_files = sorted(glob.glob("[0-9]*.csv"))
    stock_ids = [os.path.basename(f).replace(".csv", "") for f in csv_files]

    if not stock_ids:
        st.error("找不到股票 CSV 檔案，請先執行 fill_yfinance_gap.py。")
        st.stop()

    selected = st.selectbox(
        "選擇股票",
        stock_ids,
        format_func=lambda x: f"{x}  {STOCK_NAMES.get(x, '')}",
    )

    df_full = load_stock(selected)
    if df_full.empty:
        st.error(f"無法讀取 {selected}.csv")
        st.stop()

    min_date = df_full.index.min().date()
    max_date = df_full.index.max().date()

    horizon = st.pills(
        "快速區間",
        ["1個月", "3個月", "6個月", "1年", "3年", "全部"],
        default="1年",
    )
    horizon_map = {
        "1個月": 21, "3個月": 63, "6個月": 126,
        "1年": 252, "3年": 756, "全部": len(df_full),
    }
    n_days = horizon_map.get(horizon or "1年", 252)
    df = df_full.iloc[-n_days:]

    st.space("small")
    with st.expander(":material/tune: 技術指標設定", expanded=False):
        show_ma      = st.toggle("均線 (MA5/10/20/60)",   value=True)
        show_bbands  = st.toggle("布林通道 (BBands)",      value=True)
        bb_period    = st.slider("BB 週期", 5, 60, 20)
        bb_std       = st.slider("BB 標準差倍數", 1.0, 3.0, 2.0, step=0.5)
        show_volume  = st.toggle("成交量",                  value=True)
        show_rsi     = st.toggle("RSI (14)",               value=True)
        show_macd    = st.toggle("MACD",                   value=False)

    st.caption(f"資料範圍：{df.index.min().date()} ～ {df.index.max().date()}")

# ── 標題 ──────────────────────────────────────────────────────────────────────
stock_name = STOCK_NAMES.get(selected, "")
st.title(f"{selected}  {stock_name}", anchor=False)

# ── KPI 指標列 ─────────────────────────────────────────────────────────────────
latest  = df["Close"].iloc[-1]
prev    = df["Close"].iloc[-2] if len(df) > 1 else latest
chg     = latest - prev
chg_pct = chg / prev * 100
high_52w = df_full["Close"].iloc[-252:].max() if len(df_full) >= 252 else df_full["Close"].max()
low_52w  = df_full["Close"].iloc[-252:].min() if len(df_full) >= 252 else df_full["Close"].min()
vol_avg  = df["Volume"].rolling(20).mean().iloc[-1]

with st.container(horizontal=True):
    st.metric("收盤價 (NTD)", f"{latest:.2f}",
              delta=f"{chg:+.2f} ({chg_pct:+.2f}%)", border=True,
              chart_data=df["Close"].iloc[-30:].tolist(), chart_type="line")
    st.metric("52 週最高", f"{high_52w:.2f}", border=True)
    st.metric("52 週最低", f"{low_52w:.2f}", border=True)
    st.metric("20日均量 (張)", f"{int(vol_avg):,}", border=True,
              chart_data=df["Volume"].iloc[-30:].tolist(), chart_type="bar")

st.space("small")

# ── 計算指標（在完整資料上計算，再切到顯示區間，確保 rolling window 有足夠資料）─────
df_ma_full  = calc_ma(df_full) if show_ma else df_full
df_bb_full  = calc_bbands(df_full, bb_period, bb_std) if show_bbands else None
rsi_full    = calc_rsi(df_full) if show_rsi else None
macd_full   = calc_macd(df_full) if show_macd else None

# 切片到顯示區間
df_ma      = df_ma_full.iloc[-n_days:] if show_ma else df
df_bb      = df_bb_full.iloc[-n_days:] if show_bbands and df_bb_full is not None else None
rsi_series = rsi_full.iloc[-n_days:] if show_rsi and rsi_full is not None else None
macd_df    = macd_full.iloc[-n_days:] if show_macd and macd_full is not None else None

# ── K 線主圖 ──────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("K 線走勢圖", icon=":material/candlestick_chart:", anchor=False)

    addplots = []

    def safe_addplot(series, **kwargs):
        """只在 series 有非 NaN 值時建立 addplot，避免 mplfinance 崩潰。"""
        if series.notna().any():
            return mpf.make_addplot(series, **kwargs)
        return None

    if show_ma:
        colors = {"MA5": "blue", "MA10": "orange", "MA20": "green", "MA60": "red"}
        for col, color in colors.items():
            ap = safe_addplot(df_ma[col], color=color, width=1, label=col)
            if ap is not None:
                addplots.append(ap)
    if show_bbands and df_bb is not None:
        for series, kwargs in [
            (df_bb["b_up"],       dict(color="purple", linestyle="--", width=1,   label="BB上軌")),
            (df_bb["b_mid"],      dict(color="gray",   linestyle="--", width=1,   label="BB中線")),
            (df_bb["b_low"],      dict(color="purple", linestyle="--", width=1,   label="BB下軌")),
            (df_bb["b_up_long"],  dict(color="red",    linestyle=":",  width=0.8, label="BB+3σ")),
            (df_bb["b_low_long"], dict(color="green",  linestyle=":",  width=0.8, label="BB-3σ")),
        ]:
            ap = safe_addplot(series, **kwargs)
            if ap is not None:
                addplots.append(ap)

    fig, axes = mpf.plot(
        df,
        type="candle",
        addplot=addplots if addplots else None,
        volume=show_volume,
        returnfig=True,
        style="yahoo",
        figsize=(14, 6 if show_volume else 5),
        warn_too_much_data=9999,
    )
    # 台灣股市顏色慣例：漲 = 紅, 跌 = 綠
    st.pyplot(fig)
    st.caption("台灣習慣：紅漲綠跌（與 Yahoo Finance 預設方向相同）")

# ── RSI & MACD 面板 ────────────────────────────────────────────────────────────
if show_rsi or show_macd:
    indicator_cols = st.columns(2 if (show_rsi and show_macd) else 1)
    idx = 0

    if show_rsi and rsi_series is not None:
        rsi_df = rsi_series.reset_index()
        rsi_df.columns = ["Date", "RSI"]
        rsi_chart = (
            alt.Chart(rsi_df)
            .mark_line(color="#f05454")
            .encode(
                alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                alt.Y("RSI:Q", scale=alt.Scale(domain=[0, 100])),
                alt.Tooltip(["Date:T", "RSI:Q"]),
            )
        )
        ob  = alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(color="red",   strokeDash=[4, 2]).encode(y="y:Q")
        os_ = alt.Chart(pd.DataFrame({"y": [30]})).mark_rule(color="green", strokeDash=[4, 2]).encode(y="y:Q")
        with indicator_cols[idx].container(border=True):
            st.subheader("RSI (14)", icon=":material/speed:", anchor=False)
            rsi_latest = float(rsi_series.iloc[-1])
            if rsi_latest >= 70:
                st.badge("超買", color="red")
            elif rsi_latest <= 30:
                st.badge("超賣", color="green")
            else:
                st.badge(f"RSI {rsi_latest:.1f}", color="blue")
            st.altair_chart(rsi_chart + ob + os_)
        idx += 1

    if show_macd and macd_df is not None:
        macd_plot = macd_df.reset_index()
        macd_plot.columns = ["Date", "MACD", "Signal", "Histogram"]
        macd_line = (
            alt.Chart(macd_plot.melt("Date", value_vars=["MACD", "Signal"],
                                      var_name="Line", value_name="Value"))
            .mark_line()
            .encode(
                alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                alt.Y("Value:Q"),
                alt.Color("Line:N"),
                alt.Tooltip(["Date:T", "Line:N", "Value:Q"]),
            )
        )
        macd_plot["HistColor"] = macd_plot["Histogram"].apply(lambda x: "red" if x >= 0 else "green")
        hist_chart = (
            alt.Chart(macd_plot)
            .mark_bar(opacity=0.5)
            .encode(
                alt.X("Date:T"),
                alt.Y("Histogram:Q"),
                alt.Color("HistColor:N", scale=None, legend=None),
                alt.Tooltip(["Date:T", "Histogram:Q"]),
            )
        )
        with indicator_cols[idx].container(border=True):
            st.subheader("MACD (12/26/9)", icon=":material/bar_chart:", anchor=False)
            st.altair_chart(macd_line + hist_chart)

# ── 布林通道分析 ───────────────────────────────────────────────────────────────
if show_bbands and df_bb is not None:
    with st.container(border=True):
        st.subheader("布林通道指標", icon=":material/analytics:", anchor=False)
        bb_cols = st.columns(2)

        width_df = df_bb[["bband_width"]].dropna().reset_index()
        width_df.columns = ["Date", "Width"]
        with bb_cols[0]:
            st.caption("通道寬度（越窄代表盤整，越寬代表趨勢）")
            st.altair_chart(
                alt.Chart(width_df)
                .mark_area(color="#7b61ff", opacity=0.4)
                .encode(
                    alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                    alt.Y("Width:Q", title="寬度 (%)"),
                    alt.Tooltip(["Date:T", "Width:Q"]),
                )
            )

        slope_df = df_bb[["mid_slope"]].dropna().reset_index()
        slope_df.columns = ["Date", "Slope"]
        with bb_cols[1]:
            st.caption("20日均線斜率（> 0.05% 趨勢向上）")
            st.altair_chart(
                alt.Chart(slope_df)
                .mark_line(color="#f59e0b")
                .encode(
                    alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                    alt.Y("Slope:Q", title="斜率 (%)"),
                    alt.Tooltip(["Date:T", "Slope:Q"]),
                )
                + alt.Chart(pd.DataFrame({"y": [0]}))
                .mark_rule(color="gray", strokeDash=[3, 2])
                .encode(y="y:Q")
            )

# ── 價格走勢（Altair 互動圖）──────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("收盤價走勢（可縮放）", icon=":material/zoom_in:", anchor=False)
    close_df = df[["Close"]].reset_index()
    close_df.columns = ["Date", "Close"]
    base = (
        alt.Chart(close_df)
        .mark_line(color="#0ea5e9")
        .encode(
            alt.X("Date:T", axis=alt.Axis(format="%Y-%m")),
            alt.Y("Close:Q", scale=alt.Scale(zero=False), title="收盤價 (NTD)"),
            alt.Tooltip(["Date:T", "Close:Q"]),
        )
        .interactive()
    )
    st.altair_chart(base)

# ── 報酬率分析 ─────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("報酬率分析", icon=":material/percent:", anchor=False)
    ret_cols = st.columns(3)

    # 月報酬率
    df_monthly = df["Close"].resample("ME").last().pct_change().dropna() * 100
    monthly_df = df_monthly.reset_index()
    monthly_df.columns = ["Date", "MonthReturn"]
    monthly_df["Color"] = monthly_df["MonthReturn"].apply(lambda x: "#ef4444" if x >= 0 else "#22c55e")
    with ret_cols[0]:
        st.caption("月報酬率分佈")
        st.altair_chart(
            alt.Chart(monthly_df)
            .mark_bar()
            .encode(
                alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                alt.Y("MonthReturn:Q", title="月報酬率 (%)"),
                alt.Color("Color:N", scale=None, legend=None),
                alt.Tooltip(["Date:T", "MonthReturn:Q"]),
            )
        )

    # 日報酬率分佈直方圖
    daily_ret = df["Close"].pct_change().dropna() * 100
    hist_df = pd.DataFrame({"DailyReturn": daily_ret})
    with ret_cols[1]:
        st.caption("日報酬率分佈直方圖")
        st.altair_chart(
            alt.Chart(hist_df)
            .mark_bar(color="#6366f1", opacity=0.75)
            .encode(
                alt.X("DailyReturn:Q", bin=alt.Bin(maxbins=40), title="日報酬率 (%)"),
                alt.Y("count():Q", title="次數"),
            )
        )

    # 累積報酬率
    cum_ret = (1 + df["Close"].pct_change().fillna(0)).cumprod() - 1
    cum_df  = (cum_ret * 100).reset_index()
    cum_df.columns = ["Date", "CumReturn"]
    with ret_cols[2]:
        st.caption("累積報酬率")
        area_color = "#ef4444" if float(cum_ret.iloc[-1]) >= 0 else "#22c55e"
        st.altair_chart(
            alt.Chart(cum_df)
            .mark_area(color=area_color, opacity=0.5)
            .encode(
                alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                alt.Y("CumReturn:Q", title="累積報酬率 (%)"),
                alt.Tooltip(["Date:T", "CumReturn:Q"]),
            )
        )

# ── 統計摘要 ──────────────────────────────────────────────────────────────────
with st.expander(":material/table_chart: 統計摘要 & 原始資料", expanded=False):
    stat_cols = st.columns(2)
    with stat_cols[0]:
        st.caption("統計指標")
        stats = {
            "期間": f"{df.index.min().date()} ～ {df.index.max().date()}",
            "交易日數": len(df),
            "最高收盤": f"{df['Close'].max():.2f}",
            "最低收盤": f"{df['Close'].min():.2f}",
            "平均收盤": f"{df['Close'].mean():.2f}",
            "日均量 (張)": f"{int(df['Volume'].mean()):,}",
            "年化波動率": f"{df['Close'].pct_change().std() * math.sqrt(252) * 100:.2f}%",
            "最大回撤": f"{((df['Close'] / df['Close'].cummax()) - 1).min() * 100:.2f}%",
        }
        st.table(pd.DataFrame({"指標": list(stats.keys()), "數值": list(stats.values())}).set_index("指標"))
    with stat_cols[1]:
        st.caption("最近 10 筆資料")
        display_df = df.tail(10)[["Open", "High", "Low", "Close", "Volume"]].copy()
        display_df.index = display_df.index.strftime("%Y/%m/%d")
        st.dataframe(
            display_df,
            column_config={
                "Open":   st.column_config.NumberColumn("開盤", format="%.2f"),
                "High":   st.column_config.NumberColumn("最高", format="%.2f"),
                "Low":    st.column_config.NumberColumn("最低", format="%.2f"),
                "Close":  st.column_config.NumberColumn("收盤", format="%.2f"),
                "Volume": st.column_config.NumberColumn("成交量(張)", format="%d"),
            },
        )

# ══════════════════════════════════════════════════════════════════════════════
# ── 策略回測引擎 ───────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header(":material/query_stats: 策略回測", anchor=False)

# ── 回測函數 ──────────────────────────────────────────────────────────────────
def run_backtest(price_df: pd.DataFrame, signal_series: pd.Series,
                 initial_capital: float = 100_000.0, lot_size: int = 1000) -> tuple:
    """
    核心回測引擎，考慮台灣市場手續費與交易稅。

    Parameters
    ----------
    price_df       : DataFrame with 'Close' column
    signal_series  : Series[int], values = 1 (買入訊號) / -1 (賣出訊號) / 0 (持觀望)
    initial_capital: 初始資金（NTD）
    lot_size       : 每張股數（台股 1 張 = 1,000 股）

    Returns
    -------
    trades_df, equity_df, metrics_dict
    """
    BUY_FEE  = 0.001425   # 買進手續費 0.1425%
    SELL_FEE = 0.004425   # 賣出手續費 0.1425% + 交易稅 0.3%

    capital  = initial_capital
    shares   = 0      # 目前持有股數
    avg_cost = 0.0    # 平均持有成本（含手續費）
    trades   = []
    equity   = []

    for date, row in price_df.iterrows():
        close = row["Close"]
        sig   = signal_series.get(date, 0)

        if sig == 1 and shares == 0:
            # ── 買入：用可動用資金買入最多整數張
            unit_cost = close * (1 + BUY_FEE)                  # 每股含費成本
            max_lots  = int(capital / (unit_cost * lot_size))   # 最多可買幾張
            if max_lots > 0:
                shares   = max_lots * lot_size
                spent    = shares * unit_cost
                capital -= spent
                avg_cost = unit_cost
                trades.append({
                    "日期": date.strftime("%Y/%m/%d"),
                    "操作": "買入 🔴",
                    "成交價": round(close, 2),
                    "股數": shares,
                    "交易金額": round(spent, 0),
                    "剩餘資金": round(capital, 0),
                    "損益": None,
                })

        elif sig == -1 and shares > 0:
            # ── 賣出：全數出清
            proceeds = shares * close * (1 - SELL_FEE)
            pnl      = proceeds - shares * avg_cost
            capital += proceeds
            trades.append({
                "日期": date.strftime("%Y/%m/%d"),
                "操作": "賣出 🟢",
                "成交價": round(close, 2),
                "股數": shares,
                "交易金額": round(proceeds, 0),
                "剩餘資金": round(capital, 0),
                "損益": round(pnl, 0),
            })
            shares   = 0
            avg_cost = 0.0

        # 每日權益市值
        equity.append({"Date": date, "Strategy": capital + shares * close})

    # 期末若仍持倉則按末日收盤價強制平倉（僅計算用，不列入 trades）
    final_close = price_df["Close"].iloc[-1]
    final_equity = capital + shares * final_close * (1 - SELL_FEE)

    equity_df = pd.DataFrame(equity).set_index("Date")

    # Buy-and-Hold 基準
    bh_shares    = int(initial_capital / (price_df["Close"].iloc[0] * (1 + BUY_FEE) * lot_size)) * lot_size
    bh_spent     = bh_shares * price_df["Close"].iloc[0] * (1 + BUY_FEE)
    bh_remaining = initial_capital - bh_spent
    bh_equity    = bh_remaining + bh_shares * price_df["Close"]
    equity_df["Buy & Hold"] = bh_equity

    # ── 績效指標
    trades_df = pd.DataFrame(trades)
    wins  = [t for t in trades if t["損益"] is not None and t["損益"] > 0]
    loses = [t for t in trades if t["損益"] is not None and t["損益"] <= 0]
    total_pnl = sum(t["損益"] for t in trades if t["損益"] is not None)

    # 策略最大回撤
    roll_max = equity_df["Strategy"].cummax()
    drawdown = (equity_df["Strategy"] / roll_max - 1).min() * 100

    # 年化報酬率
    years = len(price_df) / 252
    strat_return = (final_equity / initial_capital - 1) * 100
    bh_final = float(bh_equity.iloc[-1])
    bh_return = (bh_final / initial_capital - 1) * 100
    ann_return = ((final_equity / initial_capital) ** (1 / max(years, 0.1)) - 1) * 100

    metrics = {
        "初始資金":     f"NT${initial_capital:,.0f}",
        "策略期末資產":  f"NT${final_equity:,.0f}",
        "策略總報酬":    f"{strat_return:+.2f}%",
        "年化報酬率":    f"{ann_return:+.2f}%",
        "Buy & Hold 報酬": f"{bh_return:+.2f}%",
        "超額報酬 (α)":  f"{strat_return - bh_return:+.2f}%",
        "交易次數":      len([t for t in trades if "買入" in t["操作"]]),
        "勝率":         f"{len(wins) / max(len(wins) + len(loses), 1) * 100:.1f}%",
        "最大回撤":      f"{drawdown:.2f}%",
        "淨損益":        f"NT${total_pnl:+,.0f}",
    }

    return trades_df, equity_df, metrics


def gen_ma_signals(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    """MA 黃金/死亡交叉訊號：fast 上穿 slow → 買入，fast 下穿 slow → 賣出。"""
    fast_ma = df["Close"].rolling(fast).mean()
    slow_ma = df["Close"].rolling(slow).mean()
    sig     = pd.Series(0, index=df.index)
    cross_up   = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
    cross_down = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
    sig[cross_up]   =  1
    sig[cross_down] = -1
    return sig


def gen_bb_signals(df: pd.DataFrame, period: int = 20, std_num: float = 2.0) -> pd.Series:
    """布林通道策略：收盤 < 下軌 → 買入，收盤 > 上軌 → 賣出。"""
    mid = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std(ddof=0)
    b_up  = mid + std * std_num
    b_low = mid - std * std_num
    sig = pd.Series(0, index=df.index)
    sig[df["Close"] < b_low] =  1
    sig[df["Close"] > b_up]  = -1
    # 只在首次觸碰時發訊（避免連續買入）
    in_position = False
    result = pd.Series(0, index=df.index)
    for date, s in sig.items():
        if s == 1 and not in_position:
            result[date] = 1
            in_position  = True
        elif s == -1 and in_position:
            result[date] = -1
            in_position  = False
    return result


def gen_rsi_signals(df: pd.DataFrame, period: int = 14,
                    oversold: int = 30, overbought: int = 70) -> pd.Series:
    """RSI 策略：RSI 由下往上穿越超賣線 → 買入，由上往下穿越超買線 → 賣出。"""
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rsi   = 100 - 100 / (1 + gain / loss)
    sig   = pd.Series(0, index=df.index)
    buy  = (rsi < oversold)  & (rsi.shift(1) >= oversold)
    sell = (rsi > overbought) & (rsi.shift(1) <= overbought)
    sig[buy]  =  1
    sig[sell] = -1
    return sig


# ── 回測設定 UI ────────────────────────────────────────────────────────────────
bt_col_left, bt_col_right = st.columns([1, 2])

with bt_col_left:
    with st.container(border=True):
        st.subheader(":material/tune: 回測設定", anchor=False)

        strategy = st.selectbox(
            "選擇策略",
            ["MA 黃金/死亡交叉", "布林通道策略", "RSI 超買超賣"],
        )

        initial_cap = st.number_input(
            "初始資金 (NTD)", min_value=10_000, max_value=10_000_000,
            value=100_000, step=10_000, format="%d",
        )

        st.divider()

        # 策略參數
        if strategy == "MA 黃金/死亡交叉":
            ma_fast = st.slider("快線 (MA fast)", 3, 30, 5)
            ma_slow = st.slider("慢線 (MA slow)", 10, 120, 20)
            st.caption(f"快線 MA{ma_fast} 上穿慢線 MA{ma_slow} → 買入\n快線下穿慢線 → 賣出")

        elif strategy == "布林通道策略":
            bt_period = st.slider("BB 週期", 5, 60, 20)
            bt_std    = st.slider("BB 標準差倍數", 1.0, 3.0, 2.0, step=0.5)
            st.caption(f"收盤跌破布林下軌 → 買入\n收盤突破布林上軌 → 賣出")

        elif strategy == "RSI 超買超賣":
            rsi_period    = st.slider("RSI 週期", 5, 30, 14)
            rsi_oversold  = st.slider("超賣線 (買入)", 10, 40, 30)
            rsi_overbought = st.slider("超買線 (賣出)", 60, 90, 70)
            st.caption(f"RSI 穿越 {rsi_oversold} 往上 → 買入\nRSI 穿越 {rsi_overbought} 往下 → 賣出")

        run_bt = st.button(":material/play_arrow: 執行回測", type="primary")

# ── 執行與展示結果 ─────────────────────────────────────────────────────────────
with bt_col_right:
    if run_bt:
        # 使用完整資料計算訊號，確保均線 rolling 足夠
        bt_df = df_full.copy()

        if strategy == "MA 黃金/死亡交叉":
            signals = gen_ma_signals(bt_df, ma_fast, ma_slow)
        elif strategy == "布林通道策略":
            signals = gen_bb_signals(bt_df, bt_period, bt_std)
        elif strategy == "RSI 超買超賣":
            signals = gen_rsi_signals(bt_df, rsi_period, rsi_oversold, rsi_overbought)

        # 只對顯示區間的訊號回測
        signals_view = signals.loc[df.index]
        trades_df, equity_df, metrics = run_backtest(df, signals_view, initial_cap)

        # ── 績效摘要 KPI ────────────────────────────────────────────────────
        with st.container(border=True):
            st.subheader(":material/leaderboard: 績效摘要", anchor=False)
            kpi_cols = st.columns(5)
            kpi_items = [
                ("策略總報酬",    metrics["策略總報酬"]),
                ("Buy & Hold",   metrics["Buy & Hold 報酬"]),
                ("超額報酬 α",   metrics["超額報酬 (α)"]),
                ("勝率",         metrics["勝率"]),
                ("最大回撤",     metrics["最大回撤"]),
            ]
            for col, (label, val) in zip(kpi_cols, kpi_items):
                # 決定 delta 正負顏色
                try:
                    num = float(val.replace("%", "").replace("+", "").replace(",", ""))
                    delta_val = val if num != 0 else None
                except Exception:
                    delta_val = None
                col.metric(label, val, border=True)

            detail_cols = st.columns(5)
            detail_items = [
                ("初始資金",     metrics["初始資金"]),
                ("期末資產",     metrics["策略期末資產"]),
                ("年化報酬",     metrics["年化報酬率"]),
                ("交易次數",     str(metrics["交易次數"]) + " 次"),
                ("淨損益",       metrics["淨損益"]),
            ]
            for col, (label, val) in zip(detail_cols, detail_items):
                col.metric(label, val, border=True)

        # ── 權益曲線 ─────────────────────────────────────────────────────────
        with st.container(border=True):
            st.subheader(":material/show_chart: 權益曲線 vs Buy & Hold", anchor=False)
            eq_plot = equity_df.reset_index().melt("Date", var_name="策略", value_name="資產淨值")
            eq_plot["Color"] = eq_plot["策略"].map({"Strategy": "#f59e0b", "Buy & Hold": "#64748b"})
            st.altair_chart(
                alt.Chart(eq_plot)
                .mark_line()
                .encode(
                    alt.X("Date:T", axis=alt.Axis(format="%Y-%m")),
                    alt.Y("資產淨值:Q", scale=alt.Scale(zero=False), title="資產淨值 (NTD)"),
                    alt.Color("策略:N",
                              scale=alt.Scale(domain=["Strategy", "Buy & Hold"],
                                              range=["#f59e0b", "#64748b"])),
                    alt.Tooltip(["Date:T", "策略:N", "資產淨值:Q"]),
                )
                .interactive()
            )

        # ── K 線 + 買賣訊號標記 ───────────────────────────────────────────────
        with st.container(border=True):
            st.subheader(":material/candlestick_chart: 買賣訊號圖", anchor=False)

            buy_dates  = signals_view[signals_view == 1].index
            sell_dates = signals_view[signals_view == -1].index

            buy_marker  = df["Close"].copy() * np.nan
            sell_marker = df["Close"].copy() * np.nan

            if len(buy_dates):
                valid_buy  = buy_dates.intersection(df.index)
                if len(valid_buy):
                    buy_marker[valid_buy]  = df.loc[valid_buy, "Low"] * 0.98

            if len(sell_dates):
                valid_sell = sell_dates.intersection(df.index)
                if len(valid_sell):
                    sell_marker[valid_sell] = df.loc[valid_sell, "High"] * 1.02

            signal_plots = []
            if buy_marker.notna().any():
                signal_plots.append(
                    mpf.make_addplot(buy_marker, type="scatter", markersize=120,
                                     marker="^", color="red", label="買入")
                )
            if sell_marker.notna().any():
                signal_plots.append(
                    mpf.make_addplot(sell_marker, type="scatter", markersize=120,
                                     marker="v", color="green", label="賣出")
                )

            fig_sig, _ = mpf.plot(
                df,
                type="candle",
                addplot=signal_plots if signal_plots else None,
                volume=False,
                returnfig=True,
                style="yahoo",
                figsize=(12, 5),
                warn_too_much_data=9999,
            )
            st.pyplot(fig_sig)
            st.caption("▲ 紅色三角 = 買入訊號　▼ 綠色三角 = 賣出訊號")

        # ── 交易明細 ─────────────────────────────────────────────────────────
        if not trades_df.empty:
            with st.expander(":material/receipt_long: 交易明細", expanded=False):
                display_trades = trades_df.copy()
                display_trades["損益"] = display_trades["損益"].apply(
                    lambda x: f"NT${x:+,.0f}" if pd.notna(x) else "—"
                )
                st.dataframe(
                    display_trades,
                    column_config={
                        "日期":     st.column_config.TextColumn("日期"),
                        "操作":     st.column_config.TextColumn("操作"),
                        "成交價":   st.column_config.NumberColumn("成交價", format="%.2f"),
                        "股數":     st.column_config.NumberColumn("股數", format="%d"),
                        "交易金額": st.column_config.NumberColumn("交易金額 (NTD)", format="%.0f"),
                        "剩餘資金": st.column_config.NumberColumn("剩餘資金 (NTD)", format="%.0f"),
                        "損益":     st.column_config.TextColumn("損益"),
                    },
                    hide_index=True,
                )
        else:
            st.info("此期間內沒有產生任何交易訊號，請嘗試調整策略參數或延長回測區間。",
                    icon=":material/info:")
    else:
        st.info("設定好策略參數後，點擊「執行回測」按鈕開始計算。", icon=":material/info:")
        st.caption("""
**可選策略說明：**
- **MA 黃金/死亡交叉**：快均線由下往上穿越慢均線時買入，反向時賣出。適合趨勢行情。
- **布林通道策略**：收盤跌破下軌時買入（逢低承接），突破上軌時賣出（逢高出場）。適合震盪行情。
- **RSI 超買超賣**：RSI 從超賣區反彈時買入，從超買區回落時賣出。適合波動較大的股票。

> ⚠️ 回測結果僅供學習參考，不構成投資建議。過去績效不代表未來結果。
        """)
