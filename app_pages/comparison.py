"""多股比較與投資組合最佳化頁 — 標準化走勢、報酬排行、相關性熱圖、馬可維茲效率前緣 (Efficient Frontier)"""

import importlib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import src.indicators as _ind
importlib.reload(_ind)

from src.indicators import STOCK_NAMES, get_horizon_slice, get_stock_ids, load_stock

COLORS = ["#ef4444", "#3b82f6", "#22c55e", "#f97316", "#a855f7", "#06b6d4", "#ec4899", "#eab308"]

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header(":material/tune: 比較與配置設定", divider=True)

    stock_ids = get_stock_ids()
    default_picks = [s for s in ["0050", "2330", "00403A", "00988A"] if s in stock_ids]
    if len(default_picks) < 2:
        default_picks = stock_ids[:min(4, len(stock_ids))]

    selected_stocks = st.multiselect(
        "選擇股票／ETF（最多 8 支）",
        stock_ids,
        default=default_picks,
        format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
        max_selections=8,
        key="cmp_stocks",
    )

    horizon = st.pills(
        "比較區間",
        ["1個月", "3個月", "6個月", "1年", "3年", "全部"],
        default="1年",
        key="cmp_horizon",
    ) or "1年"

    normalize = st.toggle("走勢圖標準化（起始=100）", value=True)

    st.divider()
    st.subheader(":material/account_balance_wallet: 投資組合試算金額", anchor=False)
    portfolio_capital = st.number_input(
        "預計配置總資金 (NTD)",
        min_value=50_000,
        max_value=100_000_000,
        value=1_000_000,
        step=100_000,
        format="%d",
    )

if not selected_stocks:
    st.info("請在左側選擇至少一支股票或 ETF。", icon=":material/info:")
    st.stop()

# ── 載入資料 ──────────────────────────────────────────────────────────────────
stock_data: dict[str, pd.DataFrame] = {}
stock_full_data: dict[str, pd.DataFrame] = {}
for sid in selected_stocks:
    df_full = load_stock(sid)
    if not df_full.empty:
        stock_full_data[sid] = df_full
        stock_data[sid] = get_horizon_slice(df_full, horizon)

if not stock_data:
    st.error("無法載入任何股票資料")
    st.stop()

st.subheader(":material/compare_arrows: 多股比較 & 投資組合權重最佳化", anchor=False)

# ── 1. 標準化走勢比較（Plotly）────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/show_chart: 價格／標準化走勢比較", anchor=False)
    st.caption("以各股在所選區間起始收盤價為基準標準化（起始 = 100），方便跨價位直接比較累積漲跌幅。")

    fig = go.Figure()
    for i, (sid, df) in enumerate(stock_data.items()):
        close = df["Close"].dropna()
        if close.empty:
            continue
        y_vals = (close / close.iloc[0] * 100) if normalize else close
        label = f"{sid} {STOCK_NAMES.get(sid, '')}"
        fig.add_trace(
            go.Scatter(
                x=close.index,
                y=y_vals,
                name=label,
                line=dict(color=COLORS[i % len(COLORS)], width=2.2),
                hovertemplate=f"{label}<br>%{{x|%Y/%m/%d}}<br>{'指數' if normalize else '收盤'}: %{{y:.2f}}<extra></extra>",
            )
        )

    if normalize:
        fig.add_hline(y=100, line_dash="dot", line_color="#475569")

    fig.update_layout(
        height=420,
        hovermode="x unified",
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font_color="#fafafa",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=40, b=20, l=60, r=20),
        yaxis_title="標準化指數 (起點=100)" if normalize else "收盤價 (NTD)",
    )
    fig.update_xaxes(gridcolor="#1e2535", showgrid=True)
    fig.update_yaxes(gridcolor="#1e2535", showgrid=True)
    st.plotly_chart(fig)

# ── 2. 報酬率排行 ─────────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/leaderboard: 各期間報酬率與風險排行", anchor=False)

    periods = {"1個月": 21, "3個月": 63, "6個月": 126, "1年": 252}
    rows = []
    for sid, df_f in stock_full_data.items():
        row: dict = {"股票": f"{sid} {STOCK_NAMES.get(sid, '')}"}
        for label, days in periods.items():
            if len(df_f) >= days:
                ret = (df_f["Close"].iloc[-1] / df_f["Close"].iloc[-days] - 1) * 100
            else:
                ret = (df_f["Close"].iloc[-1] / df_f["Close"].iloc[0] - 1) * 100
            row[label] = float(ret)

        df_sub = stock_data[sid]
        r_daily = df_sub["Close"].pct_change().dropna()
        vol_ann = float(r_daily.std() * np.sqrt(252) * 100) if len(r_daily) > 1 else 0.0
        cum_max = df_sub["Close"].cummax()
        mdd = float(((df_sub["Close"] - cum_max) / cum_max).min() * 100)
        row["區間年化波動率"] = vol_ann
        row["區間最大回撤"] = mdd
        rows.append(row)

    ranking_df = pd.DataFrame(rows).set_index("股票")

    def color_ret(val):
        if isinstance(val, (int, float)) and pd.notna(val):
            return "color: #ef4444; font-weight: 600" if val >= 0 else "color: #22c55e"
        return ""

    st.dataframe(
        ranking_df.style.map(color_ret, subset=["1個月", "3個月", "6個月", "1年"]).format({
            "1個月": "{:+.2f}%",
            "3個月": "{:+.2f}%",
            "6個月": "{:+.2f}%",
            "1年": "{:+.2f}%",
            "區間年化波動率": "{:.2f}%",
            "區間最大回撤": "{:.2f}%",
        }),
    )

# ── 3. 相關性熱圖 ─────────────────────────────────────────────────────────────
if len(stock_data) >= 2:
    with st.container(border=True):
        st.subheader(":material/grid_on: 日報酬率相關性熱圖 (Correlation Matrix)", anchor=False)
        st.caption("接近 +1 表示同向波動，接近 0 或負值表示具備良好的**資產分散配置效果**。")

        close_dict = {
            f"{sid} {STOCK_NAMES.get(sid, '')}": df["Close"]
            for sid, df in stock_data.items()
        }
        close_all = pd.DataFrame(close_dict).dropna()
        ret_all = close_all.pct_change().dropna()

        if len(ret_all) >= 5:
            corr = ret_all.corr()
            labels = list(corr.columns)
            values = corr.values
            text = [[f"{v:.2f}" for v in row] for row in values]

            fig_corr = go.Figure(
                go.Heatmap(
                    x=labels,
                    y=labels,
                    z=values,
                    text=text,
                    texttemplate="%{text}",
                    colorscale="RdBu_r",
                    zmin=-1,
                    zmax=1,
                    colorbar=dict(title="相關係數"),
                )
            )
            fig_corr.update_layout(
                height=360,
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
                margin=dict(t=20, b=60, l=120, r=20),
            )
            st.plotly_chart(fig_corr)

# ══════════════════════════════════════════════════════════════════════════════
# 4. 投資組合權重最佳化（馬可維茲效率前緣 Efficient Frontier）
# ══════════════════════════════════════════════════════════════════════════════
if len(stock_data) >= 2:
    with st.container(border=True):
        st.subheader(":material/balance: 馬可維茲投資組合權重最佳化 (Efficient Frontier)", anchor=False)
        st.caption(
            "利用蒙地卡羅模擬 3,000 組資產權重配置，在共同交易日區間內尋找 **「最大夏普比率組合 (Max Sharpe)」** 與 **「最小波動率組合 (Min Volatility)」** 的黃金比例。"
        )

        close_aligned = pd.DataFrame({
            sid: df["Close"] for sid, df in stock_data.items()
        }).dropna()
        rets_aligned = close_aligned.pct_change().dropna()

        if len(rets_aligned) < 10:
            st.warning("所選標的之共同重疊交易日不足 10 天，請調整比較區間以進行投資組合最佳化。")
        else:
            n_assets = len(close_aligned.columns)
            asset_ids = list(close_aligned.columns)
            asset_labels = [f"{s} {STOCK_NAMES.get(s, '')}" for s in asset_ids]

            mean_daily = rets_aligned.mean().values
            cov_daily = rets_aligned.cov().values
            rf = 0.015  # 年化無風險利率 1.5%

            # 固定隨機種子確保穩定重現，產生 3000 組權重（含端點與集中權重）
            rng = np.random.default_rng(42)
            w_dir1 = rng.dirichlet(np.ones(n_assets), size=2000)
            w_dir2 = rng.dirichlet(np.full(n_assets, 0.35), size=1000)  # 探索邊界高集中度組合
            w_eq = np.full((1, n_assets), 1.0 / n_assets)
            weights_all = np.vstack([w_dir1, w_dir2, w_eq])

            port_returns = (weights_all @ mean_daily) * 252 * 100.0
            # 向量化計算投組標準差: sqrt(diag(W @ Cov @ W.T)) * sqrt(252)
            port_vars = np.einsum("ij,jk,ik->i", weights_all, cov_daily, weights_all)
            port_vols = np.sqrt(np.maximum(port_vars, 1e-12)) * np.sqrt(252) * 100.0
            port_sharpes = (port_returns - rf * 100.0) / np.maximum(port_vols, 1e-6)

            idx_max_sharpe = int(np.argmax(port_sharpes))
            idx_min_vol = int(np.argmin(port_vols))
            idx_eq = len(weights_all) - 1

            w_best_sharpe = weights_all[idx_max_sharpe]
            w_min_vol = weights_all[idx_min_vol]
            w_equal = weights_all[idx_eq]

            # KPI 卡片展示三種代表性組合
            with st.container(horizontal=True):
                st.metric(
                    "🌟 最大夏普組合 (Max Sharpe)",
                    f"Sharpe {port_sharpes[idx_max_sharpe]:.2f}",
                    delta=f"年化報酬 {port_returns[idx_max_sharpe]:+.1f}% ｜ 波動 {port_vols[idx_max_sharpe]:.1f}%",
                    delta_color="inverse",
                    border=True,
                )
                st.metric(
                    "🛡️ 最小波動組合 (Min Volatility)",
                    f"波動率 {port_vols[idx_min_vol]:.2f}%",
                    delta=f"年化報酬 {port_returns[idx_min_vol]:+.1f}% ｜ Sharpe {port_sharpes[idx_min_vol]:.2f}",
                    delta_color="off",
                    border=True,
                )
                st.metric(
                    "⚖️ 等權重組合 (1/N 平均分配)",
                    f"Sharpe {port_sharpes[idx_eq]:.2f}",
                    delta=f"年化報酬 {port_returns[idx_eq]:+.1f}% ｜ 波動 {port_vols[idx_eq]:.1f}%",
                    delta_color="off",
                    border=True,
                )

            ef_col1, ef_col2 = st.columns([3, 2])
            with ef_col1:
                fig_ef = go.Figure()
                # 散佈雲
                fig_ef.add_trace(
                    go.Scatter(
                        x=port_vols,
                        y=port_returns,
                        mode="markers",
                        name="模擬投組 (3,000組)",
                        marker=dict(
                            size=5,
                            color=port_sharpes,
                            colorscale="Viridis",
                            opacity=0.55,
                            colorbar=dict(title="Sharpe"),
                        ),
                        hovertemplate="年化波動: %{x:.2f}%<br>年化報酬: %{y:+.2f}%<extra></extra>",
                    )
                )
                # 個股單獨持有一點
                for i, sid in enumerate(asset_ids):
                    s_ret = float(mean_daily[i] * 252 * 100.0)
                    s_vol = float(np.sqrt(cov_daily[i, i]) * np.sqrt(252) * 100.0)
                    fig_ef.add_trace(
                        go.Scatter(
                            x=[s_vol],
                            y=[s_ret],
                            mode="markers+text",
                            text=[sid],
                            textposition="top center",
                            name=f"{sid} 單一持有",
                            marker=dict(size=11, color="#f8fafc", line=dict(width=1.5, color="#0f172a")),
                        )
                    )
                # 標記最大夏普、最小波動、等權重
                fig_ef.add_trace(
                    go.Scatter(
                        x=[port_vols[idx_max_sharpe]],
                        y=[port_returns[idx_max_sharpe]],
                        mode="markers+text",
                        text=["★ 最大夏普"],
                        textposition="bottom center",
                        name="最大夏普組合",
                        marker=dict(symbol="star", size=18, color="#ef4444", line=dict(width=1, color="#ffffff")),
                    )
                )
                fig_ef.add_trace(
                    go.Scatter(
                        x=[port_vols[idx_min_vol]],
                        y=[port_returns[idx_min_vol]],
                        mode="markers+text",
                        text=["◆ 最小波動"],
                        textposition="bottom center",
                        name="最小波動組合",
                        marker=dict(symbol="diamond", size=15, color="#22c55e", line=dict(width=1, color="#ffffff")),
                    )
                )
                fig_ef.add_trace(
                    go.Scatter(
                        x=[port_vols[idx_eq]],
                        y=[port_returns[idx_eq]],
                        mode="markers+text",
                        text=["● 等權重"],
                        textposition="top center",
                        name="等權重組合",
                        marker=dict(symbol="circle", size=13, color="#f59e0b", line=dict(width=1, color="#ffffff")),
                    )
                )

                fig_ef.update_layout(
                    title="馬可維茲效率前緣 (風險 vs 年化報酬)",
                    xaxis_title="年化波動率 / 風險 (%)",
                    yaxis_title="預期年化報酬率 (%)",
                    height=410,
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font_color="#fafafa",
                    showlegend=False,
                    margin=dict(t=45, b=40, l=60, r=20),
                )
                fig_ef.update_xaxes(gridcolor="#1e2535")
                fig_ef.update_yaxes(gridcolor="#1e2535")
                st.plotly_chart(fig_ef)

            with ef_col2:
                pie_target = st.segmented_control(
                    "檢視圓餅圖配置方案",
                    options=["🌟 最大夏普組合", "🛡️ 最小波動組合", "⚖️ 等權重組合"],
                    default="🌟 最大夏普組合",
                ) or "🌟 最大夏普組合"

                w_chosen = (
                    w_best_sharpe if "夏普" in pie_target
                    else (w_min_vol if "波動" in pie_target else w_equal)
                )
                fig_wpie = go.Figure(
                    go.Pie(
                        labels=asset_labels,
                        values=np.round(w_chosen * 100, 2),
                        hole=0.45,
                        textinfo="label+percent",
                        marker=dict(colors=COLORS[:n_assets]),
                    )
                )
                fig_wpie.update_layout(
                    title=f"{pie_target} — 建議權重分配",
                    height=350,
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font_color="#fafafa",
                    showlegend=False,
                    margin=dict(t=45, b=20, l=20, r=20),
                )
                st.plotly_chart(fig_wpie)

            # 權重與建議配置金額對照表
            alloc_rows = []
            for i, sid in enumerate(asset_ids):
                latest_p = float(close_aligned[sid].iloc[-1])
                alloc_rows.append({
                    "標的": f"{sid} {STOCK_NAMES.get(sid, '')}",
                    "最新股價": latest_p,
                    "最大夏普權重%": w_best_sharpe[i] * 100,
                    "最大夏普配置金額": portfolio_capital * w_best_sharpe[i],
                    "最小波動權重%": w_min_vol[i] * 100,
                    "最小波動配置金額": portfolio_capital * w_min_vol[i],
                    "等權重%": w_equal[i] * 100,
                })
            alloc_df = pd.DataFrame(alloc_rows).set_index("標的")
            st.markdown(f"**💰 依總資金 NT${portfolio_capital:,.0f} 計算之最佳配置權重與金額明細**")
            st.dataframe(
                alloc_df.style.format({
                    "最新股價": "NT${:.2f}",
                    "最大夏普權重%": "{:.2f}%",
                    "最大夏普配置金額": "NT${:,.0f}",
                    "最小波動權重%": "{:.2f}%",
                    "最小波動配置金額": "NT${:,.0f}",
                    "等權重%": "{:.2f}%",
                }),
            )

            # 投組歷史累積淨值走勢對比
            norm_prices = close_aligned / close_aligned.iloc[0]
            curve_max_sh = (norm_prices.values @ w_best_sharpe) * 100.0
            curve_min_vol = (norm_prices.values @ w_min_vol) * 100.0
            curve_eq = (norm_prices.values @ w_equal) * 100.0

            fig_pcurve = go.Figure()
            fig_pcurve.add_trace(go.Scatter(x=close_aligned.index, y=curve_max_sh, name="🌟 最大夏普組合", line=dict(color="#ef4444", width=2.6)))
            fig_pcurve.add_trace(go.Scatter(x=close_aligned.index, y=curve_min_vol, name="🛡️ 最小波動組合", line=dict(color="#22c55e", width=2.2)))
            fig_pcurve.add_trace(go.Scatter(x=close_aligned.index, y=curve_eq, name="⚖️ 等權重組合 (1/N)", line=dict(color="#f59e0b", width=2.0, dash="dash")))
            fig_pcurve.add_hline(y=100, line_dash="dot", line_color="#475569")
            fig_pcurve.update_layout(
                title="三種最佳化投資組合 — 區間標準化淨值走勢對比 (起點 = 100)",
                yaxis_title="投組標準化淨值",
                height=340,
                hovermode="x unified",
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                margin=dict(t=45, b=25, l=60, r=20),
            )
            fig_pcurve.update_xaxes(gridcolor="#1e2535")
            fig_pcurve.update_yaxes(gridcolor="#1e2535")
            st.plotly_chart(fig_pcurve)

# ── 5. 各股最新狀態 ───────────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(":material/info: 各股最新狀態", anchor=False)
    status_rows = []
    for sid, df in stock_data.items():
        close = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else close
        chg = close - prev
        chg_pct = chg / prev * 100
        status_rows.append({
            "股票": f"{sid} {STOCK_NAMES.get(sid, '')}",
            "收盤": close,
            "漲跌": chg,
            "漲跌%": chg_pct,
            "最新日期": df.index[-1].strftime("%Y/%m/%d"),
            "資料筆數": len(df),
        })

    status_df = pd.DataFrame(status_rows).set_index("股票")
    st.dataframe(
        status_df.style.map(
            lambda v: "color: #ef4444" if isinstance(v, (int, float)) and v >= 0
            else ("color: #22c55e" if isinstance(v, (int, float)) and v < 0 else ""),
            subset=["漲跌", "漲跌%"],
        ).format({
            "收盤": "{:.2f}",
            "漲跌": "{:+.2f}",
            "漲跌%": "{:+.2f}%",
        }),
    )
