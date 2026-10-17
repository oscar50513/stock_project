"""策略回測頁 — 六大策略、停損停利風控、水下回撤與月度熱圖、多策略同台PK、參數最佳化 Grid Search"""

import importlib
import io
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import src.indicators as _ind
importlib.reload(_ind)

from src.indicators import (
    STOCK_NAMES,
    calc_bbands,
    calc_kd,
    calc_ma,
    calc_macd,
    calc_rsi,
    get_horizon_slice,
    get_stock_ids,
    load_stock,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 常數與費率設定
# ═══════════════════════════════════════════════════════════════════════════════

BUY_FEE  = 0.001425   # 買進手續費 0.1425%
SELL_FEE = 0.004425   # 賣出手續費 0.1425% + 證交稅 0.3%
LOT_SIZE = 1_000      # 台股 1 張 = 1,000 股

STRATEGY_LIST = [
    "MA 黃金/死亡交叉",
    "布林通道逆勢策略",
    "雙布林通道順勢突破",
    "RSI 超買超賣反轉",
    "MACD 黃金/死亡交叉",
    "KD 低檔黃金交叉",
]

STRAT_COLORS = {
    "MA 黃金/死亡交叉": "#f59e0b",
    "布林通道逆勢策略": "#3b82f6",
    "雙布林通道順勢突破": "#a855f7",
    "RSI 超買超賣反轉": "#10b981",
    "MACD 黃金/死亡交叉": "#ec4899",
    "KD 低檔黃金交叉": "#06b6d4",
    "Buy & Hold": "#94a3b8",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 訊號產生函數（皆在完整 df_full 上計算後再切片，避免前段暖機期 NaN）
# ═══════════════════════════════════════════════════════════════════════════════

def gen_ma_signals(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    fma = df["Close"].rolling(int(fast)).mean()
    sma = df["Close"].rolling(int(slow)).mean()
    sig = pd.Series(0, index=df.index)
    sig[(fma > sma) & (fma.shift(1) <= sma.shift(1))] = 1
    sig[(fma < sma) & (fma.shift(1) >= sma.shift(1))] = -1
    return sig


def gen_bb_signals(df: pd.DataFrame, period: int = 20, std_num: float = 2.0) -> pd.Series:
    mid = df["Close"].rolling(int(period)).mean()
    std = df["Close"].rolling(int(period)).std(ddof=0)
    b_up = mid + std * float(std_num)
    b_low = mid - std * float(std_num)
    sig = pd.Series(0, index=df.index)
    sig[(df["Close"] < b_low) & (df["Close"].shift(1) >= b_low.shift(1))] = 1
    sig[(df["Close"] > b_up) & (df["Close"].shift(1) <= b_up.shift(1))] = -1
    return sig


def gen_double_bb_signals(df: pd.DataFrame, period: int = 20, entry_std: float = 2.0, exit_std: float = 3.0) -> pd.Series:
    """雙布林順勢突破策略：收盤站上 +entry_std 軌道順勢做多；跌破中軌或觸及 +exit_std 軌道獲利了結。"""
    mid = df["Close"].rolling(int(period)).mean()
    std = df["Close"].rolling(int(period)).std(ddof=0)
    up_entry = mid + std * float(entry_std)
    up_exit = mid + std * float(exit_std)
    close = df["Close"]
    sig = pd.Series(0, index=df.index)
    buy_cond = (close > up_entry) & (close.shift(1) <= up_entry.shift(1))
    sell_cond = ((close < mid) & (close.shift(1) >= mid.shift(1))) | (
        (close >= up_exit) & (close.shift(1) < up_exit.shift(1))
    )
    sig[buy_cond] = 1
    sig[sell_cond] = -1
    return sig


def gen_rsi_signals(df: pd.DataFrame, period: int = 14, oversold: int = 30, overbought: int = 70) -> pd.Series:
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(int(period)).mean()
    loss = (-delta.clip(upper=0)).rolling(int(period)).mean()
    rsi = 100 - 100 / (1 + gain / (loss + 1e-9))
    sig = pd.Series(0, index=df.index)
    # 由超賣區向上突破買入；由超買區向下跌破或觸及超買賣出
    sig[(rsi > oversold) & (rsi.shift(1) <= oversold)] = 1
    sig[(rsi > overbought) & (rsi.shift(1) <= overbought)] = -1
    return sig


def gen_macd_signals(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal_p: int = 9) -> pd.Series:
    exp_f = df["Close"].ewm(span=int(fast), adjust=False).mean()
    exp_s = df["Close"].ewm(span=int(slow), adjust=False).mean()
    macd = exp_f - exp_s
    signal = macd.ewm(span=int(signal_p), adjust=False).mean()
    sig = pd.Series(0, index=df.index)
    sig[(macd > signal) & (macd.shift(1) <= signal.shift(1))] = 1
    sig[(macd < signal) & (macd.shift(1) >= signal.shift(1))] = -1
    return sig


def gen_kd_signals(df: pd.DataFrame, period: int = 9, low_thresh: int = 30, high_thresh: int = 75) -> pd.Series:
    kd = calc_kd(df, int(period))
    k, d = kd["K"], kd["D"]
    sig = pd.Series(0, index=df.index)
    sig[(k > d) & (k.shift(1) <= d.shift(1)) & (k <= low_thresh + 10)] = 1
    sig[(k < d) & (k.shift(1) >= d.shift(1)) & (k >= high_thresh - 10)] = -1
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# 強化版回測引擎（支援零股/整張、停損/停利/移動停損、波段成對統計）
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    initial_capital: float = 100_000.0,
    lot_mode: str = "odd_lot",          # "odd_lot" (1股) or "board_lot" (1000股)
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    trailing_stop_pct: float | None = None,
) -> dict:
    capital = float(initial_capital)
    shares = 0
    entry_price = 0.0
    entry_cost_total = 0.0
    entry_fee = 0.0
    entry_date = None
    highest_close = 0.0
    total_fees_paid = 0.0

    unit_step = 1 if lot_mode == "odd_lot" else LOT_SIZE

    orders = []
    round_trips = []
    equity_rows = []
    days_in_market = 0

    for date, row in df.iterrows():
        close = float(row["Close"])
        sig = int(signals.get(date, 0))

        if shares > 0:
            days_in_market += 1
            highest_close = max(highest_close, close)

            # 檢查出場條件（優先順序：停損 -> 移動停損 -> 停利 -> 策略訊號賣出）
            price_ret_pct = (close / entry_price - 1.0) * 100.0
            dd_from_peak_pct = (close / highest_close - 1.0) * 100.0

            exit_reason = None
            if stop_loss_pct is not None and stop_loss_pct > 0 and price_ret_pct <= -stop_loss_pct:
                exit_reason = f"停損出場 (-{stop_loss_pct:.1f}%)"
            elif trailing_stop_pct is not None and trailing_stop_pct > 0 and dd_from_peak_pct <= -trailing_stop_pct:
                exit_reason = f"移動停損 (-{trailing_stop_pct:.1f}%)"
            elif take_profit_pct is not None and take_profit_pct > 0 and price_ret_pct >= take_profit_pct:
                exit_reason = f"停利出場 (+{take_profit_pct:.1f}%)"
            elif sig == -1:
                exit_reason = "訊號賣出 🟢"

            if exit_reason is not None:
                gross_proceeds = shares * close
                sell_fee = gross_proceeds * SELL_FEE
                net_proceeds = gross_proceeds - sell_fee
                total_fees_paid += sell_fee

                net_pnl = net_proceeds - entry_cost_total
                ret_pct = (net_proceeds / entry_cost_total - 1.0) * 100.0
                hold_days = max(1, (date - entry_date).days)

                capital += net_proceeds

                orders.append({
                    "日期": date.strftime("%Y/%m/%d"),
                    "操作": exit_reason,
                    "成交價": round(close, 2),
                    "股數": shares,
                    "交易金額": round(net_proceeds, 0),
                    "手續費與稅": round(sell_fee, 0),
                    "剩餘資金": round(capital, 0),
                    "單筆損益": round(net_pnl, 0),
                    "報酬率%": round(ret_pct, 2),
                })

                round_trips.append({
                    "買入日期": entry_date.strftime("%Y/%m/%d"),
                    "賣出日期": date.strftime("%Y/%m/%d"),
                    "出場原因": exit_reason,
                    "買入價": round(entry_price, 2),
                    "賣出價": round(close, 2),
                    "股數": shares,
                    "持倉天數": hold_days,
                    "總手續費與稅": round(entry_fee + sell_fee, 0),
                    "淨損益": round(net_pnl, 0),
                    "報酬率%": round(ret_pct, 2),
                })

                shares = 0
                entry_price = 0.0
                entry_cost_total = 0.0
                entry_fee = 0.0
                entry_date = None
                highest_close = 0.0

        elif sig == 1 and shares == 0:
            unit_cost_with_fee = close * (1.0 + BUY_FEE)
            max_units = int(capital // (unit_cost_with_fee * unit_step))
            if max_units > 0:
                shares = max_units * unit_step
                gross_spent = shares * close
                buy_fee = gross_spent * BUY_FEE
                total_spent = gross_spent + buy_fee
                total_fees_paid += buy_fee
                capital -= total_spent

                entry_price = close
                entry_cost_total = total_spent
                entry_fee = buy_fee
                entry_date = date
                highest_close = close

                orders.append({
                    "日期": date.strftime("%Y/%m/%d"),
                    "操作": "訊號買入 🔴",
                    "成交價": round(close, 2),
                    "股數": shares,
                    "交易金額": round(total_spent, 0),
                    "手續費與稅": round(buy_fee, 0),
                    "剩餘資金": round(capital, 0),
                    "單筆損益": np.nan,
                    "報酬率%": np.nan,
                })

        # 每日權益計算
        mkt_val = shares * close * (1.0 - SELL_FEE) if shares > 0 else 0.0
        equity_rows.append({
            "Date": date,
            "Strategy": capital + mkt_val,
            "InPosition": 1 if shares > 0 else 0,
        })

    equity_df = pd.DataFrame(equity_rows).set_index("Date")
    final_equity = float(equity_df["Strategy"].iloc[-1])

    # Buy & Hold 基準（採用相同部位單位模式，確保公平比較）
    first_close = float(df["Close"].iloc[0])
    bh_units = int(initial_capital // (first_close * (1.0 + BUY_FEE) * unit_step))
    bh_shares = bh_units * unit_step
    if bh_shares > 0:
        bh_spent = bh_shares * first_close * (1.0 + BUY_FEE)
        bh_cash = initial_capital - bh_spent
        equity_df["BH"] = bh_cash + bh_shares * df["Close"] * (1.0 - SELL_FEE)
    else:
        # 若整張買不起，以理論比例計算 B&H 供參考
        equity_df["BH"] = initial_capital * (df["Close"] / first_close)

    # 水下回撤序列 (Underwater Drawdown %)
    strat_peak = equity_df["Strategy"].cummax()
    equity_df["Strategy_DD"] = (equity_df["Strategy"] / strat_peak - 1.0) * 100.0
    bh_peak = equity_df["BH"].cummax()
    equity_df["BH_DD"] = (equity_df["BH"] / bh_peak - 1.0) * 100.0

    # 最長回撤持續天數（水下天數）
    is_underwater = equity_df["Strategy"] < strat_peak
    max_dd_days = 0
    cur_dd_days = 0
    for uw in is_underwater:
        if uw:
            cur_dd_days += 1
            max_dd_days = max(max_dd_days, cur_dd_days)
        else:
            cur_dd_days = 0

    # ── 進階績效統計 ──────────────────────────────────────────────────────────
    years = max(len(df) / 252.0, 0.05)
    strat_ret = (final_equity / initial_capital - 1.0) * 100.0
    bh_ret = (float(equity_df["BH"].iloc[-1]) / initial_capital - 1.0) * 100.0
    excess_ret = strat_ret - bh_ret
    cagr = ((max(final_equity, 1.0) / initial_capital) ** (1.0 / years) - 1.0) * 100.0
    bh_cagr = ((max(float(equity_df["BH"].iloc[-1]), 1.0) / initial_capital) ** (1.0 / years) - 1.0) * 100.0

    mdd = float(equity_df["Strategy_DD"].min())
    bh_mdd = float(equity_df["BH_DD"].min())

    daily_rets = equity_df["Strategy"].pct_change().dropna()
    vol_ann = float(daily_rets.std()) * math.sqrt(252) * 100.0 if len(daily_rets) > 1 else 0.0
    rf_daily = 0.015 / 252.0
    ex_daily = daily_rets - rf_daily
    sharpe = (float(ex_daily.mean()) / float(ex_daily.std())) * math.sqrt(252) if float(ex_daily.std()) > 1e-12 else 0.0
    downside = daily_rets[daily_rets < rf_daily]
    down_std = float(downside.std()) if len(downside) > 1 else 0.0
    sortino = (float(ex_daily.mean()) / down_std) * math.sqrt(252) if down_std > 1e-12 else 0.0
    calmar = cagr / abs(mdd) if abs(mdd) > 1e-6 else 0.0

    # 波段統計
    n_trades = len(round_trips)
    wins = [t for t in round_trips if t["淨損益"] > 0]
    losses = [t for t in round_trips if t["淨損益"] <= 0]
    win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0

    gross_profit = sum(t["淨損益"] for t in wins)
    gross_loss = abs(sum(t["淨損益"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.9 if gross_profit > 0 else 0.0)

    avg_win_pct = float(np.mean([t["報酬率%"] for t in wins])) if wins else 0.0
    avg_loss_pct = abs(float(np.mean([t["報酬率%"] for t in losses]))) if losses else 0.0
    payoff_ratio = (avg_win_pct / avg_loss_pct) if avg_loss_pct > 0 else (99.9 if avg_win_pct > 0 else 0.0)

    expectancy_pct = float(np.mean([t["報酬率%"] for t in round_trips])) if round_trips else 0.0
    expectancy_ntd = float(np.mean([t["淨損益"] for t in round_trips])) if round_trips else 0.0
    best_trade_pct = max((t["報酬率%"] for t in round_trips), default=0.0)
    worst_trade_pct = min((t["報酬率%"] for t in round_trips), default=0.0)
    avg_hold_days = float(np.mean([t["持倉天數"] for t in round_trips])) if round_trips else 0.0

    # 最大連勝 / 連敗
    max_win_streak, max_loss_streak = 0, 0
    cur_w, cur_l = 0, 0
    for t in round_trips:
        if t["淨損益"] > 0:
            cur_w += 1
            cur_l = 0
            max_win_streak = max(max_win_streak, cur_w)
        else:
            cur_l += 1
            cur_w = 0
            max_loss_streak = max(max_loss_streak, cur_l)

    exposure_pct = (days_in_market / max(len(df), 1)) * 100.0

    metrics = {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_pnl": final_equity - initial_capital,
        "strat_return": strat_ret,
        "bh_return": bh_ret,
        "excess_return": excess_ret,
        "cagr": cagr,
        "bh_cagr": bh_cagr,
        "mdd": mdd,
        "bh_mdd": bh_mdd,
        "max_dd_days": max_dd_days,
        "vol_ann": vol_ann,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "expectancy_pct": expectancy_pct,
        "expectancy_ntd": expectancy_ntd,
        "best_trade_pct": best_trade_pct,
        "worst_trade_pct": worst_trade_pct,
        "avg_hold_days": avg_hold_days,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "exposure_pct": exposure_pct,
        "total_fees": total_fees_paid,
        "still_holding": shares > 0,
        "open_shares": shares,
    }

    return {
        "orders_df": pd.DataFrame(orders) if orders else pd.DataFrame(),
        "round_trips_df": pd.DataFrame(round_trips) if round_trips else pd.DataFrame(),
        "equity_df": equity_df,
        "metrics": metrics,
    }


def compute_signals_for_strategy(df_full: pd.DataFrame, strategy_name: str, params: dict) -> pd.Series:
    if strategy_name == "MA 黃金/死亡交叉":
        return gen_ma_signals(df_full, params.get("ma_fast", 5), params.get("ma_slow", 20))
    if strategy_name == "布林通道逆勢策略":
        return gen_bb_signals(df_full, params.get("bb_period", 20), params.get("bb_std", 2.0))
    if strategy_name == "雙布林通道順勢突破":
        return gen_double_bb_signals(
            df_full,
            params.get("dbb_period", 20),
            params.get("dbb_entry_std", 2.0),
            params.get("dbb_exit_std", 3.0),
        )
    if strategy_name == "RSI 超買超賣反轉":
        return gen_rsi_signals(
            df_full,
            params.get("rsi_period", 14),
            params.get("rsi_oversold", 30),
            params.get("rsi_overbought", 70),
        )
    if strategy_name == "MACD 黃金/死亡交叉":
        return gen_macd_signals(
            df_full,
            params.get("macd_fast", 12),
            params.get("macd_slow", 26),
            params.get("macd_sig", 9),
        )
    if strategy_name == "KD 低檔黃金交叉":
        return gen_kd_signals(
            df_full,
            params.get("kd_period", 9),
            params.get("kd_low", 30),
            params.get("kd_high", 75),
        )
    return pd.Series(0, index=df_full.index)


# ═══════════════════════════════════════════════════════════════════════════════
# Sidebar 控制面板
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.header(":material/tune: 回測設定", divider=True)

    stock_ids = get_stock_ids()
    default_idx = stock_ids.index("2330") if "2330" in stock_ids else 0
    selected = st.selectbox(
        "選擇股票或主動式 ETF",
        stock_ids,
        index=default_idx,
        format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
        key="bt_stock",
    )

    horizon = st.pills(
        "回測區間",
        ["3個月", "6個月", "1年", "3年", "全部"],
        default="3年",
        key="bt_horizon",
    ) or "3年"

    initial_cap = st.number_input(
        "初始資金 (NTD)",
        min_value=10_000, max_value=50_000_000,
        value=1_000_000, step=100_000, format="%d",
    )

    lot_label = st.segmented_control(
        "下單單位模式",
        options=["零股模式 (最小1股)", "整張模式 (1張=1000股)"],
        default="零股模式 (最小1股)",
        help="高價股（如台積電）在資金較小時建議使用零股模式，避免因買不起整張而無交易。",
    ) or "零股模式 (最小1股)"
    lot_mode = "odd_lot" if "零股" in lot_label else "board_lot"

    st.divider()
    strategy = st.selectbox(
        "主分析策略",
        STRATEGY_LIST,
        key="bt_strategy",
    )

    params: dict = {}
    if strategy == "MA 黃金/死亡交叉":
        params["ma_fast"] = st.slider("快線週期 (MA Fast)", 3, 40, 5)
        params["ma_slow"] = st.slider("慢線週期 (MA Slow)", 10, 120, 20)
    elif strategy == "布林通道逆勢策略":
        params["bb_period"] = st.slider("布林週期", 5, 60, 20)
        params["bb_std"] = st.slider("通道標準差倍數 (σ)", 1.0, 3.0, 2.0, step=0.25)
    elif strategy == "雙布林通道順勢突破":
        params["dbb_period"] = st.slider("雙布林週期", 10, 60, 20)
        params["dbb_entry_std"] = st.slider("突破買入軌道 (+σ)", 1.0, 2.5, 2.0, step=0.25)
        params["dbb_exit_std"] = st.slider("極端停利軌道 (+σ)", 2.5, 4.0, 3.0, step=0.25)
    elif strategy == "RSI 超買超賣反轉":
        params["rsi_period"] = st.slider("RSI 週期", 5, 30, 14)
        params["rsi_oversold"] = st.slider("超賣買入線", 15, 45, 30)
        params["rsi_overbought"] = st.slider("超買賣出線", 55, 90, 70)
    elif strategy == "MACD 黃金/死亡交叉":
        params["macd_fast"] = st.slider("MACD 快線 EMA", 5, 20, 12)
        params["macd_slow"] = st.slider("MACD 慢線 EMA", 18, 50, 26)
        params["macd_sig"] = st.slider("Signal 訊號線 EMA", 5, 20, 9)
    elif strategy == "KD 低檔黃金交叉":
        params["kd_period"] = st.slider("KD RSV 週期", 5, 20, 9)
        params["kd_low"] = st.slider("低檔黃金交叉門檻 (K≤)", 15, 50, 35)
        params["kd_high"] = st.slider("高檔死亡交叉門檻 (K≥)", 60, 90, 75)

    st.divider()
    st.subheader(":material/shield: 風控規則（停損／停利）", anchor=False)
    use_sl = st.checkbox("啟用固定停損 (Stop Loss)", value=False)
    sl_pct = st.slider("固定停損 (%)", 2.0, 25.0, 8.0, step=0.5) if use_sl else None

    use_tp = st.checkbox("啟用固定停利 (Take Profit)", value=False)
    tp_pct = st.slider("固定停利 (%)", 5.0, 100.0, 20.0, step=1.0) if use_tp else None

    use_ts = st.checkbox("啟用移動停損 (Trailing Stop)", value=False)
    ts_pct = st.slider("最高點回落停損 (%)", 3.0, 30.0, 10.0, step=0.5) if use_ts else None


# ═══════════════════════════════════════════════════════════════════════════════
# 載入資料與執行主策略回測
# ═══════════════════════════════════════════════════════════════════════════════

df_full = load_stock(selected)
if df_full.empty:
    st.error(f"找不到 {selected}.csv")
    st.stop()

df = get_horizon_slice(df_full, horizon)
if len(df) < 10:
    st.warning("所選區間資料筆數過少，請切換為較長區間（或選擇「全部」）。")
    st.stop()

stock_name = STOCK_NAMES.get(selected, "")
date_range_str = f"{df.index[0].strftime('%Y/%m/%d')} ～ {df.index[-1].strftime('%Y/%m/%d')}（共 {len(df)} 個交易日）"

st.subheader(f":material/query_stats: {selected} {stock_name} — 深度策略回測分析", anchor=False)
st.caption(
    f"回測區間：**{date_range_str}** ｜ 初始資金：**NT${initial_cap:,.0f}** ｜ "
    f"下單模式：**{lot_label}** ｜ 手續費：買 0.1425% / 賣 0.4425%（含證交稅）"
)

signals_full = compute_signals_for_strategy(df_full, strategy, params)
signals = signals_full.loc[df.index]

res = run_backtest(
    df=df,
    signals=signals,
    initial_capital=initial_cap,
    lot_mode=lot_mode,
    stop_loss_pct=sl_pct,
    take_profit_pct=tp_pct,
    trailing_stop_pct=ts_pct,
)

m = res["metrics"]
equity_df = res["equity_df"]
orders_df = res["orders_df"]
rt_df = res["round_trips_df"]

# ═══════════════════════════════════════════════════════════════════════════════
# 三大分析分頁
# ═══════════════════════════════════════════════════════════════════════════════

tab_single, tab_multi, tab_opt = st.tabs([
    ":material/analytics: 單一策略深度報告",
    ":material/emoji_events: 多策略同台 PK 排行榜",
    ":material/grid_on: 參數最佳化掃描 (Grid Search)",
])


# ───────────────────────────────────────────────────────────────────────────────
# TAB 1：單一策略深度報告
# ───────────────────────────────────────────────────────────────────────────────
with tab_single:
    # 1. 三層式進階 KPI 卡片
    with st.container(border=True):
        st.subheader(f":material/leaderboard: {strategy} — 績效與風險總覽", anchor=False)

        # 第一排：核心報酬與基準對比
        with st.container(horizontal=True):
            st.metric(
                "策略期末資產",
                f"NT${m['final_equity']:,.0f}",
                delta=f"淨損益 NT${m['net_pnl']:+,.0f}",
                delta_color="inverse",
                border=True,
            )
            st.metric(
                "策略總報酬",
                f"{m['strat_return']:+.2f}%",
                delta=f"年化 CAGR {m['cagr']:+.2f}%",
                delta_color="inverse",
                border=True,
            )
            st.metric(
                "Buy & Hold 報酬",
                f"{m['bh_return']:+.2f}%",
                delta=f"年化 CAGR {m['bh_cagr']:+.2f}%",
                delta_color="inverse",
                border=True,
            )
            st.metric(
                "超額報酬 (Alpha)",
                f"{m['excess_return']:+.2f}%",
                delta="打敗 B&H" if m["excess_return"] >= 0 else "落後 B&H",
                delta_color="inverse",
                border=True,
            )

        # 第二排：風險調整指標與回撤分析
        with st.container(horizontal=True):
            st.metric(
                "最大回撤 (MDD)",
                f"{m['mdd']:.2f}%",
                delta=f"B&H 回撤 {m['bh_mdd']:.2f}%",
                delta_color="off",
                border=True,
            )
            st.metric(
                "最長水下恢復期",
                f"{m['max_dd_days']} 天",
                delta=f"年化波動 {m['vol_ann']:.2f}%",
                delta_color="off",
                border=True,
            )
            st.metric("Sharpe Ratio", f"{m['sharpe']:.2f}", border=True)
            st.metric("Sortino Ratio", f"{m['sortino']:.2f}", border=True)
            st.metric("Calmar Ratio", f"{m['calmar']:.2f}", border=True)

        # 第三排：交易品質與摩擦成本統計
        with st.container(horizontal=True):
            st.metric(
                "完成波段 / 勝率",
                f"{m['n_trades']} 次 ({m['win_rate']:.1f}%)",
                delta=f"最高連勝 {m['max_win_streak']} / 連敗 {m['max_loss_streak']}",
                delta_color="off",
                border=True,
            )
            pf_str = f"{m['profit_factor']:.2f}" if m["profit_factor"] < 90 else "∞"
            pr_str = f"{m['payoff_ratio']:.2f}" if m["payoff_ratio"] < 90 else "∞"
            st.metric(
                "獲利因子 (Profit Factor)",
                pf_str,
                delta=f"賺賠比 {pr_str}",
                delta_color="off",
                border=True,
            )
            st.metric(
                "單筆期望值",
                f"{m['expectancy_pct']:+.2f}%",
                delta=f"平均 NT${m['expectancy_ntd']:+,.0f}/筆",
                delta_color="inverse",
                border=True,
            )
            st.metric(
                "最佳 / 最差單筆",
                f"{m['best_trade_pct']:+.1f}% / {m['worst_trade_pct']:+.1f}%",
                delta=f"平均持倉 {m['avg_hold_days']:.1f} 天",
                delta_color="off",
                border=True,
            )
            st.metric(
                "總手續費與證交稅",
                f"NT${m['total_fees']:,.0f}",
                delta=f"市場曝險 {m['exposure_pct']:.1f}% 時間",
                delta_color="off",
                border=True,
            )

    # 2. 權益曲線 + 水下回撤圖 (Underwater Drawdown Chart)
    with st.container(border=True):
        st.subheader(":material/show_chart: 權益曲線 vs 水下回撤曲線 (Underwater Drawdown)", anchor=False)
        st.caption("上圖為資產淨值走勢，下圖為歷史各時間點從前波最高點回落的幅度（水下越深代表套牢回撤越大）。")

        fig_eq = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.62, 0.38],
            subplot_titles=("資產淨值曲線 (NTD)", "水下回撤幅度 (Underwater Drawdown %)"),
        )

        fig_eq.add_trace(
            go.Scatter(
                x=equity_df.index, y=equity_df["Strategy"],
                name=f"策略：{strategy}",
                line=dict(color="#f59e0b", width=2.4),
            ),
            row=1, col=1,
        )
        fig_eq.add_trace(
            go.Scatter(
                x=equity_df.index, y=equity_df["BH"],
                name="Buy & Hold 基準",
                line=dict(color="#94a3b8", width=1.8, dash="dash"),
            ),
            row=1, col=1,
        )

        fig_eq.add_trace(
            go.Scatter(
                x=equity_df.index, y=equity_df["Strategy_DD"],
                name="策略回撤 (%)",
                line=dict(color="#ef4444", width=1.6),
                fill="tozeroy",
                fillcolor="rgba(239,68,68,0.18)",
            ),
            row=2, col=1,
        )
        fig_eq.add_trace(
            go.Scatter(
                x=equity_df.index, y=equity_df["BH_DD"],
                name="B&H 回撤 (%)",
                line=dict(color="#64748b", width=1.3, dash="dot"),
            ),
            row=2, col=1,
        )

        fig_eq.update_layout(
            height=520,
            hovermode="x unified",
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
            margin=dict(t=55, b=25, l=70, r=20),
        )
        fig_eq.update_xaxes(gridcolor="#1e2535")
        fig_eq.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_eq)

    # 3. K 線 + 實際進出場標記（含停損/停利標示）+ 策略指標線
    with st.container(border=True):
        st.subheader(":material/candlestick_chart: K 線 + 實際進出場點位與持倉區間", anchor=False)

        fig_k = go.Figure()

        # 持倉期間高亮背景
        in_pos_series = equity_df["InPosition"]
        pos_diff = in_pos_series.diff().fillna(in_pos_series.iloc[0])
        starts = list(equity_df.index[pos_diff == 1])
        ends = list(equity_df.index[pos_diff == -1])
        if len(starts) > len(ends):
            ends.append(equity_df.index[-1])
        for s_dt, e_dt in zip(starts, ends):
            fig_k.add_vrect(
                x0=s_dt, x1=e_dt,
                fillcolor="rgba(245,158,11,0.09)",
                line_width=0,
            )

        # K 線
        fig_k.add_trace(
            go.Candlestick(
                x=df.index,
                open=df["Open"], high=df["High"],
                low=df["Low"], close=df["Close"],
                name="K線",
                increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
                increasing_fillcolor="#ef4444", decreasing_fillcolor="#22c55e",
            )
        )

        # 疊加對應策略技術線
        if strategy == "MA 黃金/死亡交叉":
            f_w, s_w = params.get("ma_fast", 5), params.get("ma_slow", 20)
            ma_df = calc_ma(df_full, [f_w, s_w]).loc[df.index]
            fig_k.add_trace(go.Scatter(x=df.index, y=ma_df[f"MA{f_w}"], name=f"MA{f_w}", line=dict(color="#f59e0b", width=1.5)))
            fig_k.add_trace(go.Scatter(x=df.index, y=ma_df[f"MA{s_w}"], name=f"MA{s_w}", line=dict(color="#3b82f6", width=1.5)))
        elif strategy in ("布林通道逆勢策略", "雙布林通道順勢突破"):
            bb_p = params.get("bb_period", params.get("dbb_period", 20))
            bb_s = params.get("bb_std", params.get("dbb_entry_std", 2.0))
            bb_df = calc_bbands(df_full, bb_p, bb_s).loc[df.index]
            fig_k.add_trace(go.Scatter(x=df.index, y=bb_df["b_up"], name=f"BB上軌(+{bb_s}σ)", line=dict(color="#a855f7", width=1.2, dash="dot")))
            fig_k.add_trace(go.Scatter(x=df.index, y=bb_df["b_mid"], name="BB中軌", line=dict(color="#3b82f6", width=1.2)))
            fig_k.add_trace(go.Scatter(x=df.index, y=bb_df["b_low"], name=f"BB下軌(-{bb_s}σ)", line=dict(color="#a855f7", width=1.2, dash="dot")))

        # 從實際成交紀錄 orders_df 標註買賣與停損停利點
        if not orders_df.empty:
            buy_orders = orders_df[orders_df["操作"].str.contains("買入")]
            sell_orders = orders_df[~orders_df["操作"].str.contains("買入")]

            if not buy_orders.empty:
                b_dates = pd.to_datetime(buy_orders["日期"])
                b_y = [df.loc[d, "Low"] * 0.975 if d in df.index else p for d, p in zip(b_dates, buy_orders["成交價"])]
                fig_k.add_trace(
                    go.Scatter(
                        x=b_dates, y=b_y,
                        mode="markers+text",
                        name="買入進場",
                        marker=dict(symbol="triangle-up", color="#ef4444", size=14),
                        text=["買" for _ in b_dates],
                        textposition="bottom center",
                        textfont=dict(color="#ef4444", size=11),
                    )
                )

            if not sell_orders.empty:
                s_dates = pd.to_datetime(sell_orders["日期"])
                s_y = [df.loc[d, "High"] * 1.025 if d in df.index else p for d, p in zip(s_dates, sell_orders["成交價"])]
                s_labels = [
                    "停損" if "停損" in op and "移動" not in op
                    else ("移停" if "移動" in op else ("停利" if "停利" in op else "賣"))
                    for op in sell_orders["操作"]
                ]
                fig_k.add_trace(
                    go.Scatter(
                        x=s_dates, y=s_y,
                        mode="markers+text",
                        name="賣出出場",
                        marker=dict(symbol="triangle-down", color="#22c55e", size=14),
                        text=s_labels,
                        textposition="top center",
                        textfont=dict(color="#22c55e", size=11),
                        customdata=sell_orders["報酬率%"],
                        hovertemplate="出場: %{text}<br>單筆報酬: %{customdata:+.2f}%<extra></extra>",
                    )
                )

        fig_k.update_layout(
            height=440,
            hovermode="x unified",
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            xaxis_rangeslider_visible=False,
            margin=dict(t=40, b=20, l=60, r=20),
        )
        fig_k.update_xaxes(gridcolor="#1e2535")
        fig_k.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_k)
        st.caption("▲ 紅三角 = 買入進場 ｜ ▼ 綠三角 = 出場（賣 / 停損 / 停利 / 移停） ｜ 🟡 淡黃色區間 = 持倉期間")

    # 4. 月度報酬率熱圖 + 單筆交易損益分佈
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        with st.container(border=True):
            st.subheader(":material/calendar_month: 策略月度報酬率熱圖 (%)", anchor=False)
            monthly_eq = equity_df["Strategy"].resample("ME").last()
            monthly_ret = monthly_eq.pct_change() * 100.0
            if len(monthly_eq) >= 1:
                first_m_ret = (monthly_eq.iloc[0] / initial_cap - 1.0) * 100.0
                monthly_ret.iloc[0] = first_m_ret

            m_df = pd.DataFrame({
                "Year": monthly_ret.index.year,
                "Month": monthly_ret.index.month,
                "Ret": monthly_ret.values,
            })
            piv = m_df.pivot(index="Year", columns="Month", values="Ret")
            for m_num in range(1, 13):
                if m_num not in piv.columns:
                    piv[m_num] = np.nan
            piv = piv[sorted(piv.columns)]
            month_names = [f"{i}月" for i in range(1, 13)]
            z_vals = piv.values
            text_vals = [[f"{v:+.1f}%" if pd.notna(v) else "" for v in row] for row in z_vals]

            fig_hm = go.Figure(
                go.Heatmap(
                    x=month_names,
                    y=[str(y) for y in piv.index],
                    z=z_vals,
                    text=text_vals,
                    texttemplate="%{text}",
                    colorscale=[[0.0, "#16a34a"], [0.5, "#1e293b"], [1.0, "#dc2626"]],
                    zmid=0,
                    colorbar=dict(title="報酬%"),
                )
            )
            fig_hm.update_layout(
                height=320,
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
                margin=dict(t=20, b=30, l=50, r=20),
            )
            st.plotly_chart(fig_hm)

    with col_m2:
        with st.container(border=True):
            st.subheader(":material/bar_chart: 波段單筆報酬率分佈", anchor=False)
            if not rt_df.empty:
                fig_dist = go.Figure()
                colors_bar = ["#ef4444" if r > 0 else "#22c55e" for r in rt_df["報酬率%"]]
                fig_dist.add_trace(
                    go.Bar(
                        x=[f"#{i+1} ({d})" for i, d in enumerate(rt_df["賣出日期"])],
                        y=rt_df["報酬率%"],
                        marker_color=colors_bar,
                        text=[f"{r:+.1f}%" for r in rt_df["報酬率%"]],
                        textposition="auto",
                        customdata=rt_df["出場原因"],
                        hovertemplate="第 %{x}<br>報酬率: %{y:+.2f}%<br>原因: %{customdata}<extra></extra>",
                    )
                )
                fig_dist.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
                fig_dist.update_layout(
                    height=320,
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font_color="#fafafa",
                    xaxis_title="各波段交易 (依出場時間序)",
                    yaxis_title="單筆淨報酬率 (%)",
                    margin=dict(t=20, b=40, l=50, r=20),
                )
                fig_dist.update_xaxes(gridcolor="#1e2535")
                fig_dist.update_yaxes(gridcolor="#1e2535")
                st.plotly_chart(fig_dist)
            else:
                st.info("此區間尚無已平倉之完整波段交易。")

    # 5. 交易明細表（成對波段明細 + 逐筆委託明細 + CSV 下載）
    with st.container(border=True):
        st.subheader(":material/receipt_long: 交易明細紀錄", anchor=False)
        log_mode = st.segmented_control(
            "明細檢視模式",
            options=["波段成對交易明細 (Round-Trip)", "逐筆買賣委託紀錄 (Order Log)"],
            default="波段成對交易明細 (Round-Trip)",
        ) or "波段成對交易明細 (Round-Trip)"

        def style_pnl(val):
            if isinstance(val, (int, float)) and pd.notna(val):
                return "color: #ef4444; font-weight: 600" if val > 0 else ("color: #22c55e" if val < 0 else "")
            return ""

        if "波段" in log_mode:
            if rt_df.empty:
                st.info("尚無已完成買賣配對之波段交易。")
            else:
                st.dataframe(
                    rt_df.style.map(style_pnl, subset=["淨損益", "報酬率%"]).format({
                        "買入價": "{:.2f}",
                        "賣出價": "{:.2f}",
                        "股數": "{:,.0f}",
                        "持倉天數": "{:d} 天",
                        "總手續費與稅": "NT${:,.0f}",
                        "淨損益": "NT${:+,.0f}",
                        "報酬率%": "{:+.2f}%",
                    }),
                    hide_index=True,
                )
        else:
            if orders_df.empty:
                st.info("此區間內未產生任何買賣委託。")
            else:
                st.dataframe(
                    orders_df.style.map(style_pnl, subset=["單筆損益", "報酬率%"]).format({
                        "成交價": "{:.2f}",
                        "股數": "{:,.0f}",
                        "交易金額": "NT${:,.0f}",
                        "手續費與稅": "NT${:,.0f}",
                        "剩餘資金": "NT${:,.0f}",
                        "單筆損益": lambda v: f"NT${v:+,.0f}" if pd.notna(v) else "—",
                        "報酬率%": lambda v: f"{v:+.2f}%" if pd.notna(v) else "—",
                    }),
                    hide_index=True,
                )

        if not orders_df.empty:
            csv_buf = io.StringIO()
            (rt_df if "波段" in log_mode and not rt_df.empty else orders_df).to_csv(
                csv_buf, index=False, encoding="utf-8-sig"
            )
            st.download_button(
                label=":material/download: 匯出目前明細 CSV",
                data=csv_buf.getvalue().encode("utf-8-sig"),
                file_name=f"{selected}_{strategy.replace('/', '_')}_backtest.csv",
                mime="text/csv",
            )


# ───────────────────────────────────────────────────────────────────────────────
# TAB 2：多策略同台 PK 排行榜
# ───────────────────────────────────────────────────────────────────────────────
with tab_multi:
    with st.container(border=True):
        st.subheader(f":material/emoji_events: {selected} {stock_name} — 六大策略 vs Buy & Hold 同台比較", anchor=False)
        st.caption(
            "以相同的初始資金、回測區間、下單單位與停損停利風控設定，同時比較 6 種技術分析策略在該檔標的上的表現，找出最適合該股股性的策略。"
        )

        pk_rows = []
        fig_pk_eq = go.Figure()
        fig_pk_dd = go.Figure()

        # 加入 Buy & Hold 基準線
        fig_pk_eq.add_trace(
            go.Scatter(
                x=equity_df.index,
                y=equity_df["BH"],
                name="Buy & Hold (買進持有)",
                line=dict(color=STRAT_COLORS["Buy & Hold"], width=2.8, dash="dash"),
            )
        )
        fig_pk_dd.add_trace(
            go.Scatter(
                x=equity_df.index,
                y=equity_df["BH_DD"],
                name="Buy & Hold",
                line=dict(color=STRAT_COLORS["Buy & Hold"], width=2.0, dash="dash"),
            )
        )

        default_params = {
            "ma_fast": 5, "ma_slow": 20,
            "bb_period": 20, "bb_std": 2.0,
            "dbb_period": 20, "dbb_entry_std": 2.0, "dbb_exit_std": 3.0,
            "rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70,
            "macd_fast": 12, "macd_slow": 26, "macd_sig": 9,
            "kd_period": 9, "kd_low": 35, "kd_high": 75,
        }
        # 若使用者正在調整當前主策略參數，將其覆蓋進比較表
        merged_params = {**default_params, **params}

        for s_name in STRATEGY_LIST:
            sig_f = compute_signals_for_strategy(df_full, s_name, merged_params)
            sig_sub = sig_f.loc[df.index]
            r_s = run_backtest(
                df=df,
                signals=sig_sub,
                initial_capital=initial_cap,
                lot_mode=lot_mode,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                trailing_stop_pct=ts_pct,
            )
            ms = r_s["metrics"]
            eq_s = r_s["equity_df"]

            fig_pk_eq.add_trace(
                go.Scatter(
                    x=eq_s.index,
                    y=eq_s["Strategy"],
                    name=s_name,
                    line=dict(color=STRAT_COLORS.get(s_name, "#3b82f6"), width=2.1),
                )
            )
            fig_pk_dd.add_trace(
                go.Scatter(
                    x=eq_s.index,
                    y=eq_s["Strategy_DD"],
                    name=s_name,
                    line=dict(color=STRAT_COLORS.get(s_name, "#3b82f6"), width=1.6),
                )
            )

            pk_rows.append({
                "策略名稱": s_name,
                "總報酬率": ms["strat_return"],
                "年化報酬(CAGR)": ms["cagr"],
                "超額報酬(vs B&H)": ms["excess_return"],
                "最大回撤(MDD)": ms["mdd"],
                "Sharpe": ms["sharpe"],
                "Sortino": ms["sortino"],
                "Calmar": ms["calmar"],
                "波段次數": ms["n_trades"],
                "勝率%": ms["win_rate"],
                "獲利因子": ms["profit_factor"] if ms["profit_factor"] < 90 else np.nan,
                "賺賠比": ms["payoff_ratio"] if ms["payoff_ratio"] < 90 else np.nan,
                "平均持倉": ms["avg_hold_days"],
                "總手續費與稅": ms["total_fees"],
                "期末資產": ms["final_equity"],
            })

        # 加入 Buy & Hold 一列供直接比較
        pk_rows.append({
            "策略名稱": "📌 Buy & Hold (買進持有基準)",
            "總報酬率": m["bh_return"],
            "年化報酬(CAGR)": m["bh_cagr"],
            "超額報酬(vs B&H)": 0.0,
            "最大回撤(MDD)": m["bh_mdd"],
            "Sharpe": np.nan,
            "Sortino": np.nan,
            "Calmar": m["bh_cagr"] / abs(m["bh_mdd"]) if abs(m["bh_mdd"]) > 1e-6 else 0.0,
            "波段次數": 1,
            "勝率%": 100.0 if m["bh_return"] > 0 else 0.0,
            "獲利因子": np.nan,
            "賺賠比": np.nan,
            "平均持倉": float(len(df)),
            "總手續費與稅": initial_cap * BUY_FEE,
            "期末資產": float(equity_df["BH"].iloc[-1]),
        })

        pk_df = pd.DataFrame(pk_rows).sort_values("總報酬率", ascending=False).set_index("策略名稱")

        best_strat_row = pk_df.iloc[0]
        st.success(
            f"🏆 **此區間最佳表現策略：{pk_df.index[0]}** "
            f"（總報酬 **{best_strat_row['總報酬率']:+.2f}%** ｜ 最大回撤 **{best_strat_row['最大回撤(MDD)']:.2f}%**）"
        )

        st.dataframe(
            pk_df.style.map(
                lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and pd.notna(v) and v > 0
                else ("color: #22c55e" if isinstance(v, (int, float)) and pd.notna(v) and v < 0 else ""),
                subset=["總報酬率", "年化報酬(CAGR)", "超額報酬(vs B&H)"],
            ).format({
                "總報酬率": "{:+.2f}%",
                "年化報酬(CAGR)": "{:+.2f}%",
                "超額報酬(vs B&H)": "{:+.2f}%",
                "最大回撤(MDD)": "{:.2f}%",
                "Sharpe": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                "Sortino": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                "Calmar": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                "波段次數": "{:d}",
                "勝率%": "{:.1f}%",
                "獲利因子": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                "賺賠比": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                "平均持倉": "{:.1f} 天",
                "總手續費與稅": "NT${:,.0f}",
                "期末資產": "NT${:,.0f}",
            }),
        )

        fig_pk_eq.update_layout(
            title="多策略權益曲線疊圖 (NTD)",
            height=420,
            hovermode="x unified",
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            margin=dict(t=50, b=25, l=70, r=20),
        )
        fig_pk_eq.update_xaxes(gridcolor="#1e2535")
        fig_pk_eq.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_pk_eq)

        fig_pk_dd.update_layout(
            title="多策略水下回撤比較 (Underwater Drawdown %)",
            height=300,
            hovermode="x unified",
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            margin=dict(t=50, b=25, l=70, r=20),
        )
        fig_pk_dd.update_xaxes(gridcolor="#1e2535")
        fig_pk_dd.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_pk_dd)


# ───────────────────────────────────────────────────────────────────────────────
# TAB 3：參數最佳化掃描 (Parameter Grid Search)
# ───────────────────────────────────────────────────────────────────────────────
with tab_opt:
    with st.container(border=True):
        st.subheader(f":material/grid_on: {selected} {stock_name} — 策略參數二維網格最佳化 (Grid Search)", anchor=False)
        st.caption("自動掃描不同參數組合在所選區間的回測表現，透過熱力圖找出報酬最高、風險調整後表現最穩健的「高原區」參數。")

        opt_col1, opt_col2 = st.columns(2)
        with opt_col1:
            opt_strat = st.selectbox(
                "選擇要最佳化的策略",
                ["MA 黃金/死亡交叉", "布林通道逆勢策略", "RSI 超買超賣反轉", "KD 低檔黃金交叉"],
                key="bt_opt_strat",
            )
        with opt_col2:
            opt_metric_label = st.segmented_control(
                "熱力圖評估指標",
                options=["總報酬率(%)", "Sharpe Ratio", "Calmar Ratio", "勝率(%)"],
                default="總報酬率(%)",
            ) or "總報酬率(%)"

        metric_key_map = {
            "總報酬率(%)": "strat_return",
            "Sharpe Ratio": "sharpe",
            "Calmar Ratio": "calmar",
            "勝率(%)": "win_rate",
        }
        target_m_key = metric_key_map[opt_metric_label]

        # 定義各策略的 2D 掃描網格
        if opt_strat == "MA 黃金/死亡交叉":
            x_vals = [3, 5, 8, 10, 15, 20]
            y_vals = [15, 20, 30, 45, 60, 90]
            x_title, y_title = "快線週期 (MA Fast)", "慢線週期 (MA Slow)"
        elif opt_strat == "布林通道逆勢策略":
            x_vals = [10, 15, 20, 25, 30, 40]
            y_vals = [1.5, 1.75, 2.0, 2.25, 2.5, 3.0]
            x_title, y_title = "布林週期 (Period)", "標準差倍數 (σ)"
        elif opt_strat == "RSI 超買超賣反轉":
            x_vals = [6, 10, 14, 18, 24]
            y_vals = [20, 25, 30, 35, 40]
            x_title, y_title = "RSI 週期", "超賣買入線 (Oversold)"
        else:  # KD
            x_vals = [5, 7, 9, 12, 14]
            y_vals = [20, 25, 30, 35, 40]
            x_title, y_title = "KD RSV 週期", "低檔買入門檻 (K≤)"

        z_matrix = []
        text_matrix = []
        grid_records = []

        for y_v in y_vals:
            row_z = []
            row_txt = []
            for x_v in x_vals:
                if opt_strat == "MA 黃金/死亡交叉" and x_v >= y_v:
                    row_z.append(np.nan)
                    row_txt.append("—")
                    continue

                if opt_strat == "MA 黃金/死亡交叉":
                    sig_g = gen_ma_signals(df_full, int(x_v), int(y_v)).loc[df.index]
                    p_desc = f"Fast={x_v}, Slow={y_v}"
                elif opt_strat == "布林通道逆勢策略":
                    sig_g = gen_bb_signals(df_full, int(x_v), float(y_v)).loc[df.index]
                    p_desc = f"Period={x_v}, σ={y_v}"
                elif opt_strat == "RSI 超買超賣反轉":
                    sig_g = gen_rsi_signals(df_full, int(x_v), int(y_v), 70).loc[df.index]
                    p_desc = f"RSI={x_v}, 超賣={y_v}/超買=70"
                else:
                    sig_g = gen_kd_signals(df_full, int(x_v), int(y_v), 75).loc[df.index]
                    p_desc = f"KD={x_v}, 低檔={y_v}/高檔=75"

                r_g = run_backtest(
                    df=df,
                    signals=sig_g,
                    initial_capital=initial_cap,
                    lot_mode=lot_mode,
                    stop_loss_pct=sl_pct,
                    take_profit_pct=tp_pct,
                    trailing_stop_pct=ts_pct,
                )["metrics"]

                val = r_g[target_m_key]
                row_z.append(val)
                row_txt.append(f"{val:+.1f}%" if "%" in opt_metric_label else f"{val:.2f}")
                grid_records.append({
                    "參數組合": p_desc,
                    "總報酬率": r_g["strat_return"],
                    "超額報酬(vs B&H)": r_g["excess_return"],
                    "年化報酬": r_g["cagr"],
                    "最大回撤(MDD)": r_g["mdd"],
                    "Sharpe": r_g["sharpe"],
                    "Calmar": r_g["calmar"],
                    "波段次數": r_g["n_trades"],
                    "勝率%": r_g["win_rate"],
                })
            z_matrix.append(row_z)
            text_matrix.append(row_txt)

        fig_grid = go.Figure(
            go.Heatmap(
                x=[str(x) for x in x_vals],
                y=[str(y) for y in y_vals],
                z=z_matrix,
                text=text_matrix,
                texttemplate="%{text}",
                colorscale="RdYlGn",
                colorbar=dict(title=opt_metric_label),
            )
        )
        fig_grid.update_layout(
            title=f"{opt_strat} — 參數敏感度熱力圖（評估指標：{opt_metric_label}）",
            xaxis_title=x_title,
            yaxis_title=y_title,
            height=400,
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            margin=dict(t=50, b=40, l=70, r=20),
        )
        st.plotly_chart(fig_grid)

        if grid_records:
            st.markdown("**🏅 Top 10 最佳參數組合排行**")
            sort_col = {
                "總報酬率(%)": "總報酬率",
                "Sharpe Ratio": "Sharpe",
                "Calmar Ratio": "Calmar",
                "勝率(%)": "勝率%",
            }[opt_metric_label]
            top_grid_df = (
                pd.DataFrame(grid_records)
                .sort_values(sort_col, ascending=False)
                .head(10)
                .set_index("參數組合")
            )
            st.dataframe(
                top_grid_df.style.map(
                    lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and v > 0
                    else ("color: #22c55e" if isinstance(v, (int, float)) and v < 0 else ""),
                    subset=["總報酬率", "超額報酬(vs B&H)", "年化報酬"],
                ).format({
                    "總報酬率": "{:+.2f}%",
                    "超額報酬(vs B&H)": "{:+.2f}%",
                    "年化報酬": "{:+.2f}%",
                    "最大回撤(MDD)": "{:.2f}%",
                    "Sharpe": "{:.2f}",
                    "Calmar": "{:.2f}",
                    "波段次數": "{:d}",
                    "勝率%": "{:.1f}%",
                }),
            )
