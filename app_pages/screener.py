"""今日訊號雷達 & Discord 推播頁 — 全市場多指標掃描、綜合多空評分、四象限強弱雷達與 Discord Webhook 一鍵推播"""

import importlib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import src.indicators as _ind
import src.config as _cfg
import src.notifier as _ntf
importlib.reload(_ind)
importlib.reload(_cfg)
importlib.reload(_ntf)

from src.config import get_discord_webhook_url, save_discord_webhook_url
from src.forecaster import get_ai_forecast_summary, get_portfolio_alert_summary
from src.indicators import (
    ACTIVE_ETF_META,
    STOCK_NAMES,
    calc_bbands,
    calc_kd,
    calc_ma,
    calc_macd,
    calc_rsi,
    get_stock_ids,
    load_stock,
)
from src.notifier import notify_discord

st.subheader(":material/radar: 今日訊號雷達 & Discord 智慧推播", anchor=False)
st.caption("自動掃描所有個股、被動式 ETF 與主動式 ETF 的最新技術指標（MA、布林通道、RSI、MACD、KD、量能），計算綜合多空評分並支援一鍵發送彩色排版卡片至 **Discord Webhook**。")

# ── Sidebar：篩選與推播設定 ───────────────────────────────────────────────────
with st.sidebar:
    st.header(":material/filter_alt: 雷達篩選設定", divider=True)

    category_filter = st.pills(
        "標的類別",
        ["全部標的", "主動式 ETF", "一般個股與被動 ETF"],
        default="全部標的",
    ) or "全部標的"

    signal_filter = st.pills(
        "多空訊號篩選",
        ["全部顯示", "偏多與買訊 🔴", "偏空與賣訊 🟢", "今日新觸發轉折 ⚡"],
        default="全部顯示",
    ) or "全部顯示"



# ═══════════════════════════════════════════════════════════════════════════════
# 全市場技術指標掃描引擎
# ═══════════════════════════════════════════════════════════════════════════════

all_stock_ids = get_stock_ids()
if category_filter == "主動式 ETF":
    scan_ids = [s for s in all_stock_ids if s.endswith("A") or s in ACTIVE_ETF_META]
elif category_filter == "一般個股與被動 ETF":
    scan_ids = [s for s in all_stock_ids if not (s.endswith("A") or s in ACTIVE_ETF_META)]
else:
    scan_ids = all_stock_ids

scan_rows = []
fresh_alerts = []

for sid in scan_ids:
    df = load_stock(sid)
    if len(df) < 25:
        continue

    close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])
    chg_pct = (close / prev_close - 1.0) * 100.0
    ret_20d = (close / float(df["Close"].iloc[-min(21, len(df))]) - 1.0) * 100.0

    # 1. 均線
    df_ma = calc_ma(df, [5, 10, 20, 60])
    ma5 = float(df_ma["MA5"].iloc[-1])
    ma20 = float(df_ma["MA20"].iloc[-1])
    ma60 = float(df_ma["MA60"].iloc[-1]) if pd.notna(df_ma["MA60"].iloc[-1]) else ma20
    ma5_prev = float(df_ma["MA5"].iloc[-2])
    ma20_prev = float(df_ma["MA20"].iloc[-2])

    ma_cross_up = (ma5 > ma20) and (ma5_prev <= ma20_prev)
    ma_cross_dn = (ma5 < ma20) and (ma5_prev >= ma20_prev)

    # 2. 布林通道
    df_bb = calc_bbands(df, 20, 2.0)
    b_up = float(df_bb["b_up"].iloc[-1])
    b_low = float(df_bb["b_low"].iloc[-1])
    b_mid = float(df_bb["b_mid"].iloc[-1])
    pct_b = ((close - b_low) / (b_up - b_low) * 100.0) if (b_up - b_low) > 1e-6 else 50.0

    bb_break_up = close > b_up and prev_close <= float(df_bb["b_up"].iloc[-2])
    bb_rebound_low = close < b_low

    # 3. RSI(14)
    rsi_s = calc_rsi(df, 14)
    rsi_val = float(rsi_s.iloc[-1]) if pd.notna(rsi_s.iloc[-1]) else 50.0
    rsi_prev = float(rsi_s.iloc[-2]) if pd.notna(rsi_s.iloc[-2]) else 50.0
    rsi_turn_up = (rsi_val > 30) and (rsi_prev <= 30)

    # 4. MACD
    df_macd = calc_macd(df)
    macd_v = float(df_macd["MACD"].iloc[-1])
    sig_v = float(df_macd["Signal"].iloc[-1])
    hist_v = float(df_macd["Histogram"].iloc[-1])
    hist_prev = float(df_macd["Histogram"].iloc[-2])
    macd_cross_up = (hist_v > 0) and (hist_prev <= 0)
    macd_cross_dn = (hist_v < 0) and (hist_prev >= 0)

    # 5. KD(9)
    df_kd = calc_kd(df, 9)
    k_val = float(df_kd["K"].iloc[-1])
    d_val = float(df_kd["D"].iloc[-1])
    k_prev = float(df_kd["K"].iloc[-2])
    d_prev = float(df_kd["D"].iloc[-2])
    kd_cross_up = (k_val > d_val) and (k_prev <= d_prev) and (k_val <= 45)
    kd_cross_dn = (k_val < d_val) and (k_prev >= d_prev) and (k_val >= 65)

    # 6. 量比 (今日量 / 5日均量)
    vol_now = float(df["Volume"].iloc[-1])
    vol_ma5 = float(df["Volume"].tail(5).mean())
    vol_ratio = (vol_now / vol_ma5) if vol_ma5 > 0 else 1.0

    # ── 計算綜合多空評分 (-5 ～ +5) 與新觸發訊號 ─────────────────────────────
    score = 0
    triggers = []

    # 均線趨勢分數
    if close > ma20:
        score += 1
    else:
        score -= 1

    if ma5 > ma20 > ma60:
        score += 1
        ma_status = "多頭排列 📈"
    elif ma5 < ma20 < ma60:
        score -= 1
        ma_status = "空頭排列 📉"
    elif close >= ma20:
        ma_status = "站上月線"
    else:
        ma_status = "月線之下"

    if ma_cross_up:
        score += 2
        ma_status = "MA5 金叉 MA20 🔴"
        triggers.append("MA黃金交叉")
    elif ma_cross_dn:
        score -= 2
        ma_status = "MA5 死叉 MA20 🟢"
        triggers.append("MA死亡交叉")

    # MACD 分數
    if macd_cross_up:
        score += 2
        macd_status = "MACD 金叉翻紅 🔴"
        triggers.append("MACD金叉")
    elif macd_cross_dn:
        score -= 2
        macd_status = "MACD 死叉翻綠 🟢"
        triggers.append("MACD死叉")
    elif hist_v > 0:
        score += 1
        macd_status = "紅柱多頭" if hist_v >= hist_prev else "紅柱收斂"
    else:
        score -= 1
        macd_status = "綠柱收斂" if hist_v > hist_prev else "綠柱空頭"

    # KD 分數
    if kd_cross_up:
        score += 1
        kd_status = f"低檔金叉 🔴 (K={k_val:.0f})"
        triggers.append("KD低檔金叉")
    elif kd_cross_dn:
        score -= 1
        kd_status = f"高檔死叉 🟢 (K={k_val:.0f})"
        triggers.append("KD高檔死叉")
    elif k_val >= 80:
        score += 1
        kd_status = f"高檔鈍化強勢 (K={k_val:.0f})"
    elif k_val <= 20:
        kd_status = f"低檔超賣區 (K={k_val:.0f})"
    else:
        kd_status = f"K={k_val:.0f} / D={d_val:.0f}"

    # 布林與 RSI 補充
    if bb_break_up:
        score += 1
        triggers.append("突破布林上軌")
    elif bb_rebound_low:
        triggers.append("觸及布林下軌")
    if rsi_turn_up:
        score += 1
        triggers.append("RSI超賣反彈")

    score = max(-5, min(5, score))

    if score >= 3 or ("MA黃金交叉" in triggers) or ("MACD金叉" in triggers):
        action_badge = "🔥 強烈買訊 / 多頭"
    elif score >= 1:
        action_badge = "🔴 偏多格局"
    elif score == 0:
        action_badge = "⚪ 中性盤整"
    elif score >= -2:
        action_badge = "🟢 偏空整理"
    else:
        action_badge = "⚠️ 轉弱 / 賣訊"

    name = STOCK_NAMES.get(sid, ACTIVE_ETF_META.get(sid, {}).get("name", sid))
    if triggers:
        fresh_alerts.append({
            "sid": sid,
            "name": name,
            "close": close,
            "chg_pct": chg_pct,
            "score": score,
            "triggers": "、".join(triggers),
            "action": action_badge,
        })

    scan_rows.append({
        "代號": sid,
        "名稱": f"{sid} {name}",
        "類別": "主動式ETF" if (sid.endswith("A") or sid in ACTIVE_ETF_META) else "個股/被動ETF",
        "最新日期": df.index[-1].strftime("%Y/%m/%d"),
        "收盤價": close,
        "單日漲跌%": chg_pct,
        "20日漲跌%": ret_20d,
        "量比(vs 5MA)": vol_ratio,
        "均線狀態": ma_status,
        "MACD狀態": macd_status,
        "KD狀態": kd_status,
        "RSI(14)": rsi_val,
        "布林%B": pct_b,
        "今日新觸發": "、".join(triggers) if triggers else "—",
        "多空評分": score,
        "綜合研判": action_badge,
    })

scan_df_all = pd.DataFrame(scan_rows)
if scan_df_all.empty:
    st.warning("目前無足夠歷史資料可供掃描。")
    st.stop()

# ── 頂部統計 KPI ──────────────────────────────────────────────────────────────
n_bull = int((scan_df_all["多空評分"] >= 1).sum())
n_bear = int((scan_df_all["多空評分"] <= -1).sum())
n_neutral = int((scan_df_all["多空評分"] == 0).sum())
n_triggers = len(fresh_alerts)

with st.container(horizontal=True):
    st.metric("掃描標的總數", f"{len(scan_df_all)} 檔", delta=f"最新資料日 {scan_df_all['最新日期'].max()}", delta_color="off", delta_arrow="off", border=True)
    st.metric("🔴 偏多 / 買方格局", f"{n_bull} 檔", delta=f"佔比 {n_bull/len(scan_df_all)*100:.0f}%", delta_color="red", delta_arrow="up", border=True)
    st.metric("🟢 偏空 / 整理格局", f"{n_bear} 檔", delta=f"中性 {n_neutral} 檔", delta_color="green", delta_arrow="down", border=True)
    st.metric("⚡ 今日新觸發轉折訊號", f"{n_triggers} 檔", delta="含金叉/死叉/突破", delta_color="off", delta_arrow="off", border=True)

# ── 今日焦點轉折快訊 ──────────────────────────────────────────────────────────
if fresh_alerts:
    with st.container(border=True):
        st.subheader(":material/bolt: 今日新觸發技術轉折快訊", anchor=False)
        cols_alert = st.columns(min(4, len(fresh_alerts)))
        for idx, item in enumerate(fresh_alerts):
            with cols_alert[idx % len(cols_alert)]:
                st.metric(
                    label=f"{item['sid']} {item['name']}",
                    value=f"NT${item['close']:.2f} ({item['chg_pct']:+.2f}%)",
                    delta=f"⚡ {item['triggers']} (評分 {item['score']:+d})",
                    delta_color="red" if item["score"] > 0 else ("green" if item["score"] < 0 else "gray"),
                    delta_arrow="up" if item["score"] > 0 else ("down" if item["score"] < 0 else "off"),
                    border=True,
                )

# ── 依使用者條件過濾表格 ──────────────────────────────────────────────────────
disp_df = scan_df_all.copy()
if signal_filter == "偏多與買訊 🔴":
    disp_df = disp_df[disp_df["多空評分"] >= 1]
elif signal_filter == "偏空與賣訊 🟢":
    disp_df = disp_df[disp_df["多空評分"] <= -1]
elif signal_filter == "今日新觸發轉折 ⚡":
    disp_df = disp_df[disp_df["今日新觸發"] != "—"]

disp_df = disp_df.sort_values(["多空評分", "20日漲跌%"], ascending=[False, False]).set_index("名稱")

with st.container(border=True):
    st.subheader(":material/table_view: 全市場多指標訊號總覽表", anchor=False)
    st.caption("評分範圍 `-5`（極空）至 `+5`（極多）；**布林 %B > 100%** 代表突破上軌、**< 0%** 代表跌破下軌。")

    def color_chg(v):
        if isinstance(v, (int, float)) and pd.notna(v):
            return "color: #ef4444; font-weight: 600" if v > 0 else ("color: #22c55e" if v < 0 else "")
        return ""

    st.dataframe(
        disp_df.drop(columns=["代號"]).style.map(
            color_chg, subset=["單日漲跌%", "20日漲跌%", "多空評分"]
        ).format({
            "收盤價": "{:.2f}",
            "單日漲跌%": "{:+.2f}%",
            "20日漲跌%": "{:+.2f}%",
            "量比(vs 5MA)": "{:.2f}x",
            "RSI(14)": "{:.1f}",
            "布林%B": "{:.1f}%",
            "多空評分": "{:+d}",
        }),
    )

# ── 四象限強弱勢動能雷達圖 (RSI vs 20日漲跌幅，氣泡大小=量比，顏色=多空評分) ──
with st.container(border=True):
    st.subheader(":material/scatter_plot: 四象限多空動能雷達圖 (RSI vs 20日報酬率)", anchor=False)
    st.caption("右上象限＝強勢主升段（RSI > 50 且 20日正報酬）；右下象限＝低檔轉強區；氣泡大小代表今日量比。")

    fig_q = go.Figure()
    fig_q.add_trace(
        go.Scatter(
            x=scan_df_all["RSI(14)"],
            y=scan_df_all["20日漲跌%"],
            mode="markers+text",
            text=scan_df_all["代號"],
            textposition="top center",
            marker=dict(
                size=np.clip(scan_df_all["量比(vs 5MA)"] * 14, 10, 32),
                color=scan_df_all["多空評分"],
                colorscale="RdYlGn_r",
                cmin=-5,
                cmax=5,
                colorbar=dict(title="多空評分"),
                line=dict(width=1, color="#f8fafc"),
            ),
            customdata=np.stack([scan_df_all["名稱"], scan_df_all["綜合研判"], scan_df_all["均線狀態"]], axis=-1),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "RSI(14): %{x:.1f}<br>"
                "20日漲跌: %{y:+.2f}%<br>"
                "均線: %{customdata[2]}<br>"
                "研判: %{customdata[1]}<extra></extra>"
            ),
        )
    )
    fig_q.add_vline(x=50, line_dash="dash", line_color="#64748b")
    fig_q.add_vline(x=70, line_dash="dot", line_color="#ef4444", annotation_text="RSI 超買(70)")
    fig_q.add_vline(x=30, line_dash="dot", line_color="#22c55e", annotation_text="RSI 超賣(30)")
    fig_q.add_hline(y=0, line_dash="dash", line_color="#64748b")
    fig_q.update_layout(
        height=420,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font_color="#fafafa",
        xaxis_title="RSI (14) 動能指標",
        yaxis_title="近 20 日累積漲跌幅 (%)",
        margin=dict(t=30, b=40, l=60, r=20),
    )
    fig_q.update_xaxes(gridcolor="#1e2535")
    fig_q.update_yaxes(gridcolor="#1e2535")
    st.plotly_chart(fig_q)

# ═══════════════════════════════════════════════════════════════════════════════
# Discord Webhook 智慧推播發送中心（串接 src/notifier.py & .env）
# ═══════════════════════════════════════════════════════════════════════════════
with st.container(border=True):
    st.subheader(":material/send: Discord Webhook 訊號推播中心（完全免費・支援彩色排版卡片）", anchor=False)
    st.caption(
        "無須申請付費 IFTTT Pro 或複雜 Token，只要在 Discord 頻道複製 **Webhook 網址** 貼到下方，即可一鍵將今日多空訊號日報發送到你的 Discord 頻道！"
    )

    with st.expander(":material/help_outline: 30 秒取得 Discord Webhook 網址教學（只需設定一次）", expanded=False):
        st.markdown("""
1. 打開你的 **Discord**（若還沒有自己的伺服器，點左側 `+` 號免費建立一個私人伺服器）。
2. 在想接收股票通知的文字頻道名稱旁，點擊 ⚙️ **「編輯頻道 (Edit Channel)」**。
3. 點選左側選單的 **「整合 (Integrations)」** → **「Webhooks」** → 點擊 **「新 Webhook (New Webhook)」**。
4. 點擊 **「複製 Webhook 網址 (Copy Webhook URL)」**（格式為 `https://discord.com/api/webhooks/...`）。
5. 貼入下方欄位並按下「儲存網址至 .env」或直接點擊發送即可！
        """)

    saved_webhook = get_discord_webhook_url()
    wh_col1, wh_col2 = st.columns([4, 1])
    with wh_col1:
        webhook_input = st.text_input(
            "Discord Webhook 網址 (自動儲存於本機 .env，不會上傳至 GitHub)",
            value=saved_webhook,
            type="password",
            placeholder="https://discord.com/api/webhooks/...",
        )
    with wh_col2:
        st.space("small")
        if st.button(":material/save: 儲存網址", width="stretch"):
            if webhook_input.strip():
                save_discord_webhook_url(webhook_input.strip())
                st.toast("已將 Discord Webhook 網址儲存至 .env！", icon=":material/check_circle:")
            else:
                st.warning("請先輸入有效的 Webhook 網址")

    top_bulls = scan_df_all[scan_df_all["多空評分"] >= 2].sort_values("多空評分", ascending=False)
    bull_summary = (
        "、".join(f"**{r['代號']} {STOCK_NAMES.get(r['代號'], '')}** (`NT${r['收盤價']:.2f}`, 評分 `{r['多空評分']:+d}`)" for _, r in top_bulls.head(6).iterrows())
        if not top_bulls.empty else "今日無強勢買訊標的"
    )

    top_bears = scan_df_all[scan_df_all["多空評分"] <= -2].sort_values("多空評分", ascending=True)
    bear_summary = (
        "、".join(f"**{r['代號']} {STOCK_NAMES.get(r['代號'], '')}** (`NT${r['收盤價']:.2f}`, 評分 `{r['多空評分']:+d}`)" for _, r in top_bears.head(5).iterrows())
        if not top_bears.empty else "今日無明顯轉弱標的"
    )

    trigger_summary = (
        "、".join(f"**{a['sid']} {a['name']}**（{a['triggers']}）" for a in fresh_alerts[:6])
        if fresh_alerts else "今日無新交叉轉折訊號"
    )

    core_watch = scan_df_all[scan_df_all["代號"].isin(["2330", "0050", "00830", "00403A", "00981A", "00988A", "00991A"])]
    price_summary = "\n".join(
        f"• **{r['代號']} {STOCK_NAMES.get(r['代號'], '')}**：`NT${r['收盤價']:.2f}` ({r['單日漲跌%']:+.2f}%) ｜ {r['均線狀態']} ｜ RSI `{r['RSI(14)']:.1f}`"
        for _, r in core_watch.iterrows()
    )

    ai_summary = get_ai_forecast_summary(horizon=5, top_n=4)
    pf_summary = get_portfolio_alert_summary()

    sec1 = st.text_input("區塊 1 — 🔥 強勢多頭與買訊摘要", value=bull_summary)
    sec2 = st.text_input("區塊 2 — ⚡ 今日新觸發技術轉折", value=trigger_summary)
    sec3 = st.text_input("區塊 3 — ⚠️ 偏空與轉弱警示", value=bear_summary)
    sec_ai = st.text_area("區塊 4 — 🔮 AI 股價預測 Top 潛力與目標價 (T+5)", value=ai_summary, height=110)
    sec_pf = st.text_area("區塊 5 — 💼 模擬帳戶持倉損益與停損停利監控", value=pf_summary, height=90)
    sec4 = st.text_area("區塊 6 — 📌 核心關注標的收盤報價", value=price_summary, height=140)

    if st.button(":material/rocket_launch: 立即發送彩色訊號日報至 Discord", type="primary"):
        active_url = webhook_input.strip() or saved_webhook
        if active_url and active_url != saved_webhook:
            save_discord_webhook_url(active_url)
        with st.spinner("正在發送彩色卡片至 Discord Webhook…"):
            ok, msg = notify_discord(
                sections=[
                    ("🔥 強勢多頭與買訊標的", sec1),
                    ("⚡ 今日新觸發技術轉折", sec2),
                    ("⚠️ 偏空與轉弱警示", sec3),
                    ("🔮 AI 股價預測 Top 潛力與目標價 (T+5)", sec_ai),
                    ("💼 模擬帳戶持倉損益與停損停利監控", sec_pf),
                    ("📌 核心關注標的收盤報價", sec4),
                ],
                webhook_url=active_url,
                title=f"📊 台股與主動式 ETF 訊號雷達日報（資料日：{scan_df_all['最新日期'].max()}）",
            )
        if ok:
            st.success(msg, icon=":material/check_circle:")
        else:
            st.error(msg, icon=":material/error:")

