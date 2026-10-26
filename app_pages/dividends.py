"""除權息日曆與 Google 日曆同步頁 — 勾選除權息、填息天數追蹤、預估股息試算與 Google Calendar 同步"""

import importlib
import json
import os
import subprocess
import urllib.parse
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import src.config as _cfg
import src.indicators as _ind
importlib.reload(_cfg)
importlib.reload(_ind)

from src.config import get_gcal_webhook_url, save_gcal_webhook_url
from src.indicators import ACTIVE_ETF_META, DATA_DIR, STOCK_NAMES, get_stock_ids, load_stock

DIVIDEND_FILE = os.path.join(DATA_DIR, "dividend_schedule.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "paper_portfolio.json")

# ── 預設台股與主動式 ETF 2026~2027 除權息排程資料庫 ──────────────────────────
DEFAULT_DIVIDENDS = [
    # 台積電 (2330) — 季配息
    {"sid": "2330", "ex_date": "2026-03-12", "pay_date": "2026-04-09", "cash_div": 4.50, "freq": "季配息", "period_label": "2025 Q3 配息"},
    {"sid": "2330", "ex_date": "2026-06-11", "pay_date": "2026-07-09", "cash_div": 4.50, "freq": "季配息", "period_label": "2025 Q4 配息"},
    {"sid": "2330", "ex_date": "2026-09-10", "pay_date": "2026-10-08", "cash_div": 5.00, "freq": "季配息", "period_label": "2026 Q1 配息"},
    {"sid": "2330", "ex_date": "2026-12-10", "pay_date": "2027-01-07", "cash_div": 5.00, "freq": "季配息", "period_label": "2026 Q2 配息"},
    # 元大台灣50 (0050) — 半年配 (1月、7月)
    {"sid": "0050", "ex_date": "2026-01-16", "pay_date": "2026-02-20", "cash_div": 3.20, "freq": "半年配", "period_label": "2025 下半年配息"},
    {"sid": "0050", "ex_date": "2026-07-16", "pay_date": "2026-08-15", "cash_div": 1.80, "freq": "半年配", "period_label": "2026 上半年配息"},
    {"sid": "0050", "ex_date": "2027-01-18", "pay_date": "2027-02-22", "cash_div": 3.50, "freq": "半年配", "period_label": "2026 下半年預估配息"},
    # 元大高股息 (0056) — 季配息 (1、4、7、10月)
    {"sid": "0056", "ex_date": "2026-04-17", "pay_date": "2026-05-15", "cash_div": 0.95, "freq": "季配息", "period_label": "2026 Q2 配息"},
    {"sid": "0056", "ex_date": "2026-07-17", "pay_date": "2026-08-14", "cash_div": 1.07, "freq": "季配息", "period_label": "2026 Q3 配息"},
    {"sid": "0056", "ex_date": "2026-10-19", "pay_date": "2026-11-14", "cash_div": 1.07, "freq": "季配息", "period_label": "2026 Q4 配息"},
    {"sid": "0056", "ex_date": "2027-01-18", "pay_date": "2027-02-18", "cash_div": 1.05, "freq": "季配息", "period_label": "2027 Q1 預估配息"},
    # 國泰費城半導體 (00830) — 年配息 (1月)
    {"sid": "00830", "ex_date": "2026-01-19", "pay_date": "2026-02-23", "cash_div": 2.10, "freq": "年配息", "period_label": "2025 年度配息"},
    {"sid": "00830", "ex_date": "2027-01-19", "pay_date": "2027-02-23", "cash_div": 2.80, "freq": "年配息", "period_label": "2026 年度預估配息"},
    # 鴻海 (2317) & 華航 (2610) — 年配息 (7月)
    {"sid": "2317", "ex_date": "2026-07-02", "pay_date": "2026-07-30", "cash_div": 5.80, "freq": "年配息", "period_label": "2025 年度股利"},
    {"sid": "2610", "ex_date": "2026-07-09", "pay_date": "2026-08-05", "cash_div": 1.15, "freq": "年配息", "period_label": "2025 年度股利"},
    # 主動式 ETF 季配息與年配息排程
    {"sid": "00980A", "ex_date": "2026-08-18", "pay_date": "2026-09-12", "cash_div": 0.22, "freq": "季配息", "period_label": "2026 Q3 配息"},
    {"sid": "00980A", "ex_date": "2026-11-17", "pay_date": "2026-12-11", "cash_div": 0.25, "freq": "季配息", "period_label": "2026 Q4 配息"},
    {"sid": "00982A", "ex_date": "2026-08-20", "pay_date": "2026-09-15", "cash_div": 0.24, "freq": "季配息", "period_label": "2026 Q3 配息"},
    {"sid": "00982A", "ex_date": "2026-11-19", "pay_date": "2026-12-15", "cash_div": 0.26, "freq": "季配息", "period_label": "2026 Q4 配息"},
    {"sid": "00984A", "ex_date": "2026-09-16", "pay_date": "2026-10-14", "cash_div": 0.28, "freq": "季配息", "period_label": "2026 Q3 配息"},
    {"sid": "00984A", "ex_date": "2026-12-16", "pay_date": "2027-01-13", "cash_div": 0.30, "freq": "季配息", "period_label": "2026 Q4 配息"},
    {"sid": "00403A", "ex_date": "2026-11-20", "pay_date": "2026-12-16", "cash_div": 0.22, "freq": "季配息", "period_label": "2026 Q4 首次配息"},
    {"sid": "00991A", "ex_date": "2026-11-24", "pay_date": "2026-12-18", "cash_div": 0.20, "freq": "季配息", "period_label": "2026 Q4 配息"},
    {"sid": "00981A", "ex_date": "2026-12-18", "pay_date": "2027-01-15", "cash_div": 0.65, "freq": "年配息", "period_label": "2026 年度配息"},
    {"sid": "00988A", "ex_date": "2026-12-22", "pay_date": "2027-01-19", "cash_div": 0.55, "freq": "年配息", "period_label": "2026 年度配息"},
]


def load_dividend_schedule() -> list[dict]:
    if os.path.exists(DIVIDEND_FILE):
        try:
            with open(DIVIDEND_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
        except Exception:
            pass
    save_dividend_schedule(DEFAULT_DIVIDENDS)
    return list(DEFAULT_DIVIDENDS)


def save_dividend_schedule(items: list[dict]) -> None:
    with open(DIVIDEND_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def load_user_holdings_shares() -> dict[str, int]:
    """讀取模擬交易持倉股數，自動帶入除權息試算表。"""
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                pf = json.load(f)
            return {sid: int(pos.get("shares", 1000)) for sid, pos in pf.get("holdings", {}).items()}
        except Exception:
            pass
    return {}


def calc_fill_days_status(sid: str, ex_date_str: str, cash_div: float) -> tuple[str, float]:
    """利用本機日 K 資料自動計算該次除息之填息狀態、填息天數與最新收盤價。"""
    df = load_stock(sid)
    if df.empty:
        return "—", 0.0

    latest_close = float(df["Close"].iloc[-1])
    ex_dt = pd.to_datetime(ex_date_str)
    today_dt = pd.to_datetime(datetime.now().strftime("%Y-%m-%d"))

    if ex_dt > df.index.max() and ex_dt >= today_dt:
        days_left = (ex_dt - today_dt).days
        return f"⏳ 即將除息 ({days_left}天後)", latest_close

    # 找除息前一日收盤價
    before_df = df[df.index < ex_dt]
    after_df = df[df.index >= ex_dt]
    if before_df.empty or after_df.empty:
        return "📅 已除息", latest_close

    pre_ex_close = float(before_df["Close"].iloc[-1])
    # 檢查除息日當天或之後最高價/收盤價何時回到 pre_ex_close
    filled_slice = after_df[after_df["High"] >= pre_ex_close]
    if not filled_slice.empty:
        fill_date = filled_slice.index[0]
        n_days = int((after_df.index <= fill_date).sum())
        return f"🔴 已填息 ({n_days}天完成)", latest_close
    else:
        elapsed = len(after_df)
        return f"🟢 貼息中 (已歷經{elapsed}交易日)", latest_close


def make_gcal_template_url(title: str, date_str: str, details: str) -> str:
    """產生免設定之 Google Calendar 網頁版單筆快速新增連結（全天行程）。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start_s = dt.strftime("%Y%m%d")
    end_s = (dt + timedelta(days=1)).strftime("%Y%m%d")
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_s}/{end_s}",
        "details": details,
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


def build_ics_content(events: list[dict]) -> str:
    """將勾選的除權息與發放日清單轉為標準 RFC 5545 iCalendar (.ics) 格式（含前一日 09:00 提醒）。"""
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//StockRadar//Taiwan Stock & Active ETF Dividend Calendar//ZH",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:StockRadar 台股配息日曆",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]
    for idx, ev in enumerate(events):
        dt = datetime.strptime(ev["date"], "%Y-%m-%d")
        dt_start = dt.strftime("%Y%m%d")
        dt_end = (dt + timedelta(days=1)).strftime("%Y%m%d")
        uid = f"stockradar-{ev['sid']}-{ev['type']}-{dt_start}-{idx}@stockradar.local"
        desc_escaped = ev["details"].replace("\n", "\\n")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_utc}",
            f"DTSTART;VALUE=DATE:{dt_start}",
            f"DTEND;VALUE=DATE:{dt_end}",
            f"SUMMARY:{ev['title']}",
            f"DESCRIPTION:{desc_escaped}",
            "BEGIN:VALARM",
            "TRIGGER:-PT15H",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{ev['title']}",
            "END:VALARM",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


st.subheader(":material/event_available: 除權息追蹤與 Google 日曆配息同步中心", anchor=False)
st.caption(
    "自由**勾選您關注的個股與主動式 ETF 除權息與股息發放日**，自動試算**預估入帳現金股利（NT$）**與**歷史填息天數**，"
    "並支援**一鍵同步更新至您的 Google 日曆（Google Calendar）**或 Mac 行事曆。"
)

# ── Sidebar：篩選、Yahoo Finance 同步與手動新增 ───────────────────────────────
with st.sidebar:
    st.header(":material/filter_alt: 除權息篩選與管理", divider=True)

    time_filter = st.pills(
        "時程篩選",
        ["全部時程", "即將除息／待發放 🔴", "歷史已除息紀錄"],
        default="全部時程",
    ) or "全部時程"

    cat_filter = st.pills(
        "標的篩選",
        ["全部標的", "主動與被動 ETF", "一般個股", "僅顯示模擬持倉標的"],
        default="全部標的",
    ) or "全部標的"

    default_shares_input = st.number_input(
        "未持倉標的預設試算股數（1張=1,000股）",
        min_value=1,
        max_value=1_000_000,
        value=1_000,
        step=1_000,
        help="若您在模擬交易中有持倉，系統會自動帶入您的實際持倉股數；未持倉標的則以此預設股數試算領息金額（亦可直接在表格內修改）。",
    )

    st.divider()
    st.subheader(":material/cloud_sync: 同步與新增配息公告", anchor=False)

    if st.button(":material/sync: 從 Yahoo Finance 同步歷史除息", width="stretch"):
        import yfinance as yf
        sched = load_dividend_schedule()
        existing_keys = {(x["sid"], x["ex_date"]) for x in sched}
        added_cnt = 0
        with st.spinner("正在從 Yahoo Finance 檢索各標的最新除權息紀錄..."):
            for sid in get_stock_ids():
                try:
                    tk = yf.Ticker(f"{sid}.TW")
                    divs = tk.dividends
                    if divs is not None and not divs.empty:
                        recent_divs = divs[divs.index >= "2025-06-01"]
                        for dt_idx, val in recent_divs.items():
                            ex_s = pd.to_datetime(dt_idx).strftime("%Y-%m-%d")
                            if (sid, ex_s) not in existing_keys and float(val) > 0:
                                pay_s = (pd.to_datetime(ex_s) + timedelta(days=28)).strftime("%Y-%m-%d")
                                sched.append({
                                    "sid": sid,
                                    "ex_date": ex_s,
                                    "pay_date": pay_s,
                                    "cash_div": round(float(val), 3),
                                    "freq": ACTIVE_ETF_META.get(sid, {}).get("dividend", "配息"),
                                    "period_label": f"{ex_s[:7]} 除息",
                                })
                                existing_keys.add((sid, ex_s))
                                added_cnt += 1
                except Exception:
                    continue
        if added_cnt > 0:
            sched.sort(key=lambda x: x["ex_date"], reverse=True)
            save_dividend_schedule(sched)
            st.toast(f"已從 Yahoo Finance 新增 {added_cnt} 筆除息紀錄！", icon=":material/check_circle:")
            st.rerun()
        else:
            st.toast("目前已包含所有最新公開除息紀錄！", icon=":material/info:")

    with st.expander(":material/add_circle: 手動新增／更新除權息公告", expanded=False):
        all_sids = get_stock_ids()
        new_sid = st.selectbox(
            "股票／ETF 代號",
            all_sids,
            format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
            key="div_add_sid",
        )
        new_ex = st.date_input("除息交易日", value=datetime.now().date() + timedelta(days=14))
        new_pay = st.date_input("股息發放日", value=datetime.now().date() + timedelta(days=42))
        new_amt = st.number_input("每股配息金額 (NTD)", min_value=0.01, max_value=500.0, value=1.0, step=0.05, format="%.2f")
        new_freq = st.selectbox("配息頻率", ["季配息", "半年配", "年配息", "月配息"])
        new_note = st.text_input("配息期別說明", value=f"{new_ex.strftime('%Y')} 配息")
        if st.button(":material/save: 新增至除權息日曆", width="stretch", type="primary"):
            sched = load_dividend_schedule()
            ex_str = new_ex.strftime("%Y-%m-%d")
            pay_str = new_pay.strftime("%Y-%m-%d")
            # 若同代號同除息日已存在則更新
            sched = [x for x in sched if not (x["sid"] == new_sid and x["ex_date"] == ex_str)]
            sched.append({
                "sid": new_sid,
                "ex_date": ex_str,
                "pay_date": pay_str,
                "cash_div": float(new_amt),
                "freq": new_freq,
                "period_label": new_note,
            })
            save_dividend_schedule(sched)
            st.toast(f"已新增 {new_sid} ({ex_str}) 除權息行程！", icon=":material/check_circle:")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 整理除權息資料表與可勾選 Data Editor
# ═══════════════════════════════════════════════════════════════════════════════

raw_schedule = load_dividend_schedule()
held_shares_map = load_user_holdings_shares()
today_str = datetime.now().strftime("%Y-%m-%d")

table_rows = []
for item in raw_schedule:
    sid = item["sid"]
    ex_date = item["ex_date"]
    pay_date = item["pay_date"]
    cash_div = float(item["cash_div"])

    # 篩選條件
    is_upcoming = (ex_date >= today_str) or (pay_date >= today_str)
    if time_filter == "即將除息／待發放 🔴" and not is_upcoming:
        continue
    if time_filter == "歷史已除息紀錄" and is_upcoming:
        continue

    is_etf = sid.startswith("00") or sid.endswith("A") or sid in ACTIVE_ETF_META
    if cat_filter == "主動與被動 ETF" and not is_etf:
        continue
    if cat_filter == "一般個股" and is_etf:
        continue
    if cat_filter == "僅顯示模擬持倉標的" and sid not in held_shares_map:
        continue

    fill_status, latest_close = calc_fill_days_status(sid, ex_date, cash_div)
    div_yield_pct = (cash_div / latest_close * 100.0) if latest_close > 0 else 0.0

    # 計算最後買進日（除息日前一工作日）
    ex_dt = pd.to_datetime(ex_date)
    last_buy_dt = pd.bdate_range(end=ex_dt - pd.Timedelta(days=1), periods=1)[0]
    last_buy_str = last_buy_dt.strftime("%Y-%m-%d")

    default_sh = held_shares_map.get(sid, int(default_shares_input))
    est_payout = int(round(default_sh * cash_div))

    table_rows.append({
        "勾選同步": is_upcoming,  # 預設自動勾選「即將除息或待發放」的項目
        "代號": sid,
        "名稱": f"{sid} {STOCK_NAMES.get(sid, ACTIVE_ETF_META.get(sid, {}).get('name', ''))}",
        "配息期別": item.get("period_label", "—"),
        "頻率": item.get("freq", "—"),
        "最後買進日": last_buy_str,
        "除息交易日": ex_date,
        "股息發放日": pay_date,
        "每股配息(元)": cash_div,
        "目前收盤價": round(latest_close, 2),
        "當期殖利率%": round(div_yield_pct, 2),
        "試算股數": default_sh,
        "預估領息(NT$)": est_payout,
        "填息與時程狀態": fill_status,
    })

if not table_rows:
    st.info("目前篩選條件下無對應的除權息紀錄，請調整左側篩選器或新增配息公告。")
    st.stop()

div_df = pd.DataFrame(table_rows).sort_values("除息交易日", ascending=False).reset_index(drop=True)

# ── 快速全選 / 僅選未來待發放 控制列 ──────────────────────────────────────────
with st.container(border=True):
    top_c1, top_c2, top_c3 = st.columns([3, 1, 1])
    with top_c1:
        st.subheader(":material/check_box: 第一步：勾選要同步至 Google 日曆的除權息項目", anchor=False)
        st.caption("可直接點擊表格第一欄 **「勾選同步」** 核取方塊，並可直接在表格內修改 **「試算股數」**，系統會即時重算預估入帳股息金額。")
    with top_c2:
        if st.button(":material/select_all: 全部勾選", width="stretch"):
            div_df["勾選同步"] = True
            st.session_state["div_editor_override"] = True
    with top_c3:
        if st.button(":material/deselect: 僅勾選未來行程", width="stretch"):
            div_df["勾選同步"] = [
                (r["除息交易日"] >= today_str or r["股息發放日"] >= today_str) for _, r in div_df.iterrows()
            ]
            st.session_state["div_editor_override"] = False

    if st.session_state.get("div_editor_override") is True:
        div_df["勾選同步"] = True

    edited_df = st.data_editor(
        div_df,
        hide_index=True,
        width="stretch",
        disabled=[
            "代號", "名稱", "配息期別", "頻率", "最後買進日",
            "除息交易日", "股息發放日", "每股配息(元)", "目前收盤價",
            "當期殖利率%", "預估領息(NT$)", "填息與時程狀態",
        ],
        column_config={
            "勾選同步": st.column_config.CheckboxColumn("☑️ 勾選同步", default=True),
            "每股配息(元)": st.column_config.NumberColumn("每股配息(元)", format="NT$%.2f"),
            "目前收盤價": st.column_config.NumberColumn("目前收盤價", format="NT$%.2f"),
            "當期殖利率%": st.column_config.NumberColumn("當期殖利率%", format="%.2f%%"),
            "試算股數": st.column_config.NumberColumn("✏️ 試算股數 (可編輯)", min_value=1, max_value=10_000_000, step=100, format="%d 股"),
            "預估領息(NT$)": st.column_config.NumberColumn("預估領息(NT$)", format="NT$%d"),
        },
        key="dividend_table_editor",
    )

# 即時根據使用者修改後的「試算股數」重算預估領息
edited_df["預估領息(NT$)"] = (edited_df["試算股數"] * edited_df["每股配息(元)"]).round(0).astype(int)
selected_rows_df = edited_df[edited_df["勾選同步"] == True].copy()

# ── 頂部勾選摘要 KPI 卡片（遵循台股紅漲綠跌配色）─────────────────────────────
total_checked = len(selected_rows_df)
total_est_div = int(selected_rows_df["預估領息(NT$)"].sum()) if total_checked > 0 else 0
avg_yield = float(selected_rows_df["當期殖利率%"].mean()) if total_checked > 0 else 0.0
upcoming_cnt = int(
    ((selected_rows_df["除息交易日"] >= today_str) | (selected_rows_df["股息發放日"] >= today_str)).sum()
) if total_checked > 0 else 0

with st.container(horizontal=True):
    st.metric(
        "目前已勾選配息筆數",
        f"{total_checked} 筆",
        delta=f"含未來待除息/待領息 {upcoming_cnt} 筆",
        delta_color="red" if total_checked > 0 else "gray",
        delta_arrow="up" if total_checked > 0 else "off",
        border=True,
    )
    st.metric(
        "勾選項目預估總領息金額",
        f"NT${total_est_div:,}",
        delta="將自動寫入 Google 日曆行程備註",
        delta_color="red" if total_est_div > 0 else "gray",
        delta_arrow="up" if total_est_div > 0 else "off",
        border=True,
    )
    st.metric(
        "勾選項目平均單次殖利率",
        f"{avg_yield:.2f}%",
        delta="依最新收盤價計算",
        delta_color="off",
        delta_arrow="off",
        border=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 產生準備同步至 Google 日曆之行程清單 (Events Builder)
# ═══════════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.subheader(":material/calendar_month: 第二步：更新至您的 Google 日曆 (Google Calendar)", anchor=False)

    ev_col1, ev_col2 = st.columns([2, 2])
    with ev_col1:
        sync_event_types = st.multiselect(
            "選擇要同步寫入日曆的事件類型",
            ["📌 除息交易日（內含最後買進日提醒）", "💰 股息發放日（內含預估入帳金額 NT$）"],
            default=["📌 除息交易日（內含最後買進日提醒）", "💰 股息發放日（內含預估入帳金額 NT$）"],
        )
    with ev_col2:
        cal_prefix = st.text_input("日曆行程標題前綴", value="[台股配息]")

    calendar_events = []
    for _, r in selected_rows_df.iterrows():
        sid = r["代號"]
        name = r["名稱"]
        div_v = r["每股配息(元)"]
        sh_v = int(r["試算股數"])
        payout_v = int(r["預估領息(NT$)"])
        yld_v = r["當期殖利率%"]
        last_buy = r["最後買進日"]
        ex_d = r["除息交易日"]
        pay_d = r["股息發放日"]
        p_label = r["配息期別"]

        if "📌 除息交易日（內含最後買進日提醒）" in sync_event_types:
            title_ex = f"{cal_prefix} 📌 {name} 除息日 (每股配 {div_v:.2f}元)"
            details_ex = (
                f"【StockRadar 台股除權息提醒】\n"
                f"• 標的：{name} ({p_label})\n"
                f"• 除息交易日：{ex_d}（最後買進日：{last_buy}）\n"
                f"• 每股現金股利：NT${div_v:.2f}（當期殖利率約 {yld_v:.2f}%）\n"
                f"• 試算持有股數：{sh_v:,} 股\n"
                f"• 預估領息總額：NT${payout_v:,}\n"
                f"• 預計股息發放日：{pay_d}"
            )
            calendar_events.append({
                "sid": sid,
                "name": name,
                "type": "ex_date",
                "type_label": "📌 除息交易日",
                "date": ex_d,
                "title": title_ex,
                "details": details_ex,
                "payout": payout_v,
                "gcal_url": make_gcal_template_url(title_ex, ex_d, details_ex),
            })

        if "💰 股息發放日（內含預估入帳金額 NT$）" in sync_event_types:
            title_pay = f"{cal_prefix} 💰 {name} 股息發放日 (預估入帳 NT${payout_v:,})"
            details_pay = (
                f"【StockRadar 台股股息入帳提醒】\n"
                f"• 標的：{name} ({p_label})\n"
                f"• 股息發放日：{pay_d}（對應除息日：{ex_d}）\n"
                f"• 每股現金股利：NT${div_v:.2f}\n"
                f"• 試算持有股數：{sh_v:,} 股\n"
                f"• 預估入帳金額：NT${payout_v:,}"
            )
            calendar_events.append({
                "sid": sid,
                "name": name,
                "type": "pay_date",
                "type_label": "💰 股息發放日",
                "date": pay_d,
                "title": title_pay,
                "details": details_pay,
                "payout": payout_v,
                "gcal_url": make_gcal_template_url(title_pay, pay_d, details_pay),
            })

    if not calendar_events:
        st.warning("請先在上方表格至少勾選一筆除權息項目，並選擇至少一種日曆事件類型。")
    else:
        tab_auto, tab_links, tab_ics = st.tabs([
            ":material/bolt: 方式一：一鍵自動寫入 Google 日曆 (Webhook)",
            ":material/open_in_new: 方式二：點擊直接打開 Google 日曆新增 (免設定)",
            ":material/download: 方式三：批次匯出 .ics 檔／同步至 Mac 行事曆",
        ])

        # ── 方式一：透過 Google Apps Script Webhook 全自動批次寫入 Google 日曆 ──
        with tab_auto:
            st.caption(
                "只需在您自己的 Google 帳號貼上 20 行 Google Apps Script 並部署為網址（跟設定 Discord Webhook 一樣簡單，30 秒完成、永久免費），"
                "之後按下按鈕就能**直接把所有勾選的除權息行程自動寫進您的 Google 日曆**，且重複點擊會自動更新不重複建立！"
            )
            with st.expander(":material/help_outline: 30 秒設定 Google 日曆自動同步網址教學（附完整程式碼，只需設定一次）", expanded=False):
                st.markdown("""
1. 打開瀏覽器前往 **[Google Apps Script (script.google.com)](https://script.google.com/)**，點擊左上角 **「新專案 (New project)」**。
2. 將編輯器內原本的程式碼清空，**複製並貼上以下 22 行程式碼**：
```javascript
function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var cal = CalendarApp.getDefaultCalendar();
  var count = 0;
  data.events.forEach(function(item) {
    var parts = item.date.split("-");
    var dt = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    var existing = cal.getEventsForDay(dt, {search: item.title});
    for (var i = 0; i < existing.length; i++) {
      existing[i].deleteEvent();
    }
    cal.createAllDayEvent(item.title, dt, {description: item.details});
    count++;
  });
  return ContentService.createTextOutput(JSON.stringify({ok: true, synced: count}))
    .setMimeType(ContentService.MimeType.JSON);
}
```
3. 點擊右上角藍色按鈕 **「部署 (Deploy)」 → 「新增部署作業 (New deployment)」**。
4. 左側齒輪選取類型 **「網頁應用程式 (Web app)」**：
   - **執行身分 (Execute as)**：選 **「我 (Me)」**
   - **誰可以存取 (Who has access)**：選 **「所有人 (Anyone)」**
5. 點擊 **「部署」** 並授權您的 Google 日曆權限，複製產生的 **「網頁應用程式網址 (`https://script.google.com/macros/s/.../exec`)」** 貼到下方即可！
                """)

            saved_gcal_url = get_gcal_webhook_url()
            gc1, gc2 = st.columns([4, 1])
            with gc1:
                gcal_url_input = st.text_input(
                    "Google 日曆 Apps Script Webhook 網址（自動加密保存於本機 .env）",
                    value=saved_gcal_url,
                    type="password",
                    placeholder="https://script.google.com/macros/s/.../exec",
                )
            with gc2:
                st.space("small")
                if st.button(":material/save: 儲存網址", width="stretch", key="save_gcal_btn"):
                    if gcal_url_input.strip():
                        save_gcal_webhook_url(gcal_url_input.strip())
                        st.toast("已儲存 Google 日曆 Webhook 網址至 .env！", icon=":material/check_circle:")
                    else:
                        st.warning("請先輸入有效的網址")

            if st.button(
                f":material/cloud_upload: 立即將勾選的 {len(calendar_events)} 筆配息行程自動寫入 Google 日曆",
                type="primary",
                width="stretch",
            ):
                active_gcal_url = gcal_url_input.strip() or saved_gcal_url
                if not active_gcal_url:
                    st.error("請先在上方欄位貼上您的 Google Apps Script Webhook 網址（或切換至旁側分頁使用「免設定點擊新增」與「.ics 批次匯入」）。")
                else:
                    if active_gcal_url != saved_gcal_url:
                        save_gcal_webhook_url(active_gcal_url)
                    with st.spinner(f"正在將 {len(calendar_events)} 筆除權息與發放日行程同步至您的 Google 日曆..."):
                        try:
                            resp = requests.post(
                                active_gcal_url,
                                json={"events": calendar_events},
                                timeout=20,
                            )
                            if resp.status_code == 200:
                                st.success(
                                    f"✅ 成功將 {len(calendar_events)} 筆除權息／股息發放日行程寫入您的 Google 日曆！現在打開手機或電腦的 Google Calendar 即可看到。",
                                    icon=":material/check_circle:",
                                )
                            else:
                                st.error(f"同步失敗（HTTP {resp.status_code}）：{resp.text[:200]}")
                        except Exception as exc:
                            st.error(f"連線至 Google 日曆 Webhook 時發生錯誤：{exc}")

        # ── 方式二：免任何設定！單筆一鍵開啟 Google Calendar 網頁新增連結 ──────
        with tab_links:
            st.caption("完全不需設定 API！點擊下方任一顆按鈕，就會直接打開您的 **Google 日曆新增頁面**，標題、日期、每股配息與預估領息金額皆已自動填好，按「儲存」即完成。")
            for ev in calendar_events:
                with st.container(horizontal=True):
                    st.markdown(f"**{ev['date']}** ｜ {ev['title']}")
                    st.link_button(
                        f":material/calendar_add_on: 加入 Google 日曆 ({ev['type_label']})",
                        url=ev["gcal_url"],
                    )

        # ── 方式三：批次匯出 .ics 行事曆檔 / 一鍵匯入 Mac 行事曆 ──────────────
        with tab_ics:
            st.caption(
                "將目前勾選的 **所有除息日與股息發放日** 打包成標準 `.ics` 行事曆檔（內建前一日早上 09:00 自動提醒）。"
                "您可以下載後至 **Google 日曆網頁版（右上角齒輪「設定」→「匯入與匯出」）一次匯入全部行程**，或直接點右側按鈕匯入 Mac 行事曆！"
            )
            ics_str = build_ics_content(calendar_events)
            ic1, ic2 = st.columns(2)
            with ic1:
                st.download_button(
                    label=f":material/download: 下載勾選的 {len(calendar_events)} 筆配息行程 (.ics 檔，可批次匯入 Google 日曆)",
                    data=ics_str.encode("utf-8"),
                    file_name="stockradar_dividends.ics",
                    mime="text/calendar",
                    type="primary",
                    width="stretch",
                )
            with ic2:
                if st.button(
                    f":material/apple: 直接在 Mac 行事曆開啟並加入這 {len(calendar_events)} 筆行程",
                    width="stretch",
                ):
                    ics_path = os.path.join(DATA_DIR, "stockradar_dividends.ics")
                    with open(ics_path, "w", encoding="utf-8") as f:
                        f.write(ics_str)
                    subprocess.Popen(["open", ics_path])
                    st.toast("已為您打開 Mac 行事曆匯入視窗！若 Mac 行事曆有綁定 Google 帳號會自動同步。", icon=":material/check_circle:")
