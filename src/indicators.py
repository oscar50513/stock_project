"""共用技術指標計算模組 — 所有頁面共享"""

import glob
import os

import numpy as np
import pandas as pd
import streamlit as st

# ── 股票名稱對照表 ─────────────────────────────────────────────────────────────
STOCK_NAMES = {
    "0050": "元大台灣50",
    "0056": "元大高股息",
    "2317": "鴻海",
    "2330": "台積電",
    "2610": "華航",
    "2618": "長榮航",
}

DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_stock_ids() -> list[str]:
    """取得所有可用的股票代碼清單。"""
    csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "[0-9]*.csv")))
    return [os.path.basename(f).replace(".csv", "") for f in csv_files]


@st.cache_data(ttl="1h")
def load_stock(stock_id: str) -> pd.DataFrame:
    """載入股票 CSV 並做型別轉換。"""
    path = os.path.join(DATA_DIR, f"{stock_id}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df.sort_index(inplace=True)
    return df


@st.cache_data
def calc_ma(df: pd.DataFrame, windows: list[int] = None) -> pd.DataFrame:
    """計算移動平均線。"""
    if windows is None:
        windows = [5, 10, 20, 60]
    res = df.copy()
    for w in windows:
        res[f"MA{w}"] = df["Close"].rolling(w).mean()
    return res


@st.cache_data
def calc_bbands(df: pd.DataFrame, period: int = 20, std_num: float = 2.0) -> pd.DataFrame:
    """計算雙布林通道及相關指標。"""
    res = df.copy()
    res["b_mid"]     = df["Close"].rolling(period).mean()
    std              = df["Close"].rolling(period).std(ddof=0)
    res["b_up"]      = res["b_mid"] + std * std_num
    res["b_up_long"] = res["b_mid"] + std * 3
    res["b_low"]     = res["b_mid"] - std * std_num
    res["b_low_long"]= res["b_mid"] - std * 3
    b_slope, ma_slope, b_width = [np.nan], [np.nan], [np.nan]
    t = res.index
    for i in range(1, len(res)):
        b_slope.append(
            (res.loc[t[i], "b_up"] - res.loc[t[i-1], "b_up"]) / res.loc[t[i-1], "b_up"] * 100
        )
        ma_slope.append((res.loc[t[i], "b_mid"] / res.loc[t[i-1], "b_mid"] - 1) * 100)
        b_width.append((res.loc[t[i], "b_up"] / res.loc[t[i], "b_low"] - 1) * 100)
    res["bband_slope"] = b_slope
    res["bband_width"] = b_width
    res["mid_slope"]   = ma_slope
    return res


@st.cache_data
def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI 指標計算。"""
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return 100 - 100 / (1 + rs)


@st.cache_data
def calc_macd(df: pd.DataFrame) -> pd.DataFrame:
    """MACD 指標（EMA12 - EMA26，Signal EMA9）。"""
    exp12  = df["Close"].ewm(span=12, adjust=False).mean()
    exp26  = df["Close"].ewm(span=26, adjust=False).mean()
    macd   = exp12 - exp26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return pd.DataFrame({"MACD": macd, "Signal": signal, "Histogram": hist}, index=df.index)


@st.cache_data
def calc_kd(df: pd.DataFrame, period: int = 9) -> pd.DataFrame:
    """KD 隨機指標 (Stochastic Oscillator)。"""
    low_min  = df["Low"].rolling(period).min()
    high_max = df["High"].rolling(period).max()
    rsv = (df["Close"] - low_min) / (high_max - low_min + 1e-9) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    return pd.DataFrame({"K": k, "D": d}, index=df.index)


def get_horizon_slice(df_full: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """依快速區間切片。"""
    horizon_map = {
        "1個月": 21, "3個月": 63, "6個月": 126,
        "1年": 252, "3年": 756, "全部": len(df_full),
    }
    n = horizon_map.get(horizon or "1年", 252)
    return df_full.iloc[-n:]
