"""主動式 ETF 專區 — 檔案卡、主動 vs 被動基準 (Alpha/Beta/IR) 對比、RS 相對強弱與深度技術分析"""

import importlib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import src.indicators as _ind
importlib.reload(_ind)

from src.indicators import (
    ACTIVE_ETF_META,
    ETF_HOLDINGS,
    STOCK_NAMES,
    calc_bbands,
    calc_kd,
    calc_ma,
    calc_macd,
    calc_rsi,
    download_stock_csv,
    get_active_etf_ids,
    load_stock,
)

PALETTE = [
    "#ef4444", "#3b82f6", "#f59e0b", "#a855f7", "#06b6d4",
    "#ec4899", "#10b981", "#f97316", "#84cc16",
]

BENCH_COLORS = {
    "0050": "#f8fafc",
    "00830": "#38bdf8",
    "0056": "#fbbf24",
}

THEME_OPTIONS = [
    "全部主題",
    "台股市值／高息型",
    "台股升級／科技成長型",
    "跨國／全球創新主題型",
]

HORIZON_MAP = {
    "1個月": 21,
    "3個月": 63,
    "6個月": 126,
    "1年": 252,
}

# ── 取得目前已下載的主動式 ETF ────────────────────────────────────────────────
available_active_ids = get_active_etf_ids()

# ── Sidebar：篩選與新增控制 ───────────────────────────────────────────────────
with st.sidebar:
    st.header("主動式 ETF 設定", divider=True)

    selected_theme = st.pills(
        "主題分類篩選",
        THEME_OPTIONS,
        default="全部主題",
    ) or "全部主題"

    if selected_theme == "全部主題":
        theme_filtered_ids = available_active_ids
    else:
        theme_filtered_ids = [
            sid for sid in available_active_ids
            if ACTIVE_ETF_META.get(sid, {}).get("theme") == selected_theme
        ]

    selected_etfs = st.multiselect(
        "選擇分析標的",
        options=available_active_ids,
        default=theme_filtered_ids if theme_filtered_ids else available_active_ids[:6],
        format_func=lambda x: f"{x} {STOCK_NAMES.get(x, ACTIVE_ETF_META.get(x, {}).get('name', ''))}",
    )

    benchmark_mode = st.segmented_control(
        "對標被動基準 ETF",
        options=["AUTO", "0050", "00830", "0056"],
        default="00830" if selected_theme == "跨國／全球創新主題型" else "AUTO",
        format_func=lambda x: (
            "依主題自動 (台股0050/跨國00830/高息0056)"
            if x == "AUTO"
            else f"{x} {STOCK_NAMES.get(x, '')}"
        ),
    ) or "AUTO"

    horizon = st.segmented_control(
        "分析區間",
        options=["1個月", "3個月", "6個月", "共同掛牌期間", "全部"],
        default="3個月",
    ) or "3個月"

    st.divider()
    st.subheader(":material/cloud_download: 新增／更新主動式 ETF", anchor=False)

    preset_choice = st.selectbox(
        "從內建清單選擇或自訂",
        options=["（手動輸入代號）"] + list(ACTIVE_ETF_META.keys()),
        format_func=lambda x: (
            x if x == "（手動輸入代號）"
            else f"{x} {ACTIVE_ETF_META[x]['name']} {'(已下載)' if x in available_active_ids else '(未下載)'}"
        ),
    )

    custom_sid = st.text_input(
        "輸入主動式 ETF 代號（如 00985A）",
        value="" if preset_choice == "（手動輸入代號）" else preset_choice,
        placeholder="例如：00985A",
    )

    if st.button(":material/download: 從 yfinance 下載／更新", type="primary"):
        target_sid = custom_sid.strip().upper()
        if not target_sid:
            st.warning("請先選擇或輸入 ETF 代號")
        else:
            with st.spinner(f"正在下載 {target_sid} 歷史資料…"):
                ok, msg = download_stock_csv(target_sid)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)


def get_etf_benchmark_id(sid: str) -> str:
    """根據目前模式決定該檔 ETF 對標的基準代號。"""
    if benchmark_mode != "AUTO":
        return benchmark_mode
    meta = ACTIVE_ETF_META.get(sid, {})
    if meta.get("theme") == "跨國／全球創新主題型":
        return "00830"
    return meta.get("benchmark", "0050")


# ── 頁面標題 ──────────────────────────────────────────────────────────────────
bench_desc = (
    "依主題自動對標（台股 → 0050 元大台灣50 ｜ 跨國全球 → 00830 國泰費城半導體 ｜ 高息 → 0056 元大高股息）"
    if benchmark_mode == "AUTO"
    else f"{benchmark_mode} {STOCK_NAMES.get(benchmark_mode, '')}"
)
st.subheader(":material/workspace_premium: 主動式 ETF 研究分析面板", anchor=False)
st.caption(
    f"檢驗主動式 ETF 經理人選股操盤能力 — 目前對標基準：**{bench_desc}** ｜ 分析區間：**{horizon}**"
)

if not selected_etfs:
    st.info("請從左側欄選擇至少 1 檔主動式 ETF 進行分析。", icon=":material/info:")
    st.stop()

# ── 載入資料 ──────────────────────────────────────────────────────────────────
etf_full_map: dict[str, pd.DataFrame] = {}
for sid in selected_etfs:
    df_tmp = load_stock(sid)
    if not df_tmp.empty:
        etf_full_map[sid] = df_tmp

if not etf_full_map:
    st.warning("所選主動式 ETF 尚無有效資料。")
    st.stop()

# 載入所有會用到的基準指數資料
needed_bench_ids = sorted({get_etf_benchmark_id(sid) for sid in etf_full_map.keys()})
bench_full_map: dict[str, pd.DataFrame] = {}
for bid in needed_bench_ids:
    dfb = load_stock(bid)
    if dfb.empty:
        ok, _ = download_stock_csv(bid)
        if ok:
            dfb = load_stock(bid)
    if not dfb.empty:
        bench_full_map[bid] = dfb

if not bench_full_map:
    st.error("無法載入基準指數 CSV 資料。")
    st.stop()

# 計算共同掛牌起始日（若選擇「共同掛牌期間」）
common_start = max(df.index.min() for df in etf_full_map.values())


def slice_by_horizon(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    if mode == "共同掛牌期間":
        return df.loc[df.index >= common_start]
    if mode == "全部":
        return df
    n = HORIZON_MAP.get(mode, 63)
    return df.iloc[-n:]


# ══════════════════════════════════════════════════════════════════════════════
# 1. 即時快照 KPI（含近 20 日走勢 Sparklines）& 檔案卡
# ══════════════════════════════════════════════════════════════════════════════
with st.container(horizontal=True):
    for sid, df_full in etf_full_map.items():
        name = STOCK_NAMES.get(sid, ACTIVE_ETF_META.get(sid, {}).get("name", sid))
        close_now = float(df_full["Close"].iloc[-1])
        close_prev = float(df_full["Close"].iloc[-2]) if len(df_full) > 1 else close_now
        day_chg_pct = (close_now / close_prev - 1) * 100
        spark = [float(x) for x in df_full["Close"].tail(20).tolist()]

        df_sub = slice_by_horizon(df_full, horizon)
        period_ret = (
            (float(df_sub["Close"].iloc[-1]) / float(df_sub["Close"].iloc[0]) - 1) * 100
            if len(df_sub) > 1 else 0.0
        )
        bid = get_etf_benchmark_id(sid)

        st.metric(
            label=f"{sid} {name} (對標 {bid})",
            value=f"NT${close_now:.2f}",
            delta=f"{day_chg_pct:+.2f}% (區間 {period_ret:+.2f}%)",
            delta_color="red" if day_chg_pct > 0 else ("green" if day_chg_pct < 0 else "gray"),
            delta_arrow="up" if day_chg_pct > 0 else ("down" if day_chg_pct < 0 else "off"),
            border=True,
            chart_data=spark,
            chart_type="line",
        )

with st.expander(":material/menu_book: 主動式 ETF 檔案室（投信、主題分類、對標基準與選股邏輯）", expanded=False):
    profile_rows = []
    for sid in selected_etfs:
        meta = ACTIVE_ETF_META.get(sid, {})
        df_f = etf_full_map.get(sid, pd.DataFrame())
        list_date = df_f.index.min().strftime("%Y/%m/%d") if not df_f.empty else "—"
        latest_p = float(df_f["Close"].iloc[-1]) if not df_f.empty else np.nan
        bid = get_etf_benchmark_id(sid)
        profile_rows.append({
            "代號": sid,
            "名稱": meta.get("name", STOCK_NAMES.get(sid, sid)),
            "主題分類": meta.get("theme", "自訂主動式 ETF"),
            "發行投信": meta.get("issuer", "—"),
            "配息頻率": meta.get("dividend", "—"),
            "對標基準": f"{bid} {STOCK_NAMES.get(bid, '')}",
            "資料起始日": list_date,
            "交易天數": len(df_f),
            "最新收盤價": latest_p,
            "核心選股策略": meta.get("strategy", "由專業經理團隊主動選股操作。"),
        })
    prof_df = pd.DataFrame(profile_rows).set_index("代號")
    st.dataframe(
        prof_df,
        column_config={
            "最新收盤價": st.column_config.NumberColumn("最新收盤", format="NT$%.2f"),
            "交易天數": st.column_config.NumberColumn("資料筆數", format="%d 天"),
            "核心選股策略": st.column_config.TextColumn("核心選股策略與特色", width="large"),
        },
    )

# ══════════════════════════════════════════════════════════════════════════════
# 2. 主動 vs 被動基準對比（Alpha / Beta / Information Ratio 檢驗）
# ══════════════════════════════════════════════════════════════════════════════
with st.container(border=True):
    bench_labels_str = "、".join(f"{b} {STOCK_NAMES.get(b, '')}" for b in needed_bench_ids)
    st.subheader(
        f":material/compare_arrows: 主動 vs 被動基準走勢對比（基準：{bench_labels_str}）",
        anchor=False,
    )
    st.caption(
        "所有曲線皆以分析區間起點標準化為 **100**（粗虛線為對標被動基準 ETF），高於對應基準線代表創造正超額報酬。"
    )

    fig_cmp = go.Figure()

    # 決定區間起點
    first_bench_df = next(iter(bench_full_map.values()))
    if horizon == "共同掛牌期間":
        bench_slice_start = common_start
    elif horizon == "全部":
        bench_slice_start = min(df.index.min() for df in etf_full_map.values())
    else:
        n_days = HORIZON_MAP.get(horizon, 63)
        bench_slice_start = first_bench_df.iloc[-min(n_days, len(first_bench_df)):].index.min()

    # 繪製基準指數虛線
    for bid, df_b_full in bench_full_map.items():
        df_b_sub = df_b_full.loc[df_b_full.index >= bench_slice_start]
        if not df_b_sub.empty:
            bench_norm = df_b_sub["Close"] / df_b_sub["Close"].iloc[0] * 100
            fig_cmp.add_trace(
                go.Scatter(
                    x=df_b_sub.index,
                    y=bench_norm,
                    name=f"基準：{bid} {STOCK_NAMES.get(bid, '')}",
                    line=dict(color=BENCH_COLORS.get(bid, "#f8fafc"), width=3.2, dash="dash"),
                )
            )

    # 繪製主動式 ETF 實線
    for idx, (sid, df_full) in enumerate(etf_full_map.items()):
        df_sub = df_full.loc[df_full.index >= bench_slice_start]
        if df_sub.empty:
            continue
        s_norm = df_sub["Close"] / df_sub["Close"].iloc[0] * 100
        name = STOCK_NAMES.get(sid, ACTIVE_ETF_META.get(sid, {}).get("name", sid))
        fig_cmp.add_trace(
            go.Scatter(
                x=df_sub.index,
                y=s_norm,
                name=f"{sid} {name}",
                line=dict(color=PALETTE[idx % len(PALETTE)], width=2.2),
            )
        )

    fig_cmp.add_hline(y=100, line_dash="dot", line_color="#475569")
    fig_cmp.update_layout(
        height=440,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font_color="#fafafa",
        hovermode="x unified",
        yaxis_title="標準化淨值 (起點 = 100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=40, b=30, l=60, r=20),
    )
    fig_cmp.update_xaxes(gridcolor="#1e2535")
    fig_cmp.update_yaxes(gridcolor="#1e2535")
    st.plotly_chart(fig_cmp)

# ── 主動操盤成績單（Alpha / Beta / Information Ratio 表格）────────────────────
with st.container(border=True):
    st.subheader(":material/leaderboard: 主動操盤績效檢驗表（對標同期間基準）", anchor=False)
    st.caption(
        "跨國／全球創新主題預設對標 **00830 國泰費城半導體**、台股成長型對標 **0050 元大台灣50**、高息型對標 **0056 元大高股息**（亦可於左側欄切換為單一固定基準）。"
        "所有指標皆嚴格對齊該檔 ETF 在所選區間內的**實際重疊交易日**計算。"
    )

    perf_rows = []
    rf_daily = 0.015 / 252  # 假設無風險年利率 1.5%

    for sid, df_full in etf_full_map.items():
        bid = get_etf_benchmark_id(sid)
        df_b_full = bench_full_map.get(bid, next(iter(bench_full_map.values())))
        df_sub = slice_by_horizon(df_full, horizon)

        # 與該 ETF 對應之基準對齊日期
        joined = pd.DataFrame({
            "etf": df_sub["Close"],
            "bench": df_b_full["Close"],
        }).dropna()

        if len(joined) < 5:
            continue

        etf_ret_total = (joined["etf"].iloc[-1] / joined["etf"].iloc[0] - 1) * 100
        bench_ret_total = (joined["bench"].iloc[-1] / joined["bench"].iloc[0] - 1) * 100
        excess_ret = etf_ret_total - bench_ret_total

        r_etf = joined["etf"].pct_change().dropna()
        r_bench = joined["bench"].pct_change().dropna()
        active_r = r_etf - r_bench

        # Beta & 年化 Alpha (CAPM)
        var_b = float(r_bench.var())
        if var_b > 1e-12:
            cov_eb = float(np.cov(r_etf, r_bench)[0, 1])
            beta = cov_eb / var_b
        else:
            beta = 1.0

        alpha_daily = (float(r_etf.mean()) - rf_daily) - beta * (float(r_bench.mean()) - rf_daily)
        alpha_annual = alpha_daily * 252 * 100

        # Information Ratio (IR) = 年化主動報酬 / 年化追蹤誤差
        te_annual = float(active_r.std()) * np.sqrt(252) * 100
        ir = (float(active_r.mean()) * 252 * 100) / te_annual if te_annual > 1e-6 else 0.0

        # 年化波動率 & Sharpe Ratio
        vol_annual = float(r_etf.std()) * np.sqrt(252) * 100
        sharpe = ((float(r_etf.mean()) - rf_daily) / float(r_etf.std()) * np.sqrt(252)) if float(r_etf.std()) > 1e-9 else 0.0

        # 最大回撤 MDD
        cum_max = joined["etf"].cummax()
        mdd = float(((joined["etf"] - cum_max) / cum_max).min()) * 100

        # 打敗大盤日勝率
        win_days_pct = float((active_r > 0).mean()) * 100

        if excess_ret >= 3.0 and ir >= 0.5:
            grade = "🏆 顯著打敗基準"
        elif excess_ret > 0:
            grade = "✅ 優於基準"
        elif excess_ret >= -2.0:
            grade = "⚖️ 貼近基準"
        else:
            grade = "⚠️ 落後基準"

        meta = ACTIVE_ETF_META.get(sid, {})
        perf_rows.append({
            "ETF": f"{sid} {STOCK_NAMES.get(sid, meta.get('name', ''))}",
            "主題": meta.get("theme", "—"),
            "對標基準": f"{bid} {STOCK_NAMES.get(bid, '')}",
            "比較天數": len(joined),
            "ETF區間報酬": etf_ret_total,
            "同期間基準報酬": bench_ret_total,
            "超額報酬(Excess)": excess_ret,
            "年化Alpha": alpha_annual,
            "Beta": beta,
            "資訊比率(IR)": ir,
            "Sharpe": sharpe,
            "年化波動率": vol_annual,
            "最大回撤(MDD)": mdd,
            "勝過基準日數%": win_days_pct,
            "操盤評級": grade,
        })

    if perf_rows:
        perf_df = pd.DataFrame(perf_rows).sort_values("超額報酬(Excess)", ascending=False).set_index("ETF")

        def color_pos_neg(v):
            if isinstance(v, (int, float)):
                return "color: #ef4444; font-weight: 600" if v > 0 else ("color: #22c55e" if v < 0 else "")
            return ""

        st.dataframe(
            perf_df.style.map(
                color_pos_neg,
                subset=["ETF區間報酬", "同期間基準報酬", "超額報酬(Excess)", "年化Alpha", "資訊比率(IR)"],
            ).format({
                "ETF區間報酬": "{:+.2f}%",
                "同期間基準報酬": "{:+.2f}%",
                "超額報酬(Excess)": "{:+.2f}%",
                "年化Alpha": "{:+.2f}%",
                "Beta": "{:.2f}",
                "資訊比率(IR)": "{:+.2f}",
                "Sharpe": "{:.2f}",
                "年化波動率": "{:.2f}%",
                "最大回撤(MDD)": "{:.2f}%",
                "勝過基準日數%": "{:.1f}%",
            }),
        )

    # 風險 vs 報酬散佈圖（波動率 vs 區間報酬）
    if len(perf_rows) >= 2:
        col_sc1, col_sc2 = st.columns(2)
        with col_sc1:
            fig_sc = go.Figure()
            for idx, r in enumerate(perf_rows):
                fig_sc.add_trace(
                    go.Scatter(
                        x=[r["年化波動率"]],
                        y=[r["ETF區間報酬"]],
                        mode="markers+text",
                        text=[r["ETF"].split()[0]],
                        textposition="top center",
                        marker=dict(size=14, color=PALETTE[idx % len(PALETTE)]),
                        name=r["ETF"],
                        hovertemplate=(
                            f"<b>{r['ETF']}</b><br>"
                            f"對標基準: {r['對標基準']}<br>"
                            "年化波動率: %{x:.2f}%<br>"
                            "區間報酬: %{y:+.2f}%<extra></extra>"
                        ),
                    )
                )
            fig_sc.add_hline(y=0, line_dash="dot", line_color="#475569")
            fig_sc.update_layout(
                title="風險 vs 報酬分佈（左上角＝高報酬低波動）",
                height=340,
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
                xaxis_title="年化波動率 (%)",
                yaxis_title="區間累積報酬 (%)",
                showlegend=False,
                margin=dict(t=45, b=40, l=60, r=20),
            )
            fig_sc.update_xaxes(gridcolor="#1e2535")
            fig_sc.update_yaxes(gridcolor="#1e2535")
            st.plotly_chart(fig_sc)

        with col_sc2:
            fig_bar = go.Figure()
            sorted_rows = sorted(perf_rows, key=lambda x: x["超額報酬(Excess)"])
            bar_colors = ["#ef4444" if r["超額報酬(Excess)"] >= 0 else "#22c55e" for r in sorted_rows]
            fig_bar.add_trace(
                go.Bar(
                    x=[r["超額報酬(Excess)"] for r in sorted_rows],
                    y=[f"{r['ETF']} (vs {r['對標基準'].split()[0]})" for r in sorted_rows],
                    orientation="h",
                    marker_color=bar_colors,
                    text=[f"{r['超額報酬(Excess)']:+.2f}%" for r in sorted_rows],
                    textposition="auto",
                )
            )
            fig_bar.add_vline(x=0, line_dash="dash", line_color="#94a3b8")
            fig_bar.update_layout(
                title="相較對應基準之超額報酬排行 (%)",
                height=340,
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
                xaxis_title="超額報酬 (%)",
                margin=dict(t=45, b=40, l=180, r=20),
            )
            fig_bar.update_xaxes(gridcolor="#1e2535")
            fig_bar.update_yaxes(gridcolor="#1e2535")
            st.plotly_chart(fig_bar)

# ══════════════════════════════════════════════════════════════════════════════
# 3. 個股深度技術面 & 相對大盤強弱勢（RS Line & Rolling Alpha）
# ══════════════════════════════════════════════════════════════════════════════
with st.container(border=True):
    st.subheader(":material/query_stats: 單一主動式 ETF 深度技術面 & 滾動超額報酬", anchor=False)

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 1])
    with ctrl_col1:
        focus_sid = st.selectbox(
            "選擇深度剖析標的",
            options=list(etf_full_map.keys()),
            format_func=lambda x: f"{x} {STOCK_NAMES.get(x, ACTIVE_ETF_META.get(x, {}).get('name', ''))}",
        )
    with ctrl_col2:
        view_mode = st.segmented_control(
            "分析視角",
            options=["相對強弱與滾動Alpha", "K線與技術指標"],
            default="相對強弱與滾動Alpha",
        ) or "相對強弱與滾動Alpha"
    with ctrl_col3:
        sub_ind = st.selectbox(
            "技術副圖（K線模式）",
            options=["RSI", "MACD", "KD"],
            disabled=(view_mode != "K線與技術指標"),
        )

    df_focus_full = etf_full_map[focus_sid]
    focus_bench_id = get_etf_benchmark_id(focus_sid)
    df_focus_bench = bench_full_map.get(focus_bench_id, next(iter(bench_full_map.values())))
    meta_focus = ACTIVE_ETF_META.get(focus_sid, {})
    st.caption(
        f"**{focus_sid} {STOCK_NAMES.get(focus_sid, meta_focus.get('name', ''))}** ｜ "
        f"對標基準：**{focus_bench_id} {STOCK_NAMES.get(focus_bench_id, '')}** ｜ "
        f"主題：{meta_focus.get('theme', '—')} ｜ 投信：{meta_focus.get('issuer', '—')} ｜ "
        f"策略：{meta_focus.get('strategy', '—')}"
    )

    if view_mode == "相對強弱與滾動Alpha":
        # 計算全歷史對齊後再切片，確保 20 日滾動指標不會因切片產生前段全 NaN
        joined_full = pd.DataFrame({
            "etf": df_focus_full["Close"],
            "bench": df_focus_bench["Close"],
        }).dropna()

        joined_full["rs_raw"] = joined_full["etf"] / joined_full["bench"]
        joined_full["rolling_20d_etf"] = (joined_full["etf"].pct_change(20)) * 100
        joined_full["rolling_20d_bench"] = (joined_full["bench"].pct_change(20)) * 100
        joined_full["rolling_20d_alpha"] = joined_full["rolling_20d_etf"] - joined_full["rolling_20d_bench"]

        if horizon == "共同掛牌期間":
            joined_sub = joined_full.loc[joined_full.index >= common_start].copy()
        elif horizon == "全部":
            joined_sub = joined_full.copy()
        else:
            n_slice = HORIZON_MAP.get(horizon, 63)
            joined_sub = joined_full.iloc[-n_slice:].copy()

        joined_sub["etf_norm"] = joined_sub["etf"] / joined_sub["etf"].iloc[0] * 100
        joined_sub["bench_norm"] = joined_sub["bench"] / joined_sub["bench"].iloc[0] * 100
        joined_sub["rs_line"] = joined_sub["rs_raw"] / joined_sub["rs_raw"].iloc[0] * 100
        joined_sub["rs_ma20"] = joined_sub["rs_line"].rolling(min(20, max(3, len(joined_sub) // 2))).mean()

        fig_rs = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.07,
            row_heights=[0.62, 0.38],
            subplot_titles=(
                f"{focus_sid} vs {focus_bench_id} ({STOCK_NAMES.get(focus_bench_id, '')}) 相對強弱線 (RS Line，向上代表跑贏基準)",
                f"20 日滾動超額報酬率 (Rolling 20D Alpha %，紅＝跑贏 {focus_bench_id}、綠＝跑輸)",
            ),
        )

        fig_rs.add_trace(
            go.Scatter(
                x=joined_sub.index, y=joined_sub["etf_norm"],
                name=f"{focus_sid} 標準化淨值",
                line=dict(color="#3b82f6", width=1.8),
            ),
            row=1, col=1,
        )
        fig_rs.add_trace(
            go.Scatter(
                x=joined_sub.index, y=joined_sub["bench_norm"],
                name=f"{focus_bench_id} 基準淨值",
                line=dict(color="#94a3b8", width=1.5, dash="dot"),
            ),
            row=1, col=1,
        )
        fig_rs.add_trace(
            go.Scatter(
                x=joined_sub.index, y=joined_sub["rs_line"],
                name="RS 相對強弱線 (ETF/基準)",
                line=dict(color="#f59e0b", width=2.8),
            ),
            row=1, col=1,
        )
        if joined_sub["rs_ma20"].notna().any():
            fig_rs.add_trace(
                go.Scatter(
                    x=joined_sub.index, y=joined_sub["rs_ma20"],
                    name="RS 均線",
                    line=dict(color="#a855f7", width=1.5, dash="dash"),
                ),
                row=1, col=1,
            )

        alpha_vals = joined_sub["rolling_20d_alpha"].fillna(0)
        alpha_colors = ["#ef4444" if v >= 0 else "#22c55e" for v in alpha_vals]
        fig_rs.add_trace(
            go.Bar(
                x=joined_sub.index,
                y=alpha_vals,
                name="20日滾動超額報酬(%)",
                marker_color=alpha_colors,
            ),
            row=2, col=1,
        )
        fig_rs.add_hline(y=0, line_dash="dash", line_color="#64748b", row=2, col=1)

        fig_rs.update_layout(
            height=560,
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
            margin=dict(t=60, b=30, l=60, r=20),
        )
        fig_rs.update_xaxes(gridcolor="#1e2535")
        fig_rs.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_rs)

    else:
        # K 線與技術指標視角（先在完整資料計算指標再切片）
        df_ma_full = calc_ma(df_focus_full, [5, 10, 20, 60])
        df_bb_full = calc_bbands(df_focus_full, 20, 2.0)
        rsi_full = calc_rsi(df_focus_full, 14)
        macd_full = calc_macd(df_focus_full)
        kd_full = calc_kd(df_focus_full, 9)

        df_k = slice_by_horizon(df_focus_full, horizon)
        idx_slice = df_k.index
        df_ma = df_ma_full.loc[idx_slice]
        df_bb = df_bb_full.loc[idx_slice]

        fig_k = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.56, 0.20, 0.24],
            subplot_titles=(
                f"{focus_sid} K線 + 均線 + 布林通道",
                "成交量 (張)",
                f"{sub_ind} 技術指標",
            ),
        )

        # K 線（台股紅漲綠跌）
        fig_k.add_trace(
            go.Candlestick(
                x=df_k.index,
                open=df_k["Open"], high=df_k["High"],
                low=df_k["Low"], close=df_k["Close"],
                increasing_line_color="#ef4444", increasing_fillcolor="#ef4444",
                decreasing_line_color="#22c55e", decreasing_fillcolor="#22c55e",
                name="K線",
            ),
            row=1, col=1,
        )

        # 均線
        ma_colors = {"MA5": "#f59e0b", "MA10": "#06b6d4", "MA20": "#3b82f6", "MA60": "#a855f7"}
        for col_name, c in ma_colors.items():
            if col_name in df_ma and df_ma[col_name].notna().any():
                fig_k.add_trace(
                    go.Scatter(
                        x=df_ma.index, y=df_ma[col_name],
                        name=col_name, line=dict(color=c, width=1.4),
                    ),
                    row=1, col=1,
                )

        # 布林上下軌
        if df_bb["b_up"].notna().any():
            fig_k.add_trace(
                go.Scatter(
                    x=df_bb.index, y=df_bb["b_up"],
                    name="BB上軌(+2σ)", line=dict(color="rgba(168,85,247,0.5)", width=1, dash="dot"),
                ),
                row=1, col=1,
            )
            fig_k.add_trace(
                go.Scatter(
                    x=df_bb.index, y=df_bb["b_low"],
                    name="BB下軌(-2σ)", line=dict(color="rgba(168,85,247,0.5)", width=1, dash="dot"),
                    fill="tonexty", fillcolor="rgba(168,85,247,0.06)",
                ),
                row=1, col=1,
            )

        # 成交量
        vol_colors = [
            "#ef4444" if c >= o else "#22c55e"
            for c, o in zip(df_k["Close"], df_k["Open"])
        ]
        fig_k.add_trace(
            go.Bar(
                x=df_k.index, y=df_k["Volume"],
                name="成交量(張)", marker_color=vol_colors,
            ),
            row=2, col=1,
        )

        # 副圖指標
        if sub_ind == "RSI":
            s_rsi = rsi_full.loc[idx_slice]
            fig_k.add_trace(
                go.Scatter(x=s_rsi.index, y=s_rsi, name="RSI(14)", line=dict(color="#f59e0b", width=1.8)),
                row=3, col=1,
            )
            fig_k.add_hline(y=70, line_dash="dash", line_color="#ef4444", row=3, col=1)
            fig_k.add_hline(y=30, line_dash="dash", line_color="#22c55e", row=3, col=1)
        elif sub_ind == "MACD":
            df_m = macd_full.loc[idx_slice]
            h_colors = ["#ef4444" if v >= 0 else "#22c55e" for v in df_m["Histogram"].fillna(0)]
            fig_k.add_trace(
                go.Bar(x=df_m.index, y=df_m["Histogram"], name="柱狀圖", marker_color=h_colors),
                row=3, col=1,
            )
            fig_k.add_trace(
                go.Scatter(x=df_m.index, y=df_m["MACD"], name="MACD", line=dict(color="#3b82f6", width=1.5)),
                row=3, col=1,
            )
            fig_k.add_trace(
                go.Scatter(x=df_m.index, y=df_m["Signal"], name="Signal", line=dict(color="#f59e0b", width=1.5)),
                row=3, col=1,
            )
        else:
            df_kd = kd_full.loc[idx_slice]
            fig_k.add_trace(
                go.Scatter(x=df_kd.index, y=df_kd["K"], name="K(9)", line=dict(color="#f59e0b", width=1.6)),
                row=3, col=1,
            )
            fig_k.add_trace(
                go.Scatter(x=df_kd.index, y=df_kd["D"], name="D(9)", line=dict(color="#3b82f6", width=1.6)),
                row=3, col=1,
            )
            fig_k.add_hline(y=80, line_dash="dash", line_color="#ef4444", row=3, col=1)
            fig_k.add_hline(y=20, line_dash="dash", line_color="#22c55e", row=3, col=1)

        fig_k.update_layout(
            height=680,
            xaxis_rangeslider_visible=False,
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
            margin=dict(t=55, b=30, l=60, r=20),
        )
        fig_k.update_xaxes(gridcolor="#1e2535")
        fig_k.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_k)

# ══════════════════════════════════════════════════════════════════════════════
# 4. 主動式 ETF 成分股透視 & 持股重疊度分析（Holdings & Overlap Matrix）
# ══════════════════════════════════════════════════════════════════════════════
with st.container(border=True):
    st.subheader(":material/pie_chart: 主動式 ETF 成分股透視 & 持股重疊度分析", anchor=False)
    st.caption(
        "基於投信最新公開之前十大核心持股快照，分析經理人選股集中度、產業主題分佈，以及與基準 ETF（0050 / 00830 / 0056）和各檔主動式 ETF 之間的**持股重疊率**。"
    )

    htab1, htab2, htab3 = st.tabs([
        ":material/donut_large: 單一 ETF 前十大持股與產業配置",
        ":material/grid_on: ETF 持股重疊度矩陣 (Overlap Matrix)",
        ":material/stars: 經理人共識重押股雷達",
    ])

    # ── 子分頁 1：單一 ETF 前十大持股與產業配置 ─────────────────────────────
    with htab1:
        hold_etf_options = [s for s in selected_etfs if s in ETF_HOLDINGS] or list(ETF_HOLDINGS.keys())
        h_sid = st.selectbox(
            "選擇要檢視成分股的 ETF",
            options=hold_etf_options,
            format_func=lambda x: f"{x} {STOCK_NAMES.get(x, ACTIVE_ETF_META.get(x, {}).get('name', x))}",
            key="ae_hold_sid",
        )
        holdings_list = ETF_HOLDINGS.get(h_sid, [])
        if holdings_list:
            h_df = pd.DataFrame(holdings_list)
            cr5 = float(h_df["weight"].head(5).sum())
            cr10 = float(h_df["weight"].sum())
            top_sector = h_df.groupby("sector")["weight"].sum().idxmax()
            b_id = get_etf_benchmark_id(h_sid)
            b_holdings = {item["code"]: item["weight"] for item in ETF_HOLDINGS.get(b_id, [])}
            overlap_with_bench = sum(min(row["weight"], b_holdings.get(row["code"], 0.0)) for _, row in h_df.iterrows())
            shared_cnt = sum(1 for _, row in h_df.iterrows() if row["code"] in b_holdings)

            with st.container(horizontal=True):
                st.metric("前五大持股集中度 (CR5)", f"{cr5:.2f}%", border=True)
                st.metric("前十大持股合計 (CR10)", f"{cr10:.2f}%", border=True)
                st.metric("第一大核心產業", top_sector, border=True)
                st.metric(
                    f"與基準 {b_id} 前十重疊權重",
                    f"{overlap_with_bench:.2f}%",
                    delta=f"共同前十成分股 {shared_cnt} 檔",
                    delta_color="off",
                    border=True,
                )

            col_h1, col_h2 = st.columns(2)
            with col_h1:
                h_sorted = h_df.sort_values("weight", ascending=True)
                fig_hbar = go.Figure(
                    go.Bar(
                        x=h_sorted["weight"],
                        y=[f"{r['code']} {r['name']}" for _, r in h_sorted.iterrows()],
                        orientation="h",
                        marker_color="#3b82f6",
                        text=[f"{w:.2f}% ({s})" for w, s in zip(h_sorted["weight"], h_sorted["sector"])],
                        textposition="auto",
                    )
                )
                fig_hbar.update_layout(
                    title=f"{h_sid} 前十大核心持股權重 (%)",
                    height=360,
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font_color="#fafafa",
                    xaxis_title="持股權重 (%)",
                    margin=dict(t=45, b=30, l=150, r=20),
                )
                fig_hbar.update_xaxes(gridcolor="#1e2535")
                fig_hbar.update_yaxes(gridcolor="#1e2535")
                st.plotly_chart(fig_hbar)

            with col_h2:
                sec_df = h_df.groupby("sector", as_index=False)["weight"].sum().sort_values("weight", ascending=False)
                fig_sec = go.Figure(
                    go.Pie(
                        labels=sec_df["sector"],
                        values=sec_df["weight"],
                        hole=0.45,
                        textinfo="label+percent",
                        marker=dict(colors=PALETTE),
                    )
                )
                fig_sec.update_layout(
                    title=f"{h_sid} 前十大持股產業主題分佈",
                    height=360,
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font_color="#fafafa",
                    margin=dict(t=45, b=20, l=20, r=20),
                    showlegend=False,
                )
                st.plotly_chart(fig_sec)

            # 詳細表格（加上與基準權重差異對照）
            h_disp = h_df.copy()
            h_disp["基準權重%"] = h_disp["code"].map(lambda c: b_holdings.get(c, 0.0))
            h_disp["主動加減碼%"] = h_disp["weight"] - h_disp["基準權重%"]
            h_disp = h_disp.rename(columns={
                "code": "代號",
                "name": "成分股名稱",
                "sector": "產業主題",
                "weight": "ETF持股權重%",
            }).set_index("代號")
            st.dataframe(
                h_disp.style.map(
                    lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and v > 0
                    else ("color: #22c55e" if isinstance(v, (int, float)) and v < 0 else ""),
                    subset=["主動加減碼%"],
                ).format({
                    "ETF持股權重%": "{:.2f}%",
                    "基準權重%": "{:.2f}%",
                    "主動加減碼%": "{:+.2f}%",
                }),
            )

    # ── 子分頁 2：ETF 持股重疊度矩陣 (Overlap Matrix) ───────────────────────
    with htab2:
        st.caption(
            "**重疊權重指標 (Overlap Weight)** = $\\sum \\min(w_{i, A}, w_{i, B})$，衡量兩檔 ETF 前十大核心持股的相似度；"
            "括號內為**共同出現的前十大成分股檔數**。數值越高代表兩檔 ETF 買的股票越相近，同時持有分散效果較低。"
        )
        compare_pool = [s for s in selected_etfs if s in ETF_HOLDINGS]
        for bid in needed_bench_ids:
            if bid in ETF_HOLDINGS and bid not in compare_pool:
                compare_pool.append(bid)

        if len(compare_pool) >= 2:
            ov_z = []
            ov_text = []
            pool_labels = [f"{s} {STOCK_NAMES.get(s, '')}" for s in compare_pool]

            for s1 in compare_pool:
                w1 = {item["code"]: item["weight"] for item in ETF_HOLDINGS.get(s1, [])}
                row_z = []
                row_t = []
                for s2 in compare_pool:
                    w2 = {item["code"]: item["weight"] for item in ETF_HOLDINGS.get(s2, [])}
                    if s1 == s2:
                        ov_w = sum(w1.values())
                        cnt = len(w1)
                    else:
                        common_codes = set(w1.keys()) & set(w2.keys())
                        ov_w = sum(min(w1[c], w2[c]) for c in common_codes)
                        cnt = len(common_codes)
                    row_z.append(round(ov_w, 2))
                    row_t.append(f"{ov_w:.1f}%\n({cnt}檔)")
                ov_z.append(row_z)
                ov_text.append(row_t)

            fig_ov = go.Figure(
                go.Heatmap(
                    x=pool_labels,
                    y=pool_labels,
                    z=ov_z,
                    text=ov_text,
                    texttemplate="%{text}",
                    colorscale="YlOrRd",
                    colorbar=dict(title="重疊權重%"),
                )
            )
            fig_ov.update_layout(
                height=440,
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
                margin=dict(t=25, b=60, l=140, r=20),
            )
            st.plotly_chart(fig_ov)
        else:
            st.info("請選擇至少 2 檔有持股資料的 ETF 以檢視重疊度矩陣。")

    # ── 子分頁 3：經理人共識重押股雷達 ──────────────────────────────────────
    with htab3:
        st.caption("統計目前所選主動式 ETF 中，被最多位基金經理人同時納入前十大持股的「共識核心股」與各 ETF 配置權重。")
        active_only_pool = [s for s in selected_etfs if s in ETF_HOLDINGS]
        stock_agg: dict[str, dict] = {}
        for sid in active_only_pool:
            for item in ETF_HOLDINGS.get(sid, []):
                c = item["code"]
                if c not in stock_agg:
                    stock_agg[c] = {
                        "成分股代號": c,
                        "名稱": item["name"],
                        "產業主題": item["sector"],
                        "入選ETF檔數": 0,
                        "平均配置權重%": 0.0,
                        "最高配置權重%": 0.0,
                        "持有之主動式ETF明細": [],
                    }
                stock_agg[c]["入選ETF檔數"] += 1
                stock_agg[c]["平均配置權重%"] += item["weight"]
                stock_agg[c]["最高配置權重%"] = max(stock_agg[c]["最高配置權重%"], item["weight"])
                stock_agg[c]["持有之主動式ETF明細"].append(f"{sid} ({item['weight']:.2f}%)")

        if stock_agg:
            consensus_rows = []
            for c, info in stock_agg.items():
                cnt = info["入選ETF檔數"]
                consensus_rows.append({
                    "成分股": f"{c} {info['名稱']}",
                    "產業主題": info["產業主題"],
                    "入選ETF檔數": cnt,
                    "平均權重%": info["平均配置權重%"] / cnt,
                    "最高權重%": info["最高配置權重%"],
                    "各主動式ETF配置權重明細": "、".join(info["持有之主動式ETF明細"]),
                })
            cons_df = (
                pd.DataFrame(consensus_rows)
                .sort_values(["入選ETF檔數", "平均權重%"], ascending=[False, False])
                .set_index("成分股")
            )
            st.dataframe(
                cons_df,
                column_config={
                    "入選ETF檔數": st.column_config.ProgressColumn(
                        "經理人共識度 (入選檔數)",
                        min_value=0,
                        max_value=max(len(active_only_pool), 1),
                        format="%d 檔",
                    ),
                    "平均權重%": st.column_config.NumberColumn("平均權重", format="%.2f%%"),
                    "最高權重%": st.column_config.NumberColumn("最高權重", format="%.2f%%"),
                    "各主動式ETF配置權重明細": st.column_config.TextColumn("持有之主動式 ETF 與權重", width="large"),
                },
            )

