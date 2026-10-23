"""每日收盤自動更新股價 CSV 並發送 Discord 訊號雷達日報腳本

執行方式：
    .venv/bin/python daily_report.py
"""

import glob
import logging
import os
import warnings
import pandas as pd

# 抑制非 Streamlit Server 環境下的警告與提示
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)
logging.disable(logging.WARNING)

from fill_yfinance_gap import fill_gaps
from src.indicators import (
    ACTIVE_ETF_META,
    DATA_DIR,
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


def run_daily_pipeline() -> tuple[bool, str]:
    # 1. 更新所有 CSV 最新股價
    print("=== Step 1: 更新所有股票與 ETF 最新股價 (yfinance) ===")
    csvs = sorted(glob.glob(os.path.join(DATA_DIR, "[0-9]*.csv")))
    for csv_path in csvs:
        fill_gaps(csv_path)

    load_stock.clear()

    # 2. 掃描全市場技術訊號
    print("=== Step 2: 執行全市場多指標訊號掃描 ===")
    scan_rows = []
    fresh_alerts = []

    for sid in get_stock_ids():
        df = load_stock(sid)
        if len(df) < 25:
            continue

        close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2])
        chg_pct = (close / prev_close - 1.0) * 100.0

        df_ma = calc_ma(df, [5, 10, 20, 60])
        ma5 = float(df_ma["MA5"].iloc[-1])
        ma20 = float(df_ma["MA20"].iloc[-1])
        ma60 = float(df_ma["MA60"].iloc[-1]) if pd.notna(df_ma["MA60"].iloc[-1]) else ma20
        ma5_prev = float(df_ma["MA5"].iloc[-2])
        ma20_prev = float(df_ma["MA20"].iloc[-2])

        ma_cross_up = (ma5 > ma20) and (ma5_prev <= ma20_prev)
        ma_cross_dn = (ma5 < ma20) and (ma5_prev >= ma20_prev)

        df_bb = calc_bbands(df, 20, 2.0)
        b_up = float(df_bb["b_up"].iloc[-1])
        b_low = float(df_bb["b_low"].iloc[-1])
        bb_break_up = close > b_up and prev_close <= float(df_bb["b_up"].iloc[-2])
        bb_rebound_low = close < b_low

        rsi_s = calc_rsi(df, 14)
        rsi_val = float(rsi_s.iloc[-1]) if pd.notna(rsi_s.iloc[-1]) else 50.0
        rsi_prev = float(rsi_s.iloc[-2]) if pd.notna(rsi_s.iloc[-2]) else 50.0
        rsi_turn_up = (rsi_val > 30) and (rsi_prev <= 30)

        df_macd = calc_macd(df)
        hist_v = float(df_macd["Histogram"].iloc[-1])
        hist_prev = float(df_macd["Histogram"].iloc[-2])
        macd_cross_up = (hist_v > 0) and (hist_prev <= 0)
        macd_cross_dn = (hist_v < 0) and (hist_prev >= 0)

        df_kd = calc_kd(df, 9)
        k_val = float(df_kd["K"].iloc[-1])
        d_val = float(df_kd["D"].iloc[-1])
        k_prev = float(df_kd["K"].iloc[-2])
        d_prev = float(df_kd["D"].iloc[-2])
        kd_cross_up = (k_val > d_val) and (k_prev <= d_prev) and (k_val <= 45)
        kd_cross_dn = (k_val < d_val) and (k_prev >= d_prev) and (k_val >= 65)

        score = 0
        triggers = []

        score += 1 if close > ma20 else -1
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

        if macd_cross_up:
            score += 2
            triggers.append("MACD金叉")
        elif macd_cross_dn:
            score -= 2
            triggers.append("MACD死叉")
        elif hist_v > 0:
            score += 1
        else:
            score -= 1

        if kd_cross_up:
            score += 1
            triggers.append("KD低檔金叉")
        elif kd_cross_dn:
            score -= 1
            triggers.append("KD高檔死叉")
        elif k_val >= 80:
            score += 1

        if bb_break_up:
            score += 1
            triggers.append("突破布林上軌")
        elif bb_rebound_low:
            triggers.append("觸及布林下軌")
        if rsi_turn_up:
            score += 1
            triggers.append("RSI超賣反彈")

        score = max(-5, min(5, score))
        name = STOCK_NAMES.get(sid, ACTIVE_ETF_META.get(sid, {}).get("name", sid))

        if triggers:
            fresh_alerts.append({
                "sid": sid,
                "name": name,
                "triggers": "、".join(triggers),
            })

        scan_rows.append({
            "代號": sid,
            "收盤價": close,
            "單日漲跌%": chg_pct,
            "均線狀態": ma_status,
            "RSI(14)": rsi_val,
            "多空評分": score,
            "最新日期": df.index[-1].strftime("%Y/%m/%d"),
        })

    scan_df_all = pd.DataFrame(scan_rows)
    if scan_df_all.empty:
        return False, "無有效股票資料可供掃描"

    top_bulls = scan_df_all[scan_df_all["多空評分"] >= 2].sort_values("多空評分", ascending=False)
    bull_summary = (
        "、".join(
            f"**{r['代號']} {STOCK_NAMES.get(r['代號'], '')}** (`NT${r['收盤價']:.2f}`, 評分 `{r['多空評分']:+d}`)"
            for _, r in top_bulls.head(6).iterrows()
        )
        if not top_bulls.empty else "今日無強勢買訊標的"
    )

    top_bears = scan_df_all[scan_df_all["多空評分"] <= -2].sort_values("多空評分", ascending=True)
    bear_summary = (
        "、".join(
            f"**{r['代號']} {STOCK_NAMES.get(r['代號'], '')}** (`NT${r['收盤價']:.2f}`, 評分 `{r['多空評分']:+d}`)"
            for _, r in top_bears.head(5).iterrows()
        )
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

    # 3. 推播至 Discord
    print("=== Step 3: 發送訊號雷達日報至 Discord Webhook ===")
    ok, msg = notify_discord(
        sections=[
            ("🔥 強勢多頭與買訊標的", bull_summary),
            ("⚡ 今日新觸發技術轉折", trigger_summary),
            ("⚠️ 偏空與轉弱警示", bear_summary),
            ("📌 核心關注標的收盤報價", price_summary),
        ],
        title=f"📊 台股與主動式 ETF 訊號雷達日報（資料日：{scan_df_all['最新日期'].max()}）",
    )
    print(msg)
    return ok, msg


if __name__ == "__main__":
    run_daily_pipeline()
