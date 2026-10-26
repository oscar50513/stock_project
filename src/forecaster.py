"""AI 技術指標預測與模擬部位停損停利警示共用引擎 — 供 prediction.py、screener.py 與 daily_report.py 共享"""

import json
import os
import numpy as np
import pandas as pd

from .indicators import (
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

PORTFOLIO_FILE = os.path.join(DATA_DIR, "paper_portfolio.json")

DEFAULT_FEATURE_COLS = [
    "Ret_1D", "Ret_5D", "Ret_20D", "Bias_MA5", "Bias_MA20", "Bias_MA60", "MA5_MA20_Spread",
    "BB_PctB", "BB_Width", "BB_Slope",
    "RSI_14", "RSI_Diff3",
    "MACD_Norm", "MACD_Hist_Norm",
    "KD_K", "KD_Spread",
    "Vol_Ratio5", "Vol_20D",
]


def build_feature_dataframe(sid: str) -> pd.DataFrame:
    """從原始日 K 資料建構 18 項無未來函數的技術指標特徵矩陣。"""
    df = load_stock(sid)
    if df.empty or len(df) < 40:
        return pd.DataFrame()

    res = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    close = res["Close"]

    df_ma = calc_ma(df, [5, 10, 20, 60])
    res["Ret_1D"] = close.pct_change(1) * 100.0
    res["Ret_5D"] = close.pct_change(5) * 100.0
    res["Ret_20D"] = close.pct_change(20) * 100.0
    res["Bias_MA5"] = (close / df_ma["MA5"] - 1.0) * 100.0
    res["Bias_MA20"] = (close / df_ma["MA20"] - 1.0) * 100.0
    ma60_filled = df_ma["MA60"].fillna(df_ma["MA20"])
    res["Bias_MA60"] = (close / ma60_filled - 1.0) * 100.0
    res["MA5_MA20_Spread"] = (df_ma["MA5"] / df_ma["MA20"] - 1.0) * 100.0

    df_bb = calc_bbands(df, 20, 2.0)
    bb_range = (df_bb["b_up"] - df_bb["b_low"]).replace(0, np.nan)
    res["BB_PctB"] = ((close - df_bb["b_low"]) / bb_range) * 100.0
    res["BB_Width"] = df_bb["bband_width"]
    res["BB_Slope"] = df_bb["mid_slope"]

    rsi = calc_rsi(df, 14)
    res["RSI_14"] = rsi
    res["RSI_Diff3"] = rsi.diff(3)

    df_macd = calc_macd(df)
    res["MACD_Norm"] = (df_macd["MACD"] / close) * 100.0
    res["MACD_Hist_Norm"] = (df_macd["Histogram"] / close) * 100.0

    df_kd = calc_kd(df, 9)
    res["KD_K"] = df_kd["K"]
    res["KD_Spread"] = df_kd["K"] - df_kd["D"]

    vol_ma5 = res["Volume"].rolling(5).mean().replace(0, np.nan)
    res["Vol_Ratio5"] = (res["Volume"] / vol_ma5).clip(0.1, 8.0)
    res["Vol_20D"] = res["Ret_1D"].rolling(20).std()

    return res.dropna()


def fit_ridge_predict(X_train: np.ndarray, y_train: np.ndarray, x_now: np.ndarray, alpha: float = 5.0) -> tuple[float, np.ndarray]:
    """標準化多因子嶺迴歸 (Closed-Form L2 Ridge Regression)。"""
    mu = X_train.mean(axis=0)
    sigma = X_train.std(axis=0)
    sigma[sigma < 1e-8] = 1.0

    Xz = (X_train - mu) / sigma
    xz_now = (x_now - mu) / sigma

    y_mean = float(y_train.mean())
    yc = y_train - y_mean

    n_feat = Xz.shape[1]
    A = Xz.T @ Xz + alpha * np.eye(n_feat)
    b = Xz.T @ yc
    try:
        w = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        w = np.linalg.lstsq(A, b, rcond=None)[0]

    pred = y_mean + float(xz_now @ w)
    contributions = xz_now * w
    return pred, contributions


def quick_forecast_stock(sid: str, horizon: int = 5, window: int = 360, k_neighbors: int = 8, alpha: float = 5.0) -> dict | None:
    """快速計算單一標的未來 horizon 日之 Ensemble 綜合預測結果。"""
    feat_df = build_feature_dataframe(sid)
    if feat_df.empty or len(feat_df) < 45:
        return None

    df_work = feat_df.tail(min(len(feat_df), window + horizon + 65))
    close_arr = df_work["Close"].values
    X_all = df_work[DEFAULT_FEATURE_COLS].values
    x_today = X_all[-1]
    latest_close = float(close_arr[-1])

    # 1. KNN
    valid_end = max(10, len(df_work) - horizon)
    X_hist = X_all[:valid_end]
    mu_h = X_hist.mean(axis=0)
    sd_h = X_hist.std(axis=0)
    sd_h[sd_h < 1e-8] = 1.0
    dists = np.sqrt(np.mean(((X_hist - mu_h) / sd_h - (x_today - mu_h) / sd_h) ** 2, axis=1))
    sorted_indices = np.argsort(dists)
    picked = []
    for idx in sorted_indices:
        if all(abs(int(idx) - int(p)) >= 3 for p in picked):
            picked.append(int(idx))
        if len(picked) >= k_neighbors:
            break

    analog_rets = []
    weights_knn = []
    for idx in picked:
        base_c = float(close_arr[idx])
        target_idx = min(idx + horizon, len(close_arr) - 1)
        r_h = (float(close_arr[target_idx]) / base_c - 1.0) * 100.0
        analog_rets.append(r_h)
        weights_knn.append(float(np.exp(-dists[idx] / 2.5)))

    analog_arr = np.array(analog_rets)
    w_arr = np.array(weights_knn)
    w_arr = w_arr / (w_arr.sum() + 1e-9)
    knn_ret_h = float(analog_arr @ w_arr)

    # 2. Ridge (h = horizon & h = 1)
    y_h = (pd.Series(close_arr).shift(-horizon).values[:-horizon] / close_arr[:-horizon] - 1.0) * 100.0
    X_tr = X_all[:-horizon]
    if len(X_tr) > window:
        X_tr = X_tr[-window:]
        y_h = y_h[-window:]
    ridge_ret_h, _ = fit_ridge_predict(X_tr, y_h, x_today, alpha)

    y_1 = (pd.Series(close_arr).shift(-1).values[:-1] / close_arr[:-1] - 1.0) * 100.0
    X_tr1 = X_all[:-1][-window:]
    y_1 = y_1[-window:]
    ridge_ret_1, _ = fit_ridge_predict(X_tr1, y_1, x_today, alpha)

    # 3. 動能漂移
    daily_rets = pd.Series(close_arr).pct_change().dropna().tail(60).values
    daily_vol = float(np.std(daily_rets)) if len(daily_rets) > 5 else 0.015
    recent_drift = float(np.mean(daily_rets[-20:])) if len(daily_rets) >= 20 else 0.0
    rsi_now = float(df_work["RSI_14"].iloc[-1])
    ma_spread_now = float(df_work["MA5_MA20_Spread"].iloc[-1]) / 100.0
    adj_daily_drift = 0.5 * recent_drift + 0.3 * (ma_spread_now / 10.0) - 0.0002 * ((rsi_now - 50.0) / 10.0)
    drift_ret_h = ((1.0 + adj_daily_drift) ** horizon - 1.0) * 100.0

    final_ret_h = 0.45 * ridge_ret_h + 0.35 * knn_ret_h + 0.20 * drift_ret_h
    target_price = latest_close * (1.0 + final_ret_h / 100.0)
    next_price = latest_close * (1.0 + ridge_ret_1 / 100.0)

    knn_std = float(np.std(analog_arr)) if len(analog_arr) > 1 else (daily_vol * 100.0 * np.sqrt(horizon))
    comb_std = 0.5 * (daily_vol * 100.0 * np.sqrt(horizon)) + 0.5 * knn_std
    knn_win_prob = float((analog_arr > 0).mean()) * 100.0
    z_score = float(final_ret_h / (comb_std + 1e-6))
    norm_prob = float(0.5 * (1.0 + np.tanh(0.8 * z_score))) * 100.0
    up_prob = 0.55 * norm_prob + 0.45 * knn_win_prob

    name = STOCK_NAMES.get(sid, ACTIVE_ETF_META.get(sid, {}).get("name", sid))
    return {
        "sid": sid,
        "name": name,
        "latest_close": latest_close,
        "next_price": next_price,
        "next_ret_pct": ridge_ret_1,
        "target_price": target_price,
        "pred_ret_pct": final_ret_h,
        "up_prob": up_prob,
    }


def get_ai_forecast_summary(horizon: int = 5, top_n: int = 4) -> str:
    """掃描全市場標的並產生供 Discord 日報使用的 AI 股價預測摘要字串。"""
    results = []
    for sid in get_stock_ids():
        r = quick_forecast_stock(sid, horizon=horizon)
        if r is not None:
            results.append(r)

    if not results:
        return "目前無足夠資料進行 AI 預測"

    results.sort(key=lambda x: (x["pred_ret_pct"], x["up_prob"]), reverse=True)
    top_bull = [r for r in results if r["pred_ret_pct"] > 0][:top_n]
    top_bear = [r for r in reversed(results) if r["pred_ret_pct"] < 0][:2]

    lines = []
    if top_bull:
        for r in top_bull:
            lines.append(
                f"🔴 **{r['sid']} {r['name']}**：現價 `{r['latest_close']:.2f}` → "
                f"T+{horizon}目標 **`NT${r['target_price']:.2f}`** (`{r['pred_ret_pct']:+.2f}%`｜勝率 `{r['up_prob']:.0f}%`)"
            )
    if top_bear:
        for r in top_bear:
            lines.append(
                f"🟢 **{r['sid']} {r['name']}**：現價 `{r['latest_close']:.2f}` → "
                f"T+{horizon}目標 **`NT${r['target_price']:.2f}`** (`{r['pred_ret_pct']:+.2f}%`｜勝率 `{r['up_prob']:.0f}%`)"
            )
    return "\n".join(lines) if lines else "目前各標的預測均呈中性區間震盪"


def get_portfolio_alert_summary() -> str:
    """讀取模擬交易持倉 (paper_portfolio.json)，檢查最新收盤損益與是否觸發停損／停利目標價。"""
    if not os.path.exists(PORTFOLIO_FILE):
        return "目前尚無模擬交易持倉紀錄"

    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            pf = json.load(f)
    except Exception:
        return "無法讀取模擬交易紀錄檔"

    holdings = pf.get("holdings", {})
    if not holdings:
        return f"目前空手無持倉（可用現金 `NT${pf.get('cash', 1_000_000):,.0f}`）"

    lines = []
    for sid, pos in holdings.items():
        df = load_stock(sid)
        if df.empty:
            continue
        price = float(df["Close"].iloc[-1])
        shares = int(pos.get("shares", 0))
        avg_cost = float(pos.get("avg_cost", price))
        pnl_pct = (price / avg_cost - 1.0) * 100.0 if avg_cost > 0 else 0.0
        pnl_ntd = (price - avg_cost) * shares
        sl_p = pos.get("stop_loss_price")
        tp_p = pos.get("take_profit_price")
        name = STOCK_NAMES.get(sid, sid)

        alert_tag = ""
        if tp_p and price >= float(tp_p):
            alert_tag = f" 🎯 **【停利達標 ≥ {float(tp_p):.2f}】**"
        elif sl_p and price <= float(sl_p):
            alert_tag = f" ⚠️ **【觸發停損 ≤ {float(sl_p):.2f}】**"
        elif tp_p or sl_p:
            sl_str = f"停損 {float(sl_p):.1f}" if sl_p else ""
            tp_str = f"停利 {float(tp_p):.1f}" if tp_p else ""
            sep = "/" if (sl_str and tp_str) else ""
            alert_tag = f" （監控：{sl_str}{sep}{tp_str}）"

        icon = "🔴" if pnl_pct >= 0 else "🟢"
        lines.append(
            f"{icon} **{sid} {name}**（`{shares:,}`股）：現價 `{price:.2f}` / 成本 `{avg_cost:.2f}` ｜ "
            f"損益 **`NT${pnl_ntd:+,.0f}`** (`{pnl_pct:+.2f}%`){alert_tag}"
        )

    return "\n".join(lines) if lines else "目前無有效持倉資料"
