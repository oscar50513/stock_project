"""資料管理頁 — 查看資料狀況 + 一鍵更新"""

import os
import subprocess
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.indicators import DATA_DIR, STOCK_NAMES, get_stock_ids, load_stock

# ── 資料狀態總覽 ───────────────────────────────────────────────────────────────
st.subheader(":material/database: 資料狀態總覽", anchor=False)

stock_ids = get_stock_ids()
if not stock_ids:
    st.error("找不到任何股票 CSV 檔案（格式：[0-9]*.csv）")
    st.stop()

rows = []
for sid in stock_ids:
    path   = os.path.join(DATA_DIR, f"{sid}.csv")
    df     = load_stock(sid)
    size   = os.path.getsize(path) / 1024  # KB
    if df.empty:
        rows.append({
            "股票": f"{sid} {STOCK_NAMES.get(sid, '')}",
            "資料筆數": 0, "最早日期": "—", "最新日期": "—",
            "距今天數": "—", "資料大小": f"{size:.1f} KB", "狀態": "❌ 空檔案",
        })
        continue

    first_date  = df.index.min().date()
    last_date   = df.index.max().date()
    gap_days    = (date.today() - last_date).days
    # 扣掉週末（估算）
    approx_trading_gap = max(0, gap_days - gap_days // 7 * 2)

    if approx_trading_gap == 0:
        status = "✅ 最新"
    elif approx_trading_gap <= 3:
        status = "🟡 輕微落後"
    elif approx_trading_gap <= 30:
        status = f"🟠 落後約 {approx_trading_gap} 個交易日"
    else:
        status = f"🔴 落後約 {approx_trading_gap} 個交易日"

    rows.append({
        "股票":     f"{sid} {STOCK_NAMES.get(sid, '')}",
        "資料筆數": len(df),
        "最早日期": str(first_date),
        "最新日期": str(last_date),
        "距今天數": f"{gap_days} 天",
        "資料大小": f"{size:.1f} KB",
        "狀態":     status,
    })

status_df = pd.DataFrame(rows).set_index("股票")
st.dataframe(status_df, use_container_width=True)

# ── 一鍵更新 ──────────────────────────────────────────────────────────────────
st.subheader(":material/refresh: 更新資料", anchor=False)

col_l, col_r = st.columns([2, 1])
with col_l:
    st.caption(
        "使用 `fill_yfinance_gap.py` 自動從 yfinance 補充缺口資料。"
        "更新需要網路連線，時間視資料量而定（約 10–60 秒）。"
    )

with col_r:
    do_update = st.button(
        ":material/cloud_download: 立即更新所有股票",
        type="primary",
        use_container_width=True,
    )

if do_update:
    script_path = os.path.join(DATA_DIR, "fill_yfinance_gap.py")
    if not os.path.exists(script_path):
        st.error(f"找不到 {script_path}，請確認 fill_yfinance_gap.py 存在於專案根目錄。")
    else:
        with st.status("正在更新資料…", expanded=True) as status_box:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True, cwd=DATA_DIR,
                timeout=180,
            )

            if result.returncode == 0:
                st.write("**stdout：**")
                st.code(result.stdout or "（無輸出）", language="text")
                status_box.update(label="✅ 更新完成！", state="complete")
                st.success("資料已更新。請重新整理頁面以查看最新狀態。",
                           icon=":material/check_circle:")
                # 清除快取，讓資料頁面重新載入
                load_stock.clear()
            else:
                st.write("**stdout：**")
                st.code(result.stdout or "（無輸出）", language="text")
                st.write("**stderr：**")
                st.code(result.stderr or "（無輸出）", language="text")
                status_box.update(label="❌ 更新失敗", state="error")
                st.error(f"更新腳本回傳錯誤碼 {result.returncode}，請查看上方訊息。")

# ── 個股詳細資訊 ───────────────────────────────────────────────────────────────
st.subheader(":material/table_chart: 個股資料詳細查看", anchor=False)

inspect_sid = st.selectbox(
    "選擇股票查看原始資料",
    stock_ids,
    format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
    key="dm_inspect",
)

df_inspect = load_stock(inspect_sid)
if not df_inspect.empty:
    c1, c2 = st.columns(2)
    with c1:
        st.caption("最新 20 筆資料")
        disp = df_inspect.tail(20)[["Open", "High", "Low", "Close", "Volume"]].copy()
        disp.index = disp.index.strftime("%Y/%m/%d")
        st.dataframe(
            disp,
            column_config={
                "Open":   st.column_config.NumberColumn("開盤", format="%.2f"),
                "High":   st.column_config.NumberColumn("最高", format="%.2f"),
                "Low":    st.column_config.NumberColumn("最低", format="%.2f"),
                "Close":  st.column_config.NumberColumn("收盤", format="%.2f"),
                "Volume": st.column_config.NumberColumn("成交量(張)", format="%d"),
            },
        )
    with c2:
        st.caption("最舊 10 筆資料（驗證起始點）")
        disp_old = df_inspect.head(10)[["Open", "High", "Low", "Close", "Volume"]].copy()
        disp_old.index = disp_old.index.strftime("%Y/%m/%d")
        st.dataframe(
            disp_old,
            column_config={
                "Open":   st.column_config.NumberColumn("開盤", format="%.2f"),
                "High":   st.column_config.NumberColumn("最高", format="%.2f"),
                "Low":    st.column_config.NumberColumn("最低", format="%.2f"),
                "Close":  st.column_config.NumberColumn("收盤", format="%.2f"),
                "Volume": st.column_config.NumberColumn("成交量(張)", format="%d"),
            },
        )

    # 下載完整 CSV
    csv_data = df_inspect.reset_index().to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f":material/download: 下載 {inspect_sid}.csv",
        data=csv_data,
        file_name=f"{inspect_sid}.csv",
        mime="text/csv",
    )
