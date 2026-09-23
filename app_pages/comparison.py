"""多股比較頁 — 標準化走勢、相關性、報酬排行"""

import altair as alt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.indicators import STOCK_NAMES, get_horizon_slice, get_stock_ids, load_stock

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header(":material/tune: 比較設定", divider=True)

    stock_ids = get_stock_ids()
    selected_stocks = st.multiselect(
        "選擇股票（最多 6 支）",
        stock_ids,
        default=stock_ids[:min(3, len(stock_ids))],
        format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
        max_selections=6,
        key="cmp_stocks",
    )

    horizon = st.pills(
        "比較區間",
        ["1個月", "3個月", "6個月", "1年", "3年", "全部"],
        default="1年",
        key="cmp_horizon",
    )

    normalize = st.toggle("標準化（起始=100）", value=True)

if not selected_stocks:
    st.info("請在左側選擇至少一支股票", icon=":material/info:")
    st.stop()

# ── 載入資料 ──────────────────────────────────────────────────────────────────
stock_data: dict[str, pd.DataFrame] = {}
for sid in selected_stocks:
    df_full = load_stock(sid)
    if not df_full.empty:
        stock_data[sid] = get_horizon_slice(df_full, horizon or "1年")

if not stock_data:
    st.error("無法載入任何股票資料")
    st.stop()

# ── 1. 標準化走勢比較（Plotly）────────────────────────────────────────────────
COLORS = ["#ef4444", "#3b82f6", "#22c55e", "#f97316", "#a855f7", "#06b6d4"]

with st.container(border=True):
    st.subheader("標準化走勢比較", icon=":material/show_chart:", anchor=False)
    st.caption("以各股起始收盤價為基準標準化（起始 = 100），方便直接比較漲跌幅")

    fig = go.Figure()
    for i, (sid, df) in enumerate(stock_data.items()):
        close = df["Close"].dropna()
        y_vals = (close / close.iloc[0] * 100) if normalize else close
        label  = f"{sid} {STOCK_NAMES.get(sid, '')}"
        fig.add_trace(go.Scatter(
            x=close.index, y=y_vals, name=label,
            line=dict(color=COLORS[i % len(COLORS)], width=2),
            hovertemplate=f"{label}<br>%{{x|%Y/%m/%d}}<br>{'指數' if normalize else '收盤'}: %{{y:.2f}}<extra></extra>",
        ))

    fig.update_layout(
        height=420,
        hovermode="x unified",
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font_color="#fafafa",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=40, b=20, l=60, r=20),
        yaxis_title="標準化指數" if normalize else "收盤價 (NTD)",
    )
    fig.update_xaxes(gridcolor="#1e2535", showgrid=True)
    fig.update_yaxes(gridcolor="#1e2535", showgrid=True)
    st.plotly_chart(fig, use_container_width=True)

# ── 2. 報酬率排行 ─────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("報酬率排行", icon=":material/leaderboard:", anchor=False)

    periods = {"1個月": 21, "3個月": 63, "6個月": 126, "1年": 252}
    rows = []
    for sid, df in stock_data.items():
        row = {"股票": f"{sid} {STOCK_NAMES.get(sid, '')}"}
        for label, days in periods.items():
            if len(df) >= days:
                ret = (df["Close"].iloc[-1] / df["Close"].iloc[-days] - 1) * 100
            else:
                ret = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
            row[label] = ret
        # 年化波動率
        row["年化波動率"] = df["Close"].pct_change().std() * np.sqrt(252) * 100
        rows.append(row)

    ranking_df = pd.DataFrame(rows).set_index("股票")

    def color_ret(val):
        if isinstance(val, (int, float)):
            return "color: #ef4444" if val >= 0 else "color: #22c55e"
        return ""

    st.dataframe(
        ranking_df.style.applymap(color_ret).format({
            "1個月": "{:+.2f}%",
            "3個月": "{:+.2f}%",
            "6個月": "{:+.2f}%",
            "1年":   "{:+.2f}%",
            "年化波動率": "{:.2f}%",
        }),
    )

# ── 3. 相關性熱圖 ─────────────────────────────────────────────────────────────
if len(stock_data) >= 2:
    with st.container(border=True):
        st.subheader("日報酬率相關性熱圖", icon=":material/grid_on:", anchor=False)
        st.caption("接近 +1 表示同向波動，接近 -1 表示反向波動，接近 0 表示低相關")

        # 對齊日期並計算相關係數
        close_dict = {
            f"{sid} {STOCK_NAMES.get(sid, '')}": df["Close"]
            for sid, df in stock_data.items()
        }
        close_all = pd.DataFrame(close_dict).dropna()
        ret_all   = close_all.pct_change().dropna()
        corr      = ret_all.corr()

        # Plotly 熱圖
        labels = list(corr.columns)
        values = corr.values
        text   = [[f"{v:.2f}" for v in row] for row in values]

        fig_corr = go.Figure(go.Heatmap(
            x=labels, y=labels, z=values,
            text=text, texttemplate="%{text}",
            colorscale="RdBu_r",
            zmin=-1, zmax=1,
            colorbar=dict(title="相關係數"),
        ))
        fig_corr.update_layout(
            height=350,
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            margin=dict(t=20, b=60, l=100, r=20),
        )
        st.plotly_chart(fig_corr, use_container_width=True)

# ── 4. 各股最新狀態 ───────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("各股最新狀態", icon=":material/info:", anchor=False)
    status_rows = []
    for sid, df in stock_data.items():
        close  = df["Close"].iloc[-1]
        prev   = df["Close"].iloc[-2] if len(df) > 1 else close
        chg    = close - prev
        chg_pct = chg / prev * 100
        status_rows.append({
            "股票": f"{sid} {STOCK_NAMES.get(sid, '')}",
            "收盤": close,
            "漲跌":  chg,
            "漲跌%": chg_pct,
            "最新日期": df.index[-1].strftime("%Y/%m/%d"),
            "資料筆數": len(df),
        })

    status_df = pd.DataFrame(status_rows).set_index("股票")
    st.dataframe(
        status_df.style.applymap(
            lambda v: "color: #ef4444" if isinstance(v, float) and v >= 0
                      else ("color: #22c55e" if isinstance(v, float) and v < 0 else ""),
            subset=["漲跌", "漲跌%"]
        ).format({
            "收盤":   "{:.2f}",
            "漲跌":   "{:+.2f}",
            "漲跌%":  "{:+.2f}%",
        }),
    )
