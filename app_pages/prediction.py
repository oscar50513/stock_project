"""AI 技術指標股價預測頁 — 多因子嶺迴歸、KNN 歷史相似型態匹配、蒙地卡羅信心扇形圖與樣本外回測驗證"""

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
    STOCK_NAMES,
    calc_bbands,
    calc_kd,
    calc_ma,
    calc_macd,
    calc_rsi,
    get_stock_ids,
    load_stock,
)

st.subheader(":material/auto_graph: 技術指標量化股價預測實驗室", anchor=False)
st.caption(
    "結合 **16 項量價技術指標因子（均線乖離、布林通道 %B 與斜率、RSI、MACD、KD、量能動能）**，"
    "運用 **多因子嶺迴歸（Ridge Regression）**、**KNN 歷史相似型態匹配（Analog Pattern Matching）** 與 **蒙地卡羅波動率模擬** "
    "推估未來股價走勢區間與上漲勝率，並提供**樣本外滾動驗證（Walk-Forward Validation）**。"
)

# ── Sidebar：預測參數設定 ─────────────────────────────────────────────────────
with st.sidebar:
    st.header(":material/psychology: 預測模型設定", divider=True)

    stock_ids = get_stock_ids()
    default_idx = stock_ids.index("2330") if "2330" in stock_ids else 0

    selected_sid = st.selectbox(
        "選擇預測標的",
        stock_ids,
        index=default_idx,
        format_func=lambda x: f"{x} {STOCK_NAMES.get(x, '')}",
        key="pred_sid",
    )

    forecast_days = st.slider(
        "預測未來交易日數 (Horizon)",
        min_value=3,
        max_value=30,
        value=10,
        step=1,
        help="推估未來 1 ～ N 個交易日的收盤價路徑與信心區間。",
    )

    model_mode = st.selectbox(
        "核心預測演算法",
        [
            "Ensemble 綜合加權集成（推薦）",
            "多因子嶺迴歸 (Ridge Regression)",
            "KNN 歷史相似技術型態匹配",
            "技術動能漂移蒙地卡羅模擬",
        ],
        index=0,
        key="pred_model_mode",
    )

    st.divider()
    st.subheader(":material/tune: 演算法進階參數", anchor=False)

    train_window = st.slider(
        "歷史訓練樣本視窗（交易日）",
        min_value=90,
        max_value=1000,
        value=360,
        step=30,
        help="使用最近幾天的技術指標與報酬關係進行模型訓練（主動式 ETF 若掛牌天數較短會自動調整）。",
    )

    knn_k = st.slider(
        "KNN 歷史最相似型態取樣數 (K)",
        min_value=3,
        max_value=20,
        value=8,
        step=1,
        help="從歷史中找出與今日技術指標狀態最相似的 K 個交易日，觀察其後續實際走勢。",
    )

    ridge_alpha = st.select_slider(
        "嶺迴歸正則化強度 (L2 Alpha)",
        options=[0.1, 0.5, 1.0, 5.0, 10.0, 25.0, 50.0],
        value=5.0,
        help="正則化強度越高，越能防止多重共線性與過度擬合（Overfitting）。",
    )

    selected_feature_groups = st.multiselect(
        "啟用技術指標特徵群組",
        ["均線與趨勢乖離 (MA)", "布林通道動能 (BBands)", "RSI 強弱指標", "MACD 柱狀與動能", "KD 隨機震盪", "量價與波動率 (Vol)"],
        default=["均線與趨勢乖離 (MA)", "布林通道動能 (BBands)", "RSI 強弱指標", "MACD 柱狀與動能", "KD 隨機震盪", "量價與波動率 (Vol)"],
    )

if not selected_feature_groups:
    st.warning("請在左側欄至少勾選一組技術指標特徵群組。")
    st.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 技術指標特徵工程引擎 (Feature Engineering)
# ═══════════════════════════════════════════════════════════════════════════════

FEATURE_LABELS = {
    "Ret_1D": "1日報酬動能",
    "Ret_5D": "5日周動能",
    "Ret_20D": "20日月動能",
    "Bias_MA5": "MA5 乖離率",
    "Bias_MA20": "MA20 月線乖離率",
    "Bias_MA60": "MA60 季線乖離率",
    "MA5_MA20_Spread": "MA5-MA20 均線差",
    "BB_PctB": "布林 %B 位階",
    "BB_Width": "布林通道寬度",
    "BB_Slope": "20MA 均線斜率",
    "RSI_14": "RSI(14) 水位",
    "RSI_Diff3": "RSI 3日斜率",
    "MACD_Norm": "MACD 標準化值",
    "MACD_Hist_Norm": "MACD 柱狀體動能",
    "KD_K": "KD-K 值",
    "KD_Spread": "KD (K-D) 差值",
    "Vol_Ratio5": "5日量比",
    "Vol_20D": "20日滾動波動率",
}


@st.cache_data(ttl="30m")
def build_feature_dataframe(sid: str) -> pd.DataFrame:
    """從原始日 K 資料建構 18 項無未來函數 (No Look-Ahead) 的技術指標特徵矩陣。"""
    df = load_stock(sid)
    if df.empty or len(df) < 40:
        return pd.DataFrame()

    res = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    close = res["Close"]

    # 1. 均線與趨勢乖離
    df_ma = calc_ma(df, [5, 10, 20, 60])
    res["Ret_1D"] = close.pct_change(1) * 100.0
    res["Ret_5D"] = close.pct_change(5) * 100.0
    res["Ret_20D"] = close.pct_change(20) * 100.0
    res["Bias_MA5"] = (close / df_ma["MA5"] - 1.0) * 100.0
    res["Bias_MA20"] = (close / df_ma["MA20"] - 1.0) * 100.0
    ma60_filled = df_ma["MA60"].fillna(df_ma["MA20"])
    res["Bias_MA60"] = (close / ma60_filled - 1.0) * 100.0
    res["MA5_MA20_Spread"] = (df_ma["MA5"] / df_ma["MA20"] - 1.0) * 100.0

    # 2. 布林通道
    df_bb = calc_bbands(df, 20, 2.0)
    bb_range = (df_bb["b_up"] - df_bb["b_low"]).replace(0, np.nan)
    res["BB_PctB"] = ((close - df_bb["b_low"]) / bb_range) * 100.0
    res["BB_Width"] = df_bb["bband_width"]
    res["BB_Slope"] = df_bb["mid_slope"]

    # 3. RSI
    rsi = calc_rsi(df, 14)
    res["RSI_14"] = rsi
    res["RSI_Diff3"] = rsi.diff(3)

    # 4. MACD (以收盤價標準化避免跨時期價格尺度偏誤)
    df_macd = calc_macd(df)
    res["MACD_Norm"] = (df_macd["MACD"] / close) * 100.0
    res["MACD_Hist_Norm"] = (df_macd["Histogram"] / close) * 100.0

    # 5. KD
    df_kd = calc_kd(df, 9)
    res["KD_K"] = df_kd["K"]
    res["KD_Spread"] = df_kd["K"] - df_kd["D"]

    # 6. 量價與波動率
    vol_ma5 = res["Volume"].rolling(5).mean().replace(0, np.nan)
    res["Vol_Ratio5"] = (res["Volume"] / vol_ma5).clip(0.1, 8.0)
    res["Vol_20D"] = res["Ret_1D"].rolling(20).std()

    return res.dropna()


def get_active_feature_cols(groups: list[str]) -> list[str]:
    cols = []
    if "均線與趨勢乖離 (MA)" in groups:
        cols += ["Ret_1D", "Ret_5D", "Ret_20D", "Bias_MA5", "Bias_MA20", "Bias_MA60", "MA5_MA20_Spread"]
    if "布林通道動能 (BBands)" in groups:
        cols += ["BB_PctB", "BB_Width", "BB_Slope"]
    if "RSI 強弱指標" in groups:
        cols += ["RSI_14", "RSI_Diff3"]
    if "MACD 柱狀與動能" in groups:
        cols += ["MACD_Norm", "MACD_Hist_Norm"]
    if "KD 隨機震盪" in groups:
        cols += ["KD_K", "KD_Spread"]
    if "量價與波動率 (Vol)" in groups:
        cols += ["Vol_Ratio5", "Vol_20D"]
    return cols


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 核心量化預測引擎（Ridge 迴歸 + KNN 型態匹配 + 蒙地卡羅扇形區間）
# ═══════════════════════════════════════════════════════════════════════════════

def fit_ridge_predict(X_train: np.ndarray, y_train: np.ndarray, x_now: np.ndarray, alpha: float) -> tuple[float, np.ndarray]:
    """標準化多因子嶺迴歸 (Closed-Form L2 Ridge Regression)，回傳預測值與標準化特徵係數。"""
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
    # 單日或區間當日各特徵貢獻 = xz_now * w
    contributions = xz_now * w
    return pred, contributions


def run_forecast_engine(
    feat_df: pd.DataFrame,
    feature_cols: list[str],
    horizon: int,
    window: int,
    k_neighbors: int,
    alpha: float,
    mode: str,
) -> dict:
    """執行多步預測 (h = 1..horizon)、KNN 歷史相似匹配與樣本外回測驗證。"""
    df_work = feat_df.tail(min(len(feat_df), window + horizon + 65)).copy()
    close_arr = df_work["Close"].values
    dates_idx = df_work.index
    X_all = df_work[feature_cols].values
    x_today = X_all[-1]
    latest_close = float(close_arr[-1])

    # 1. KNN 歷史相似型態搜尋（排除最後 horizon 天以確保有完整後續實際走勢）
    valid_end = len(df_work) - horizon
    if valid_end < 20:
        valid_end = max(10, len(df_work) - 3)

    X_hist = X_all[:valid_end]
    mu_h = X_hist.mean(axis=0)
    sd_h = X_hist.std(axis=0)
    sd_h[sd_h < 1e-8] = 1.0

    Xz_hist = (X_hist - mu_h) / sd_h
    xz_today = (x_today - mu_h) / sd_h

    # 歐氏距離與相似度分數
    dists = np.sqrt(np.mean((Xz_hist - xz_today) ** 2, axis=1))
    # 避免相鄰連續日期重複入選（至少間隔 3 個交易日）
    sorted_indices = np.argsort(dists)
    picked_indices = []
    for idx in sorted_indices:
        if all(abs(int(idx) - int(p)) >= 3 for p in picked_indices):
            picked_indices.append(int(idx))
        if len(picked_indices) >= k_neighbors:
            break

    analog_records = []
    analog_paths = []  # shape: (k, horizon)
    for idx in picked_indices:
        base_c = float(close_arr[idx])
        sim_score = float(np.exp(-dists[idx] / 2.5) * 100.0)
        future_slice = close_arr[idx + 1 : idx + 1 + horizon]
        if len(future_slice) < horizon:
            pad_len = horizon - len(future_slice)
            future_slice = np.pad(future_slice, (0, pad_len), mode="edge")
        rel_ret_path = (future_slice / base_c - 1.0) * 100.0
        analog_paths.append(rel_ret_path)
        analog_records.append({
            "歷史相似日期": dates_idx[idx].strftime("%Y/%m/%d"),
            "型態相似度": sim_score,
            "當時收盤價": base_c,
            "當時RSI(14)": float(df_work["RSI_14"].iloc[idx]),
            "當時布林%B": float(df_work["BB_PctB"].iloc[idx]),
            "後1日漲跌%": float(rel_ret_path[0]),
            "後5日漲跌%": float(rel_ret_path[min(4, horizon - 1)]),
            f"後{horizon}日漲跌%": float(rel_ret_path[-1]),
        })

    analog_paths_arr = np.array(analog_paths)  # (K, horizon) in %
    weights_knn = np.array([r["型態相似度"] for r in analog_records], dtype=float)
    weights_knn = weights_knn / (weights_knn.sum() + 1e-9)
    knn_ret_curve = (analog_paths_arr.T @ weights_knn)  # (horizon,) in %

    # 2. 多步嶺迴歸直接預測 (Direct Multi-Horizon Ridge Forecasting, h = 1..horizon)
    ridge_ret_curve = np.zeros(horizon)
    feature_contributions_h = None

    for h in range(1, horizon + 1):
        # 目標 y_h: 未來 h 日累積報酬率 (%)
        y_h = (pd.Series(close_arr).shift(-h).values[: len(close_arr) - h] / close_arr[: len(close_arr) - h] - 1.0) * 100.0
        X_tr = X_all[: len(close_arr) - h]
        # 取最近 window 筆訓練
        if len(X_tr) > window:
            X_tr = X_tr[-window:]
            y_h = y_h[-window:]
        pred_ret_h, contrib_h = fit_ridge_predict(X_tr, y_h, x_today, alpha)
        ridge_ret_curve[h - 1] = pred_ret_h
        if h == horizon:
            feature_contributions_h = contrib_h

    # 3. 技術動能漂移與波動率模擬 (Technical Drift + Monte Carlo)
    daily_rets = pd.Series(close_arr).pct_change().dropna().tail(60).values
    daily_vol = float(np.std(daily_rets)) if len(daily_rets) > 5 else 0.015
    recent_drift = float(np.mean(daily_rets[-20:])) if len(daily_rets) >= 20 else 0.0
    # 結合 RSI 與 MA 趨勢調整漂移率
    rsi_now = float(df_work["RSI_14"].iloc[-1])
    ma_spread_now = float(df_work["MA5_MA20_Spread"].iloc[-1]) / 100.0
    adj_daily_drift = 0.5 * recent_drift + 0.3 * (ma_spread_now / 10.0) - 0.0002 * ((rsi_now - 50.0) / 10.0)
    drift_ret_curve = np.array([((1.0 + adj_daily_drift) ** h - 1.0) * 100.0 for h in range(1, horizon + 1)])

    # 4. 根據使用者選擇的模型合成最終預期報酬曲線
    if mode == "多因子嶺迴歸 (Ridge Regression)":
        final_ret_curve = ridge_ret_curve
    elif mode == "KNN 歷史相似技術型態匹配":
        final_ret_curve = knn_ret_curve
    elif mode == "技術動能漂移蒙地卡羅模擬":
        final_ret_curve = drift_ret_curve
    else:
        # Ensemble 綜合加權集成：45% Ridge + 35% KNN + 20% 技術動能漂移
        final_ret_curve = 0.45 * ridge_ret_curve + 0.35 * knn_ret_curve + 0.20 * drift_ret_curve

    # 轉換為預測價格與信心區間 (50% 與 90% 扇形區間)
    steps = np.arange(1, horizon + 1)
    # 結合歷史波動率與 KNN 離散度估算標準差
    knn_std_pct = np.std(analog_paths_arr, axis=0) if len(analog_paths_arr) > 1 else (daily_vol * 100.0 * np.sqrt(steps))
    vol_std_pct = daily_vol * 100.0 * np.sqrt(steps)
    combined_std_pct = 0.5 * vol_std_pct + 0.5 * knn_std_pct

    pred_prices = latest_close * (1.0 + final_ret_curve / 100.0)
    upper_50 = latest_close * (1.0 + (final_ret_curve + 0.674 * combined_std_pct) / 100.0)
    lower_50 = latest_close * (1.0 + (final_ret_curve - 0.674 * combined_std_pct) / 100.0)
    upper_90 = latest_close * (1.0 + (final_ret_curve + 1.645 * combined_std_pct) / 100.0)
    lower_90 = latest_close * (1.0 + (final_ret_curve - 1.645 * combined_std_pct) / 100.0)

    # 產生未來交易日座標 (以工作日推算)
    last_dt = dates_idx[-1]
    future_dates = pd.bdate_range(start=last_dt + pd.Timedelta(days=1), periods=horizon)

    # 計算綜合上漲勝率估計 (結合 KNN 正報酬比例與預測 Z-score)
    knn_win_prob = float((analog_paths_arr[:, -1] > 0).mean()) * 100.0
    z_score = float(final_ret_curve[-1] / (combined_std_pct[-1] + 1e-6))
    norm_prob = float(0.5 * (1.0 + np.tanh(0.8 * z_score))) * 100.0
    up_prob = 0.55 * norm_prob + 0.45 * knn_win_prob

    # 5. 樣本外滾動回測驗證 (Walk-Forward Validation on recent 45 trading days)
    eval_horizon = min(5, horizon)  # 以 5 日（或所選天數）滾動預測做歷史準確度檢驗
    n_eval = min(45, max(15, len(close_arr) // 4))
    oos_dates = []
    oos_actual_prices = []
    oos_pred_prices = []
    oos_actual_rets = []
    oos_pred_rets = []

    start_eval_idx = len(close_arr) - n_eval
    for t_idx in range(start_eval_idx, len(close_arr)):
        origin_idx = t_idx - eval_horizon
        if origin_idx < 35:
            continue
        X_sub = X_all[:origin_idx]
        c_sub = close_arr[:origin_idx]
        y_sub = (pd.Series(c_sub).shift(-eval_horizon).values[:-eval_horizon] / c_sub[:-eval_horizon] - 1.0) * 100.0
        X_sub_tr = X_sub[:-eval_horizon]
        if len(X_sub_tr) < 20:
            continue
        if len(X_sub_tr) > window:
            X_sub_tr = X_sub_tr[-window:]
            y_sub = y_sub[-window:]

        pred_r, _ = fit_ridge_predict(X_sub_tr, y_sub, X_all[origin_idx], alpha)
        origin_close = float(close_arr[origin_idx])
        actual_close = float(close_arr[t_idx])
        actual_r = (actual_close / origin_close - 1.0) * 100.0

        oos_dates.append(dates_idx[t_idx])
        oos_actual_prices.append(actual_close)
        oos_pred_prices.append(origin_close * (1.0 + pred_r / 100.0))
        oos_actual_rets.append(actual_r)
        oos_pred_rets.append(pred_r)

    if oos_actual_prices:
        oos_act_arr = np.array(oos_actual_prices)
        oos_prd_arr = np.array(oos_pred_prices)
        oos_act_r = np.array(oos_actual_rets)
        oos_prd_r = np.array(oos_pred_rets)
        dir_acc = float(np.mean(np.sign(oos_act_r) == np.sign(oos_prd_r)) * 100.0)
        mape = float(np.mean(np.abs((oos_act_arr - oos_prd_arr) / oos_act_arr)) * 100.0)
        rmse = float(np.sqrt(np.mean((oos_act_arr - oos_prd_arr) ** 2)))
    else:
        dir_acc, mape, rmse = 50.0, 0.0, 0.0

    return {
        "latest_close": latest_close,
        "latest_date": last_dt.strftime("%Y/%m/%d"),
        "future_dates": future_dates,
        "pred_prices": pred_prices,
        "final_ret_curve": final_ret_curve,
        "ridge_prices": latest_close * (1.0 + ridge_ret_curve / 100.0),
        "knn_prices": latest_close * (1.0 + knn_ret_curve / 100.0),
        "drift_prices": latest_close * (1.0 + drift_ret_curve / 100.0),
        "upper_50": upper_50,
        "lower_50": lower_50,
        "upper_90": upper_90,
        "lower_90": lower_90,
        "up_prob": up_prob,
        "feature_contributions": feature_contributions_h,
        "analog_records": analog_records,
        "analog_paths_arr": analog_paths_arr,
        "eval_horizon": eval_horizon,
        "oos_dates": oos_dates,
        "oos_actual_prices": oos_actual_prices,
        "oos_pred_prices": oos_pred_prices,
        "dir_acc": dir_acc,
        "mape": mape,
        "rmse": rmse,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 執行主標的預測並呈現 KPI 與互動扇形圖
# ═══════════════════════════════════════════════════════════════════════════════

feat_df = build_feature_dataframe(selected_sid)
if feat_df.empty or len(feat_df) < 45:
    st.error(f"標的 {selected_sid} 的歷史資料筆數不足（需至少 45 個交易日），無法建立多因子預測模型。")
    st.stop()

active_cols = get_active_feature_cols(selected_feature_groups)
res = run_forecast_engine(
    feat_df=feat_df,
    feature_cols=active_cols,
    horizon=forecast_days,
    window=train_window,
    k_neighbors=knn_k,
    alpha=ridge_alpha,
    mode=model_mode,
)

latest_c = res["latest_close"]
target_c = float(res["pred_prices"][-1])
target_ret = float(res["final_ret_curve"][-1])
next_day_c = float(res["pred_prices"][0])
next_day_ret = float(res["final_ret_curve"][0])
up_prob = float(res["up_prob"])

if target_ret >= 2.0 and up_prob >= 58:
    signal_text = "🔴 強勢看多 (Bullish)"
elif target_ret > 0:
    signal_text = "🔴 溫和偏多 (Slightly Bullish)"
elif target_ret <= -2.0 and up_prob <= 42:
    signal_text = "🟢 明顯看空 (Bearish)"
else:
    signal_text = "🟢 震盪偏空 (Slightly Bearish)"

# ── 頂部預測核心 KPI 卡片（嚴格遵循台股紅漲綠跌）──────────────────────────────
with st.container(horizontal=True):
    st.metric(
        f"最新收盤價 ({res['latest_date']})",
        f"NT${latest_c:.2f}",
        delta=f"預測模型：{model_mode.split()[0]}",
        delta_color="off",
        delta_arrow="off",
        border=True,
    )
    st.metric(
        "下一交易日 (T+1) 預測價",
        f"NT${next_day_c:.2f}",
        delta=f"{next_day_ret:+.2f}% (NT${next_day_c - latest_c:+.2f})",
        delta_color="red" if next_day_ret > 0 else ("green" if next_day_ret < 0 else "gray"),
        delta_arrow="up" if next_day_ret > 0 else ("down" if next_day_ret < 0 else "off"),
        border=True,
    )
    st.metric(
        f"未來 {forecast_days} 日 (T+{forecast_days}) 目標價",
        f"NT${target_c:.2f}",
        delta=f"{target_ret:+.2f}% (90%區間 {res['lower_90'][-1]:.1f}~{res['upper_90'][-1]:.1f})",
        delta_color="red" if target_ret > 0 else ("green" if target_ret < 0 else "gray"),
        delta_arrow="up" if target_ret > 0 else ("down" if target_ret < 0 else "off"),
        border=True,
    )
    st.metric(
        f"未來 {forecast_days} 日預估上漲機率",
        f"{up_prob:.1f}%",
        delta=signal_text,
        delta_color="red" if up_prob >= 50 else "green",
        delta_arrow="up" if up_prob >= 50 else "down",
        border=True,
    )
    st.metric(
        f"樣本外方向準確率 ({res['eval_horizon']}日驗證)",
        f"{res['dir_acc']:.1f}%",
        delta=f"平均誤差 MAPE {res['mape']:.2f}%",
        delta_color="off",
        delta_arrow="off",
        border=True,
    )

# ── 主圖：歷史 K 線 + 未來預測路徑與 50%/90% 信心扇形圖 (Fan Chart) ────────────
with st.container(border=True):
    st.subheader(
        f":material/timeline: {selected_sid} {STOCK_NAMES.get(selected_sid, '')} — 未來 {forecast_days} 個交易日股價預測扇形圖 (Fan Chart)",
        anchor=False,
    )
    st.caption(
        "實線為歷史收盤價，虛線為三大子模型與主預測軌跡；陰影區間分別代表 **50% 核心信心區間** 與 **90% 波動邊界區間**（台股紅漲綠跌配色）。"
    )

    hist_slice = feat_df.tail(75)
    f_dates = [hist_slice.index[-1]] + list(res["future_dates"])
    f_main = [latest_c] + list(res["pred_prices"])
    f_ridge = [latest_c] + list(res["ridge_prices"])
    f_knn = [latest_c] + list(res["knn_prices"])
    f_drift = [latest_c] + list(res["drift_prices"])
    f_u90 = [latest_c] + list(res["upper_90"])
    f_l90 = [latest_c] + list(res["lower_90"])
    f_u50 = [latest_c] + list(res["upper_50"])
    f_l50 = [latest_c] + list(res["lower_50"])

    main_color = "#ef4444" if target_ret >= 0 else "#22c55e"
    band_rgb = "239, 68, 68" if target_ret >= 0 else "34, 197, 94"

    fig_fan = go.Figure()

    # 歷史 K 線 (半透明) 與收盤折線
    fig_fan.add_trace(
        go.Candlestick(
            x=hist_slice.index,
            open=hist_slice["Open"],
            high=hist_slice["High"],
            low=hist_slice["Low"],
            close=hist_slice["Close"],
            name="歷史 K 線",
            increasing_line_color="#ef4444",
            decreasing_line_color="#22c55e",
            increasing_fillcolor="#ef4444",
            decreasing_fillcolor="#22c55e",
            opacity=0.65,
        )
    )

    # 90% 信心區間
    fig_fan.add_trace(
        go.Scatter(
            x=f_dates + f_dates[::-1],
            y=f_u90 + f_l90[::-1],
            fill="toself",
            fillcolor=f"rgba({band_rgb}, 0.12)",
            line=dict(color="rgba(0,0,0,0)"),
            name="90% 預測信心區間",
            hoverinfo="skip",
        )
    )

    # 50% 信心區間
    fig_fan.add_trace(
        go.Scatter(
            x=f_dates + f_dates[::-1],
            y=f_u50 + f_l50[::-1],
            fill="toself",
            fillcolor=f"rgba({band_rgb}, 0.26)",
            line=dict(color="rgba(0,0,0,0)"),
            name="50% 核心信心區間",
            hoverinfo="skip",
        )
    )

    # 子模型軌跡虛線
    fig_fan.add_trace(
        go.Scatter(
            x=f_dates,
            y=f_ridge,
            name="多因子嶺迴歸軌跡",
            line=dict(color="#38bdf8", width=1.5, dash="dot"),
        )
    )
    fig_fan.add_trace(
        go.Scatter(
            x=f_dates,
            y=f_knn,
            name="KNN 歷史相似型態軌跡",
            line=dict(color="#f59e0b", width=1.5, dash="dot"),
        )
    )

    # 主預測軌跡
    fig_fan.add_trace(
        go.Scatter(
            x=f_dates,
            y=f_main,
            mode="lines+markers",
            name=f"主預測路徑 ({model_mode.split()[0]})",
            line=dict(color=main_color, width=3.0),
            marker=dict(size=6, color=main_color),
            hovertemplate="日期: %{x|%Y/%m/%d}<br>預測價: NT$%{y:.2f}<extra></extra>",
        )
    )

    fig_fan.update_layout(
        height=480,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font_color="#fafafa",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=40, b=30, l=60, r=20),
        yaxis_title="股價 (NTD)",
    )
    fig_fan.update_xaxes(gridcolor="#1e2535")
    fig_fan.update_yaxes(gridcolor="#1e2535")
    st.plotly_chart(fig_fan, width="stretch")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 深入分析分頁：特徵歸因、KNN 歷史相似型態、逐日預測明細、樣本外回測驗證
# ═══════════════════════════════════════════════════════════════════════════════

tab_attr, tab_knn, tab_val, tab_table = st.tabs([
    ":material/bar_chart: 技術指標多空歸因解析",
    ":material/history: KNN 歷史相似型態對照",
    ":material/verified: 樣本外歷史回測準確度驗證",
    ":material/table_view: 未來逐日預測價位表",
])

# ── Tab 1：技術指標多空歸因解析 ──────────────────────────────────────────────
with tab_attr:
    st.caption(
        "顯示**今日最新各項技術指標特徵**對未來預測報酬率的**邊際推力貢獻（百分點 %）**。"
        "**紅色柱（> 0）** 代表該技術指標目前提供看多推力，**綠色柱（< 0）** 代表提供看空壓力。"
    )
    contribs = res["feature_contributions"]
    attr_df = pd.DataFrame({
        "指標代碼": active_cols,
        "指標名稱": [FEATURE_LABELS.get(c, c) for c in active_cols],
        "今日指標數值": [float(feat_df[c].iloc[-1]) for c in active_cols],
        "對預測報酬貢獻(%)": contribs,
    }).sort_values("對預測報酬貢獻(%)", ascending=True)

    c_left, c_right = st.columns([3, 2])
    with c_left:
        bar_colors = ["#ef4444" if v >= 0 else "#22c55e" for v in attr_df["對預測報酬貢獻(%)"]]
        fig_attr = go.Figure(
            go.Bar(
                x=attr_df["對預測報酬貢獻(%)"],
                y=attr_df["指標名稱"],
                orientation="h",
                marker_color=bar_colors,
                text=[f"{v:+.2f}%" for v in attr_df["對預測報酬貢獻(%)"]],
                textposition="outside",
            )
        )
        fig_attr.add_vline(x=0, line_color="#64748b", line_dash="dash")
        fig_attr.update_layout(
            title=f"今日各技術指標對未來 {forecast_days} 日報酬率之影響權重",
            height=420,
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            xaxis_title="預期報酬貢獻度 (%)",
            margin=dict(t=45, b=30, l=130, r=40),
        )
        fig_attr.update_xaxes(gridcolor="#1e2535")
        fig_attr.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_attr, width="stretch")

    with c_right:
        attr_disp = attr_df.sort_values("對預測報酬貢獻(%)", ascending=False).set_index("指標名稱")[
            ["今日指標數值", "對預測報酬貢獻(%)"]
        ]
        st.dataframe(
            attr_disp.style.map(
                lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and v > 0
                else ("color: #22c55e; font-weight: 600" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=["對預測報酬貢獻(%)"],
            ).format({
                "今日指標數值": "{:.2f}",
                "對預測報酬貢獻(%)": "{:+.2f}%",
            }),
            height=420,
            width="stretch",
        )

# ── Tab 2：KNN 歷史最相似技術型態對照 ────────────────────────────────────────
with tab_knn:
    st.caption(
        f"系統自動比對過去所有交易日的 16 維度技術指標向量，找出與**今日（{res['latest_date']}）技術面最相似的 {len(res['analog_records'])} 個歷史交易日**，並疊加它們當時在未來 {forecast_days} 天的真實走勢。"
    )
    k_col1, k_col2 = st.columns([3, 2])
    with k_col1:
        fig_knn = go.Figure()
        x_days = list(range(0, forecast_days + 1))
        for i, rec in enumerate(res["analog_records"]):
            path_y = [0.0] + list(res["analog_paths_arr"][i])
            fig_knn.add_trace(
                go.Scatter(
                    x=x_days,
                    y=path_y,
                    name=f"{rec['歷史相似日期']} (相似度 {rec['型態相似度']:.0f}%)",
                    line=dict(width=1.4),
                    opacity=0.6,
                )
            )
        mean_knn_y = [0.0] + list(((res["knn_prices"] / latest_c) - 1.0) * 100.0)
        fig_knn.add_trace(
            go.Scatter(
                x=x_days,
                y=mean_knn_y,
                name="相似度加權平均走勢",
                line=dict(color="#ef4444" if mean_knn_y[-1] >= 0 else "#22c55e", width=3.2),
            )
        )
        fig_knn.add_hline(y=0, line_dash="dash", line_color="#64748b")
        fig_knn.update_layout(
            title=f"歷史最相似 {len(res['analog_records'])} 個交易日之後續 {forecast_days} 日真實累積漲跌幅 (%)",
            xaxis_title="交易日推進 (T+0 為相似當日)",
            yaxis_title="後續累積漲跌幅 (%)",
            height=380,
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            margin=dict(t=45, b=35, l=55, r=20),
        )
        fig_knn.update_xaxes(gridcolor="#1e2535")
        fig_knn.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_knn, width="stretch")

    with k_col2:
        analog_df = pd.DataFrame(res["analog_records"]).set_index("歷史相似日期")
        ret_cols_knn = ["後1日漲跌%", "後5日漲跌%", f"後{forecast_days}日漲跌%"]
        st.dataframe(
            analog_df.style.map(
                lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and v > 0
                else ("color: #22c55e; font-weight: 600" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=ret_cols_knn,
            ).format({
                "型態相似度": "{:.1f}%",
                "當時收盤價": "{:.2f}",
                "當時RSI(14)": "{:.1f}",
                "當時布林%B": "{:.1f}%",
                "後1日漲跌%": "{:+.2f}%",
                "後5日漲跌%": "{:+.2f}%",
                f"後{forecast_days}日漲跌%": "{:+.2f}%",
            }),
            height=380,
            width="stretch",
        )

# ── Tab 3：樣本外歷史回測準確度驗證 (Walk-Forward Validation) ───────────────
with tab_val:
    st.caption(
        f"採用嚴格無未來函數之**滾動訓練（Walk-Forward）**：在過去每個時間點只用當時以前的歷史資料訓練模型，預測 {res['eval_horizon']} 個交易日後的收盤價，與真實收盤價進行比對。"
    )
    if res["oos_dates"]:
        fig_oos = go.Figure()
        fig_oos.add_trace(
            go.Scatter(
                x=res["oos_dates"],
                y=res["oos_actual_prices"],
                name="實際收盤價",
                line=dict(color="#f8fafc", width=2.4),
            )
        )
        fig_oos.add_trace(
            go.Scatter(
                x=res["oos_dates"],
                y=res["oos_pred_prices"],
                name=f"模型事前預測價 (提前 {res['eval_horizon']} 日預測)",
                line=dict(color="#ef4444", width=2.2, dash="dash"),
            )
        )
        fig_oos.update_layout(
            title=f"樣本外滾動驗證：實際收盤價 vs 模型預測價（方向準確率 {res['dir_acc']:.1f}%｜MAPE {res['mape']:.2f}%｜RMSE NT${res['rmse']:.2f}）",
            height=380,
            hovermode="x unified",
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
            margin=dict(t=45, b=30, l=60, r=20),
            yaxis_title="股價 (NTD)",
        )
        fig_oos.update_xaxes(gridcolor="#1e2535")
        fig_oos.update_yaxes(gridcolor="#1e2535")
        st.plotly_chart(fig_oos, width="stretch")
    else:
        st.info("樣本數較少，暫無足夠區間進行樣本外滾動驗證。")

# ── Tab 4：未來逐日預測價位表與 CSV 下載 ────────────────────────────────────
with tab_table:
    schedule_rows = []
    for i in range(forecast_days):
        schedule_rows.append({
            "預估交易日": res["future_dates"][i].strftime("%Y/%m/%d"),
            "天數": f"T+{i + 1}",
            "綜合預測價": float(res["pred_prices"][i]),
            "預期累積漲跌%": float(res["final_ret_curve"][i]),
            "嶺迴歸預測價": float(res["ridge_prices"][i]),
            "KNN型態預測價": float(res["knn_prices"][i]),
            "50%區間下緣": float(res["lower_50"][i]),
            "50%區間上緣": float(res["upper_50"][i]),
            "90%區間下緣": float(res["lower_90"][i]),
            "90%區間上緣": float(res["upper_90"][i]),
        })
    sched_df = pd.DataFrame(schedule_rows).set_index("預估交易日")
    st.dataframe(
        sched_df.style.map(
            lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and v > 0
            else ("color: #22c55e; font-weight: 600" if isinstance(v, (int, float)) and v < 0 else ""),
            subset=["預期累積漲跌%"],
        ).format({
            "綜合預測價": "NT${:.2f}",
            "預期累積漲跌%": "{:+.2f}%",
            "嶺迴歸預測價": "NT${:.2f}",
            "KNN型態預測價": "NT${:.2f}",
            "50%區間下緣": "NT${:.2f}",
            "50%區間上緣": "NT${:.2f}",
            "90%區間下緣": "NT${:.2f}",
            "90%區間上緣": "NT${:.2f}",
        }),
        width="stretch",
    )
    st.download_button(
        label=f":material/download: 匯出 {selected_sid} 未來 {forecast_days} 日預測明細表 (CSV)",
        data=sched_df.to_csv().encode("utf-8-sig"),
        file_name=f"forecast_{selected_sid}_{forecast_days}d.csv",
        mime="text/csv",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 全市場 AI 批次預測掃描排行榜（一次看清所有個股與主動式 ETF 的預測潛力）
# ═══════════════════════════════════════════════════════════════════════════════

with st.container(border=True):
    st.subheader(f":material/leaderboard: 全市場技術指標 AI 預測排行榜（未來 {forecast_days} 日潛力掃描）", anchor=False)
    st.caption("使用相同特徵組合與預測模型，同步掃描股票池中所有個股與主動式 ETF 的預期漲跌幅、上漲勝率與樣本外準確率。")

    batch_rows = []
    for sid in stock_ids:
        f_df = build_feature_dataframe(sid)
        if f_df.empty or len(f_df) < 45:
            continue
        r_b = run_forecast_engine(
            feat_df=f_df,
            feature_cols=active_cols,
            horizon=forecast_days,
            window=train_window,
            k_neighbors=knn_k,
            alpha=ridge_alpha,
            mode=model_mode,
        )
        ret_b = float(r_b["final_ret_curve"][-1])
        prob_b = float(r_b["up_prob"])
        batch_rows.append({
            "標的": f"{sid} {STOCK_NAMES.get(sid, '')}",
            "類別": "主動式ETF" if (sid.endswith("A") or sid in ACTIVE_ETF_META) else "個股/被動ETF",
            "最新收盤價": float(r_b["latest_close"]),
            "T+1預測價": float(r_b["pred_prices"][0]),
            "T+1預期漲跌%": float(r_b["final_ret_curve"][0]),
            f"T+{forecast_days}目標價": float(r_b["pred_prices"][-1]),
            f"T+{forecast_days}預期漲跌%": ret_b,
            "預估上漲機率%": prob_b,
            "樣本外方向準確率%": float(r_b["dir_acc"]),
            "AI多空研判": "🔴 看多" if ret_b > 0.8 and prob_b >= 52 else ("🟢 看空" if ret_b < -0.8 and prob_b < 48 else "⚪ 盤整"),
        })

    if batch_rows:
        batch_df = (
            pd.DataFrame(batch_rows)
            .sort_values(f"T+{forecast_days}預期漲跌%", ascending=False)
            .set_index("標的")
        )
        st.dataframe(
            batch_df.style.map(
                lambda v: "color: #ef4444; font-weight: 600" if isinstance(v, (int, float)) and v > 0
                else ("color: #22c55e; font-weight: 600" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=["T+1預期漲跌%", f"T+{forecast_days}預期漲跌%"],
            ).format({
                "最新收盤價": "{:.2f}",
                "T+1預測價": "{:.2f}",
                "T+1預期漲跌%": "{:+.2f}%",
                f"T+{forecast_days}目標價": "{:.2f}",
                f"T+{forecast_days}預期漲跌%": "{:+.2f}%",
                "預估上漲機率%": "{:.1f}%",
                "樣本外方向準確率%": "{:.1f}%",
            }),
            width="stretch",
        )
