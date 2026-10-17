"""台灣股票分析 Dashboard — 主入口"""

import streamlit as st

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

pg.run()
