"""台灣股票分析 Dashboard — 主入口"""

import streamlit as st
from fill_yfinance_gap import update_all_csvs
from src.indicators import get_stock_ids, load_stock

st.set_page_config(
    page_title="台灣股票分析",
    page_icon=":material/candlestick_chart:",
    layout="wide",
)

# ── 多頁面導覽 ────────────────────────────────────────────────────────────────
pg = st.navigation(
    [
        st.Page("app_pages/overview.py",
                title="技術分析",
                icon=":material/candlestick_chart:",
                default=True),
        st.Page("app_pages/screener.py",
                title="訊號雷達",
                icon=":material/radar:"),
        st.Page("app_pages/active_etf.py",
                title="主動式ETF",
                icon=":material/workspace_premium:"),
        st.Page("app_pages/comparison.py",
                title="多股比較",
                icon=":material/compare_arrows:"),
        st.Page("app_pages/backtest.py",
                title="策略回測",
                icon=":material/query_stats:"),
        st.Page("app_pages/paper_trade.py",
                title="模擬交易",
                icon=":material/account_balance:"),
        st.Page("app_pages/data_mgmt.py",
                title="資料管理",
                icon=":material/database:"),
    ],
    position="top",
)

# ── 全局側邊欄底部：資料鮮度與一鍵同步最新收盤價 ──────────────────────────────
with st.sidebar:
    _sids = get_stock_ids()
    _ref_sid = "2330" if "2330" in _sids else (_sids[0] if _sids else None)
    _latest_date_str = "—"
    if _ref_sid:
        _ref_df = load_stock(_ref_sid)
        if not _ref_df.empty:
            _latest_date_str = _ref_df.index.max().strftime("%Y/%m/%d")

    st.caption(f"📅 最新收盤資料日：**{_latest_date_str}**（共 {len(_sids)} 檔標的）")
    if st.button(":material/sync: 同步最新收盤價", width="stretch", key="global_sync_btn"):
        with st.spinner("正在從 Yahoo Finance 同步全市場最新收盤價..."):
            cnt, new_dt = update_all_csvs()
            load_stock.clear()
        st.toast(f"已同步 {cnt} 檔標的（最新資料日：{new_dt}）", icon=":material/check_circle:")
        st.rerun()

pg.run()
