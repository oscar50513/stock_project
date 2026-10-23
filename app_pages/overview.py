"""技術分析頁 — Plotly 互動 K 線 + 完整技術指標"""

import math

import altair as alt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.indicators import (
    STOCK_NAMES, calc_bbands, calc_kd, calc_ma, calc_macd,
    calc_rsi, get_horizon_slice, get_stock_ids, load_stock,
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header(":material/tune: 分析設定", divider=True)

    stock_ids = get_stock_ids()
    selected = st.selectbox(
        "選擇股票",
        stock_ids,
        format_func=lambda x: f"{x}  {STOCK_NAMES.get(x, '')}",
        key="overview_stock",
    )

    horizon = st.pills(
        "快速區間",
        ["1個月", "3個月", "6個月", "1年", "3年", "全部"],
        default="1年",
        key="overview_horizon",
    )

    st.divider()
    st.caption("指標疊加")
    show_ma     = st.toggle("均線 MA5/10/20/60", value=True)
    show_bb     = st.toggle("布林通道 BBands",    value=True)
    show_volume = st.toggle("成交量",              value=True)

    st.divider()
    st.caption("副圖指標")
    sub_indicator = st.selectbox(
        "選擇副圖",
        ["無", "RSI", "MACD", "KD"],
        index=1,
        label_visibility="collapsed",
    )

    if show_bb:
        with st.expander("布林通道參數"):
            bb_period = st.slider("BB 週期", 5, 60, 20)
            bb_std    = st.slider("BB 倍數", 1.0, 3.0, 2.0, step=0.5)
    else:
        bb_period, bb_std = 20, 2.0

# ── 載入資料 ──────────────────────────────────────────────────────────────────
df_full = load_stock(selected)
if df_full.empty:
    st.error(f"找不到 {selected}.csv")
    st.stop()

df = get_horizon_slice(df_full, horizon or "1年")
stock_name = STOCK_NAMES.get(selected, "")

# ── 標題與 KPI ────────────────────────────────────────────────────────────────
st.subheader(f"{selected}  {stock_name}", anchor=False)

latest  = df["Close"].iloc[-1]
prev    = df["Close"].iloc[-2] if len(df) > 1 else latest
chg     = latest - prev
chg_pct = chg / prev * 100
high52  = df_full["Close"].iloc[-252:].max() if len(df_full) >= 252 else df_full["Close"].max()
low52   = df_full["Close"].iloc[-252:].min() if len(df_full) >= 252 else df_full["Close"].min()
vol20   = df["Volume"].rolling(20).mean().iloc[-1]

with st.container(horizontal=True):
    st.metric("收盤價 (NTD)", f"{latest:.2f}",
              delta=f"{chg:+.2f} ({chg_pct:+.2f}%)",
              delta_color="inverse", border=True,
              chart_data=df["Close"].iloc[-30:].tolist(), chart_type="line")
    st.metric("52 週最高", f"{high52:.2f}", border=True)
    st.metric("52 週最低", f"{low52:.2f}",  border=True)
    st.metric("20日均量 (張)", f"{int(vol20):,}", border=True,
              chart_data=df["Volume"].iloc[-30:].tolist(), chart_type="bar")

# ── 計算指標（在完整資料上算，再切片）────────────────────────────────────────
n_days = len(df)
df_ma_full  = calc_ma(df_full) if show_ma else None
df_bb_full  = calc_bbands(df_full, bb_period, bb_std) if show_bb else None

df_ma = df_ma_full.iloc[-n_days:] if df_ma_full is not None else None
df_bb = df_bb_full.iloc[-n_days:] if df_bb_full is not None else None

# 副圖指標
if sub_indicator == "RSI":
    sub_data = calc_rsi(df_full).iloc[-n_days:]
elif sub_indicator == "MACD":
    sub_data = calc_macd(df_full).iloc[-n_days:]
elif sub_indicator == "KD":
    sub_data = calc_kd(df_full).iloc[-n_days:]
else:
    sub_data = None

# ── Plotly 主圖 ───────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("互動式 K 線圖", icon=":material/candlestick_chart:", anchor=False)
    st.caption("可用滑鼠滾輪縮放，拖曳平移，雙擊還原")

    # 決定子圖數量
    rows    = 1
    row_heights = [0.7]
    if show_volume:
        rows += 1
        row_heights.append(0.15)
    if sub_data is not None:
        rows += 1
        row_heights.append(0.15)

    subplot_titles = [""] * rows
    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # K 線
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        name="K線",
        increasing_line_color="#ef4444",
        decreasing_line_color="#22c55e",
        increasing_fillcolor="#ef4444",
        decreasing_fillcolor="#22c55e",
    ), row=1, col=1)

    # 均線
    ma_colors = {"MA5": "#3b82f6", "MA10": "#f97316", "MA20": "#a855f7", "MA60": "#06b6d4"}
    if df_ma is not None:
        for col, color in ma_colors.items():
            if col in df_ma.columns and df_ma[col].notna().any():
                fig.add_trace(go.Scatter(
                    x=df_ma.index, y=df_ma[col], name=col,
                    line=dict(color=color, width=1.2),
                    hovertemplate=f"{col}: %{{y:.2f}}<extra></extra>",
                ), row=1, col=1)

    # 布林通道
    if df_bb is not None:
        for col, name, color, dash in [
            ("b_up",      "BB上軌", "#8b5cf6", "dash"),
            ("b_mid",     "BB中線", "#64748b", "dash"),
            ("b_low",     "BB下軌", "#8b5cf6", "dash"),
            ("b_up_long", "BB+3σ",  "#ef4444", "dot"),
            ("b_low_long","BB-3σ",  "#22c55e", "dot"),
        ]:
            if df_bb[col].notna().any():
                fig.add_trace(go.Scatter(
                    x=df_bb.index, y=df_bb[col], name=name,
                    line=dict(color=color, width=1, dash=dash),
                    hovertemplate=f"{name}: %{{y:.2f}}<extra></extra>",
                ), row=1, col=1)

        # 布林通道填色
        valid_bb = df_bb[["b_up", "b_low"]].dropna()
        if len(valid_bb) > 0:
            fig.add_trace(go.Scatter(
                x=list(valid_bb.index) + list(valid_bb.index[::-1]),
                y=list(valid_bb["b_up"]) + list(valid_bb["b_low"][::-1]),
                fill="toself", fillcolor="rgba(139,92,246,0.06)",
                line=dict(color="rgba(0,0,0,0)"),
                name="BB區間", showlegend=False, hoverinfo="skip",
            ), row=1, col=1)

    # 成交量
    current_row = 2
    if show_volume:
        vol_colors = ["#ef4444" if c >= o else "#22c55e"
                      for c, o in zip(df["Close"], df["Open"])]
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"],
            name="成交量", marker_color=vol_colors,
            opacity=0.7,
            hovertemplate="成交量: %{y:,.0f}張<extra></extra>",
        ), row=current_row, col=1)
        fig.update_yaxes(title_text="量(張)", row=current_row, col=1)
        current_row += 1

    # 副圖指標
    if sub_data is not None and sub_indicator == "RSI":
        fig.add_trace(go.Scatter(
            x=sub_data.index, y=sub_data, name="RSI",
            line=dict(color="#f59e0b", width=1.5),
        ), row=current_row, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red",
                      row=current_row, col=1, annotation_text="超買70")
        fig.add_hline(y=30, line_dash="dash", line_color="green",
                      row=current_row, col=1, annotation_text="超賣30")
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=current_row, col=1)

    elif sub_data is not None and sub_indicator == "MACD":
        fig.add_trace(go.Scatter(
            x=sub_data.index, y=sub_data["MACD"], name="MACD",
            line=dict(color="#3b82f6", width=1.2),
        ), row=current_row, col=1)
        fig.add_trace(go.Scatter(
            x=sub_data.index, y=sub_data["Signal"], name="Signal",
            line=dict(color="#f97316", width=1.2),
        ), row=current_row, col=1)
        hist_colors = ["#ef4444" if v >= 0 else "#22c55e" for v in sub_data["Histogram"]]
        fig.add_trace(go.Bar(
            x=sub_data.index, y=sub_data["Histogram"],
            name="Histogram", marker_color=hist_colors, opacity=0.6,
        ), row=current_row, col=1)
        fig.update_yaxes(title_text="MACD", row=current_row, col=1)

    elif sub_data is not None and sub_indicator == "KD":
        fig.add_trace(go.Scatter(
            x=sub_data.index, y=sub_data["K"], name="K",
            line=dict(color="#3b82f6", width=1.2),
        ), row=current_row, col=1)
        fig.add_trace(go.Scatter(
            x=sub_data.index, y=sub_data["D"], name="D",
            line=dict(color="#f97316", width=1.2),
        ), row=current_row, col=1)
        fig.add_hline(y=80, line_dash="dash", line_color="red",
                      row=current_row, col=1, annotation_text="超買80")
        fig.add_hline(y=20, line_dash="dash", line_color="green",
                      row=current_row, col=1, annotation_text="超賣20")
        fig.update_yaxes(title_text="KD", range=[0, 100], row=current_row, col=1)

    # 圖形設定
    fig.update_layout(
        height=580 + (120 if sub_data is not None else 0),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        xaxis_rangeslider_visible=False,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font_color="#fafafa",
        margin=dict(t=40, b=20, l=60, r=20),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="#1e2535", showgrid=True)
    fig.update_yaxes(gridcolor="#1e2535", showgrid=True)

    st.plotly_chart(fig, width="stretch")

# ── 關鍵技術支撐與壓力價位速覽 ─────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/layers: 關鍵技術支撐與壓力價位", anchor=False)
    st.caption("自動計算目前收盤價相對應的近期關鍵技術支撐、多空分水嶺與上檔壓力價位（括號為距離現價之幅度）。")

    _bb_sr = df_bb_full if df_bb_full is not None else calc_bbands(df_full, bb_period, bb_std)
    _ma_sr = df_ma_full if df_ma_full is not None else calc_ma(df_full)

    sr_bb_up  = float(_bb_sr["b_up"].iloc[-1]) if pd.notna(_bb_sr["b_up"].iloc[-1]) else float(latest)
    sr_high20 = float(df_full["High"].tail(20).max())
    sr_ma20   = float(_ma_sr["MA20"].iloc[-1]) if pd.notna(_ma_sr["MA20"].iloc[-1]) else float(latest)
    sr_low20  = float(df_full["Low"].tail(20).min())
    sr_bb_low = float(_bb_sr["b_low"].iloc[-1]) if pd.notna(_bb_sr["b_low"].iloc[-1]) else float(latest)

    def _dist_str(target_p: float) -> str:
        pct = (target_p / float(latest) - 1.0) * 100.0
        return f"距現價 {pct:+.2f}%"

    with st.container(horizontal=True):
        st.metric("壓力 2｜布林上軌 (+2σ)", f"{sr_bb_up:.2f}", delta=_dist_str(sr_bb_up), delta_color="off", delta_arrow="off", border=True)
        st.metric("壓力 1｜20日波段高點", f"{sr_high20:.2f}", delta=_dist_str(sr_high20), delta_color="off", delta_arrow="off", border=True)
        st.metric("分水嶺｜20MA 月線", f"{sr_ma20:.2f}", delta="站上月線 🔴" if latest >= sr_ma20 else "月線之下 🟢",
                  delta_color="red" if latest >= sr_ma20 else "green",
                  delta_arrow="up" if latest >= sr_ma20 else "down", border=True)
        st.metric("支撐 1｜20日波段低點", f"{sr_low20:.2f}", delta=_dist_str(sr_low20), delta_color="off", delta_arrow="off", border=True)
        st.metric("支撐 2｜布林下軌 (-2σ)", f"{sr_bb_low:.2f}", delta=_dist_str(sr_bb_low), delta_color="off", delta_arrow="off", border=True)

# ── 布林通道指標分析 ───────────────────────────────────────────────────────────
if show_bb and df_bb is not None:
    with st.container(border=True):
        st.subheader("布林通道指標", icon=":material/analytics:", anchor=False)
        bb_c1, bb_c2 = st.columns(2)

        width_df = df_bb[["bband_width"]].dropna().reset_index()
        width_df.columns = ["Date", "Width"]
        with bb_c1:
            st.caption("通道寬度（越窄代表盤整，越寬代表趨勢）")
            st.altair_chart(
                alt.Chart(width_df).mark_area(color="#7b61ff", opacity=0.4).encode(
                    alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                    alt.Y("Width:Q", title="寬度 (%)"),
                    alt.Tooltip(["Date:T", "Width:Q"]),
                )
            )

        slope_df = df_bb[["mid_slope"]].dropna().reset_index()
        slope_df.columns = ["Date", "Slope"]
        with bb_c2:
            st.caption("20日均線斜率（> 0.05% 趨勢向上）")
            base = alt.Chart(slope_df).mark_line(color="#f59e0b").encode(
                alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                alt.Y("Slope:Q", title="斜率 (%)"),
                alt.Tooltip(["Date:T", "Slope:Q"]),
            )
            zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
                color="gray", strokeDash=[3, 2]
            ).encode(y="y:Q")
            st.altair_chart(base + zero)

# ── 報酬率分析 ─────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("報酬率分析", icon=":material/percent:", anchor=False)
    ret_c1, ret_c2, ret_c3 = st.columns(3)

    # 月報酬率
    df_monthly = df["Close"].resample("ME").last().pct_change().dropna() * 100
    monthly_df = df_monthly.reset_index()
    monthly_df.columns = ["Date", "MonthReturn"]
    monthly_df["Color"] = monthly_df["MonthReturn"].apply(
        lambda x: "#ef4444" if x >= 0 else "#22c55e"
    )
    with ret_c1:
        st.caption("月報酬率")
        st.altair_chart(
            alt.Chart(monthly_df).mark_bar().encode(
                alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                alt.Y("MonthReturn:Q", title="月報酬率 (%)"),
                alt.Color("Color:N", scale=None, legend=None),
                alt.Tooltip(["Date:T", "MonthReturn:Q"]),
            )
        )

    # 日報酬率直方圖
    daily_ret = df["Close"].pct_change().dropna() * 100
    hist_df   = pd.DataFrame({"DailyReturn": daily_ret})
    with ret_c2:
        st.caption("日報酬率分佈")
        st.altair_chart(
            alt.Chart(hist_df).mark_bar(color="#6366f1", opacity=0.75).encode(
                alt.X("DailyReturn:Q", bin=alt.Bin(maxbins=40), title="日報酬率 (%)"),
                alt.Y("count():Q", title="次數"),
            )
        )

    # 累積報酬率
    cum_ret   = (1 + df["Close"].pct_change().fillna(0)).cumprod() - 1
    cum_df    = (cum_ret * 100).reset_index()
    cum_df.columns = ["Date", "CumReturn"]
    cum_color = "#ef4444" if float(cum_ret.iloc[-1]) >= 0 else "#22c55e"
    with ret_c3:
        st.caption("累積報酬率")
        st.altair_chart(
            alt.Chart(cum_df).mark_area(color=cum_color, opacity=0.5).encode(
                alt.X("Date:T", axis=alt.Axis(format="%Y-%m", title=None)),
                alt.Y("CumReturn:Q", title="累積報酬率 (%)"),
                alt.Tooltip(["Date:T", "CumReturn:Q"]),
            )
        )

# ── 統計摘要 ──────────────────────────────────────────────────────────────────
with st.expander(":material/table_chart: 統計摘要 & 原始資料", expanded=False):
    sc1, sc2 = st.columns(2)
    with sc1:
        st.caption("統計指標")
        std_daily  = df["Close"].pct_change().std()
        max_dd     = ((df["Close"] / df["Close"].cummax()) - 1).min() * 100
        ann_vol    = std_daily * math.sqrt(252) * 100
        stats = {
            "期間":      f"{df.index.min().date()} ～ {df.index.max().date()}",
            "交易日數":  f"{len(df):,} 天",
            "最高收盤":  f"{df['Close'].max():.2f}",
            "最低收盤":  f"{df['Close'].min():.2f}",
            "平均收盤":  f"{df['Close'].mean():.2f}",
            "日均量(張)": f"{int(df['Volume'].mean()):,}",
            "年化波動率": f"{ann_vol:.2f}%",
            "最大回撤":  f"{max_dd:.2f}%",
        }
        st.table(
            pd.DataFrame({"指標": list(stats.keys()), "數值": list(stats.values())}).set_index("指標")
        )
    with sc2:
        st.caption("最近 10 筆資料")
        disp_full = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        disp_full["漲跌%"] = df_full["Close"].pct_change().reindex(df.index) * 100.0
        disp = disp_full.tail(10)[["Open", "High", "Low", "Close", "漲跌%", "Volume"]].copy()
        disp.index = disp.index.strftime("%Y/%m/%d")
        st.dataframe(
            disp.style.map(
                lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and pd.notna(v) and v > 0
                else ("color: #22c55e; font-weight: 600" if isinstance(v, (int, float)) and pd.notna(v) and v < 0 else ""),
                subset=["漲跌%"],
            ).format({
                "Open": "{:.2f}",
                "High": "{:.2f}",
                "Low": "{:.2f}",
                "Close": "{:.2f}",
                "漲跌%": "{:+.2f}%",
                "Volume": "{:,.0f}",
            }),
            width="stretch",
        )
