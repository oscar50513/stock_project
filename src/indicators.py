"""共用技術指標計算模組 — 所有頁面共享"""

import glob
import os

import numpy as np
import pandas as pd
import streamlit as st

# ── 股票與主動式 ETF 名稱對照表 ──────────────────────────────────────────────
STOCK_NAMES = {
    "0050": "元大台灣50",
    "0056": "元大高股息",
    "00830": "國泰費城半導體",
    "2317": "鴻海",
    "2330": "台積電",
    "2610": "華航",
    "2618": "長榮航",
    # 主動式 ETF
    "00980A": "主動野村臺灣優選",
    "00981A": "主動統一台股增長",
    "00982A": "主動群益台灣強棒",
    "00983A": "主動中信ARK創新",
    "00984A": "主動安聯台灣高息",
    "00985A": "主動野村台灣50",
    "00986A": "主動台新龍頭成長",
    "00987A": "主動台新優勢成長",
    "00988A": "主動統一全球創新",
    "00989A": "主動摩根美國科技",
    "00990A": "主動元大AI新經濟",
    "00991A": "主動復華未來50",
    "00992A": "主動群益科技創新",
    "00403A": "主動統一升級50",
}

# ── 主動式 ETF 詳細檔案庫 ────────────────────────────────────────────────────
ACTIVE_ETF_META = {
    # 主題一：台股市值／高息代表型
    "00980A": {
        "name": "主動野村臺灣優選",
        "theme": "台股市值／高息型",
        "issuer": "野村投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "台灣首檔掛牌主動式ETF，結合量化因子模型與質化基本面研究，動態挑選兼具成長動能與合理評價之台股標的。",
    },
    "00981A": {
        "name": "主動統一台股增長",
        "theme": "台股市值／高息型",
        "issuer": "統一投信",
        "dividend": "年配息",
        "benchmark": "0050",
        "strategy": "鎖定台股大型權值與高成長核心企業（AI、先進半導體供應鏈），由經理團隊靈活調整持股權重追求超額報酬。",
    },
    "00984A": {
        "name": "主動安聯台灣高息",
        "theme": "台股市值／高息型",
        "issuer": "安聯投信",
        "dividend": "季配息",
        "benchmark": "0056",
        "strategy": "結合主動選股與高股息策略，跳脫傳統純殖利率排序，兼顧企業獲利成長動能與穩定股息現金流。",
    },
    "00985A": {
        "name": "主動野村台灣50",
        "theme": "台股市值／高息型",
        "issuer": "野村投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "以台股市值前50大企業為核心母體進行主動增強配置，透過強弱勢股動態加減碼追求超越台灣50指數表現。",
    },
    # 主題二：台股升級／科技成長主題型
    "00403A": {
        "name": "主動統一升級50",
        "theme": "台股升級／科技成長型",
        "issuer": "統一投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "聚焦台股市值前200大企業，以前50大為核心持倉，並從第51～200名中「汰弱增強」納入高成長動能潛力股。",
    },
    "00991A": {
        "name": "主動復華未來50",
        "theme": "台股升級／科技成長型",
        "issuer": "復華投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "從台股市值前150大企業中，精選50檔具產業前瞻性與獲利爆發力的標的，提前布局「未來的台灣50」。",
    },
    "00982A": {
        "name": "主動群益台灣強棒",
        "theme": "台股升級／科技成長型",
        "issuer": "群益投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "聚焦台股強勢主流類股與科技成長動能，透過經理人積極換股操作應對產業快速輪動。",
    },
    "00986A": {
        "name": "主動台新龍頭成長",
        "theme": "台股升級／科技成長型",
        "issuer": "台新投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "精選台灣各關鍵產業龍頭與具競爭護城河之成長型企業，隨景氣循環動態調整配置。",
    },
    "00987A": {
        "name": "主動台新優勢成長",
        "theme": "台股升級／科技成長型",
        "issuer": "台新投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "結合基本面研究與量化篩選，鎖定台股具技術領先優勢與營收加速成長之上市櫃公司。",
    },
    "00992A": {
        "name": "主動群益科技創新",
        "theme": "台股升級／科技成長型",
        "issuer": "群益投信",
        "dividend": "季配息",
        "benchmark": "0050",
        "strategy": "高度聚焦台灣半導體、AI伺服器、高速運算及先進電子零組件供應鏈，主動汰弱留強。",
    },
    # 主題三：跨國／全球創新主題型
    "00988A": {
        "name": "主動統一全球創新",
        "theme": "跨國／全球創新主題型",
        "issuer": "統一投信",
        "dividend": "年配息",
        "benchmark": "00830",
        "strategy": "採「創新金三角策略」（顛覆式、漸進式、擴展式），全球佈局AI軟硬體、能源基建、光通訊與航太科技龍頭。",
    },
    "00983A": {
        "name": "主動中信ARK創新",
        "theme": "跨國／全球創新主題型",
        "issuer": "中信投信",
        "dividend": "年配息",
        "benchmark": "00830",
        "strategy": "與美國方舟投資（ARK Invest）合作，聚焦AI、機器人、基因定序、能源儲存與區塊鏈等顛覆式創新企業。",
    },
    "00990A": {
        "name": "主動元大AI新經濟",
        "theme": "跨國／全球創新主題型",
        "issuer": "元大投信",
        "dividend": "年配息",
        "benchmark": "00830",
        "strategy": "跨國網羅全球AI晶片、雲端算力中心、邊緣運算與AI軟體應用上中下游核心大廠，動態捕捉AI成長紅利。",
    },
    "00989A": {
        "name": "主動摩根美國科技",
        "theme": "跨國／全球創新主題型",
        "issuer": "摩根投信",
        "dividend": "年配息",
        "benchmark": "00830",
        "strategy": "由摩根美國科技研究團隊操盤，深度挖掘美國最具全球統治力與創新動能的科技巨頭與新星。",
    },
}

# ── 主動式 ETF 與基準指數前十大核心持股（2026/10 投信公開快照）────────────────
ETF_HOLDINGS: dict[str, list[dict]] = {
    "00980A": [
        {"code": "2330", "name": "台積電",   "sector": "半導體",     "weight": 9.73},
        {"code": "2454", "name": "聯發科",   "sector": "IC設計",     "weight": 5.65},
        {"code": "2383", "name": "台光電",   "sector": "PCB/CCL",    "weight": 4.58},
        {"code": "2059", "name": "川湖",     "sector": "AI伺服器導軌", "weight": 4.20},
        {"code": "1303", "name": "南亞",     "sector": "電子材料/塑化", "weight": 3.96},
        {"code": "3653", "name": "健策",     "sector": "AI散熱",     "weight": 3.74},
        {"code": "3037", "name": "欣興",     "sector": "ABF載板",    "weight": 3.55},
        {"code": "6669", "name": "緯穎",     "sector": "AI伺服器",   "weight": 3.40},
        {"code": "2308", "name": "台達電",   "sector": "電源與散熱",  "weight": 3.25},
        {"code": "3017", "name": "奇鋐",     "sector": "AI散熱",     "weight": 3.12},
    ],
    "00981A": [
        {"code": "2330", "name": "台積電",   "sector": "半導體",     "weight": 10.84},
        {"code": "2383", "name": "台光電",   "sector": "PCB/CCL",    "weight": 8.21},
        {"code": "2454", "name": "聯發科",   "sector": "IC設計",     "weight": 8.03},
        {"code": "3037", "name": "欣興",     "sector": "ABF載板",    "weight": 7.76},
        {"code": "3017", "name": "奇鋐",     "sector": "AI散熱",     "weight": 7.68},
        {"code": "3653", "name": "健策",     "sector": "AI散熱",     "weight": 6.19},
        {"code": "2327", "name": "國巨",     "sector": "被動元件",   "weight": 4.90},
        {"code": "6223", "name": "旺矽",     "sector": "半導體測試",  "weight": 4.79},
        {"code": "2345", "name": "智邦",     "sector": "高速網通",   "weight": 4.56},
        {"code": "2308", "name": "台達電",   "sector": "電源與散熱",  "weight": 4.51},
    ],
    "00982A": [
        {"code": "2330", "name": "台積電",   "sector": "半導體",     "weight": 7.87},
        {"code": "2454", "name": "聯發科",   "sector": "IC設計",     "weight": 6.59},
        {"code": "3105", "name": "穩懋",     "sector": "化合物半導體", "weight": 6.02},
        {"code": "6139", "name": "亞翔",     "sector": "無塵室廠務",  "weight": 5.34},
        {"code": "6669", "name": "緯穎",     "sector": "AI伺服器",   "weight": 3.95},
        {"code": "6531", "name": "愛普*",    "sector": "記憶體IP",   "weight": 3.92},
        {"code": "4958", "name": "臻鼎-KY",  "sector": "PCB/CCL",    "weight": 3.70},
        {"code": "3491", "name": "昇達科",   "sector": "低軌衛星",   "weight": 3.62},
        {"code": "2360", "name": "致茂",     "sector": "半導體測試",  "weight": 3.56},
        {"code": "3008", "name": "大立光",   "sector": "光學鏡頭",   "weight": 3.38},
    ],
    "00984A": [
        {"code": "2330", "name": "台積電",   "sector": "半導體",     "weight": 4.27},
        {"code": "2881", "name": "富邦金",   "sector": "金融保險",   "weight": 4.24},
        {"code": "3017", "name": "奇鋐",     "sector": "AI散熱",     "weight": 4.21},
        {"code": "6505", "name": "台塑化",   "sector": "塑化能源",   "weight": 3.49},
        {"code": "2887", "name": "台新新光金", "sector": "金融保險",  "weight": 3.45},
        {"code": "2885", "name": "元大金",   "sector": "金融保險",   "weight": 3.26},
        {"code": "2882", "name": "國泰金",   "sector": "金融保險",   "weight": 3.23},
        {"code": "1303", "name": "南亞",     "sector": "電子材料/塑化", "weight": 3.09},
        {"code": "2395", "name": "研華",     "sector": "工業電腦",   "weight": 2.58},
        {"code": "6187", "name": "萬潤",     "sector": "先進封裝設備", "weight": 2.47},
    ],
    "00403A": [
        {"code": "2330", "name": "台積電",   "sector": "半導體",     "weight": 14.34},
        {"code": "3653", "name": "健策",     "sector": "AI散熱",     "weight": 5.76},
        {"code": "3037", "name": "欣興",     "sector": "ABF載板",    "weight": 5.74},
        {"code": "2383", "name": "台光電",   "sector": "PCB/CCL",    "weight": 5.47},
        {"code": "2454", "name": "聯發科",   "sector": "IC設計",     "weight": 5.40},
        {"code": "3017", "name": "奇鋐",     "sector": "AI散熱",     "weight": 4.94},
        {"code": "2327", "name": "國巨",     "sector": "被動元件",   "weight": 3.85},
        {"code": "3443", "name": "創意",     "sector": "ASIC設計",   "weight": 3.83},
        {"code": "6223", "name": "旺矽",     "sector": "半導體測試",  "weight": 3.76},
        {"code": "2308", "name": "台達電",   "sector": "電源與散熱",  "weight": 3.61},
    ],
    "00991A": [
        {"code": "2330", "name": "台積電",   "sector": "半導體",     "weight": 14.61},
        {"code": "2383", "name": "台光電",   "sector": "PCB/CCL",    "weight": 9.85},
        {"code": "3037", "name": "欣興",     "sector": "ABF載板",    "weight": 8.20},
        {"code": "2408", "name": "南亞科",   "sector": "記憶體",     "weight": 7.33},
        {"code": "8046", "name": "南電",     "sector": "ABF載板",    "weight": 6.52},
        {"code": "2059", "name": "川湖",     "sector": "AI伺服器導軌", "weight": 6.51},
        {"code": "3189", "name": "景碩",     "sector": "ABF載板",    "weight": 6.45},
        {"code": "2454", "name": "聯發科",   "sector": "IC設計",     "weight": 6.23},
        {"code": "3017", "name": "奇鋐",     "sector": "AI散熱",     "weight": 5.50},
        {"code": "2327", "name": "國巨",     "sector": "被動元件",   "weight": 4.74},
    ],
    "00988A": [
        {"code": "LITE",   "name": "Lumentum (光通訊)", "sector": "光通訊/矽光子", "weight": 7.34},
        {"code": "BE",     "name": "Bloom Energy",      "sector": "AI電力能源",   "weight": 6.84},
        {"code": "3037",   "name": "欣興",              "sector": "ABF載板",      "weight": 6.34},
        {"code": "SPCX",   "name": "SpaceX (太空探索)",  "sector": "太空與衛星",   "weight": 5.58},
        {"code": "009150", "name": "三星電機",          "sector": "被動元件/載板", "weight": 4.85},
        {"code": "6981",   "name": "村田製作所",        "sector": "被動元件",     "weight": 4.22},
        {"code": "PANW",   "name": "Palo Alto Networks","sector": "資安軟體",     "weight": 4.14},
        {"code": "NVDA",   "name": "NVIDIA (輝達)",     "sector": "AI晶片",       "weight": 4.08},
        {"code": "PLTR",   "name": "Palantir",          "sector": "AI大數據軟體", "weight": 3.57},
        {"code": "3017",   "name": "奇鋐",              "sector": "AI散熱",       "weight": 3.35},
    ],
    "00983A": [
        {"code": "TSLA", "name": "Tesla (特斯拉)",    "sector": "自駕與機器人", "weight": 9.01},
        {"code": "SPCX", "name": "SpaceX (太空探索)", "sector": "太空與衛星",   "weight": 6.98},
        {"code": "TEM",  "name": "Tempus AI",         "sector": "AI精準醫療",   "weight": 5.46},
        {"code": "SHOP", "name": "Shopify",           "sector": "AI電商平台",   "weight": 5.14},
        {"code": "CRCL", "name": "Circle Internet",   "sector": "區塊鏈金融",   "weight": 5.00},
        {"code": "COIN", "name": "Coinbase",          "sector": "區塊鏈金融",   "weight": 4.62},
        {"code": "HOOD", "name": "Robinhood",         "sector": "金融科技",     "weight": 3.95},
        {"code": "PLTR", "name": "Palantir",          "sector": "AI大數據軟體", "weight": 3.86},
        {"code": "TWST", "name": "Twist Bioscience",  "sector": "基因定序",     "weight": 3.80},
        {"code": "CRSP", "name": "CRISPR Therapeutics","sector": "基因編輯",    "weight": 3.74},
    ],
    "00990A": [
        {"code": "LITE", "name": "Lumentum (光通訊)", "sector": "光通訊/矽光子", "weight": 7.75},
        {"code": "META", "name": "Meta Platforms",    "sector": "AI雲端與社群", "weight": 5.58},
        {"code": "BE",   "name": "Bloom Energy",      "sector": "AI電力能源",   "weight": 5.62},
        {"code": "NVDA", "name": "NVIDIA (輝達)",     "sector": "AI晶片",       "weight": 4.76},
        {"code": "AMD",  "name": "AMD (超微)",        "sector": "AI晶片",       "weight": 4.30},
        {"code": "MSFT", "name": "Microsoft (微軟)",  "sector": "AI雲端與軟體", "weight": 4.00},
        {"code": "SPCX", "name": "SpaceX (太空探索)", "sector": "太空與衛星",   "weight": 3.54},
        {"code": "PLTR", "name": "Palantir",          "sector": "AI大數據軟體", "weight": 3.45},
        {"code": "SNOW", "name": "Snowflake",         "sector": "AI雲端資料",   "weight": 3.19},
        {"code": "SHOP", "name": "Shopify",           "sector": "AI電商平台",   "weight": 3.18},
    ],
    # 被動式基準 ETF 前十大持股（供重疊度比較）
    "0050": [
        {"code": "2330", "name": "台積電",   "sector": "半導體",     "weight": 56.80},
        {"code": "2317", "name": "鴻海",     "sector": "AI伺服器",   "weight": 5.10},
        {"code": "2454", "name": "聯發科",   "sector": "IC設計",     "weight": 4.35},
        {"code": "2308", "name": "台達電",   "sector": "電源與散熱",  "weight": 2.15},
        {"code": "2382", "name": "廣達",     "sector": "AI伺服器",   "weight": 1.95},
        {"code": "2881", "name": "富邦金",   "sector": "金融保險",   "weight": 1.65},
        {"code": "2891", "name": "中信金",   "sector": "金融保險",   "weight": 1.50},
        {"code": "2882", "name": "國泰金",   "sector": "金融保險",   "weight": 1.42},
        {"code": "3711", "name": "日月光投控","sector": "半導體封測", "weight": 1.30},
        {"code": "2303", "name": "聯電",     "sector": "半導體",     "weight": 1.20},
    ],
    "0056": [
        {"code": "2303", "name": "聯電",     "sector": "半導體",     "weight": 4.10},
        {"code": "2603", "name": "長榮",     "sector": "航運",       "weight": 3.95},
        {"code": "2454", "name": "聯發科",   "sector": "IC設計",     "weight": 3.80},
        {"code": "2891", "name": "中信金",   "sector": "金融保險",   "weight": 3.65},
        {"code": "2885", "name": "元大金",   "sector": "金融保險",   "weight": 3.50},
        {"code": "2382", "name": "廣達",     "sector": "AI伺服器",   "weight": 3.40},
        {"code": "2357", "name": "華碩",     "sector": "AI PC/品牌", "weight": 3.25},
        {"code": "3034", "name": "聯詠",     "sector": "IC設計",     "weight": 3.10},
        {"code": "2886", "name": "兆豐金",   "sector": "金融保險",   "weight": 2.95},
        {"code": "1101", "name": "台泥",     "sector": "傳產原物料",  "weight": 2.70},
    ],
    "00830": [
        {"code": "NVDA", "name": "NVIDIA (輝達)",     "sector": "AI晶片",     "weight": 11.20},
        {"code": "AVGO", "name": "Broadcom (博通)",   "sector": "AI晶片/網通", "weight": 9.80},
        {"code": "AMD",  "name": "AMD (超微)",        "sector": "AI晶片",     "weight": 7.60},
        {"code": "2330", "name": "台積電 ADR",        "sector": "半導體",     "weight": 4.90},
        {"code": "QCOM", "name": "Qualcomm (高通)",   "sector": "IC設計",     "weight": 4.65},
        {"code": "ASML", "name": "ASML (艾司摩爾)",   "sector": "半導體設備",  "weight": 4.50},
        {"code": "AMAT", "name": "Applied Materials", "sector": "半導體設備",  "weight": 4.35},
        {"code": "MU",   "name": "Micron (美光)",     "sector": "記憶體",     "weight": 4.20},
        {"code": "TXN",  "name": "Texas Instruments", "sector": "類比IC",     "weight": 4.10},
        {"code": "LRCX", "name": "Lam Research",      "sector": "半導體設備",  "weight": 3.90},
    ],
}

DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_stock_ids() -> list[str]:
    """取得所有可用的股票與 ETF 代碼清單。"""
    csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "[0-9]*.csv")))
    return [os.path.basename(f).replace(".csv", "") for f in csv_files]


def get_active_etf_ids() -> list[str]:
    """取得目前已下載 CSV 的主動式 ETF 代碼清單（代號含 A 或在 ACTIVE_ETF_META 中）。"""
    all_ids = get_stock_ids()
    return [sid for sid in all_ids if sid.endswith("A") or sid in ACTIVE_ETF_META]


def download_stock_csv(stock_id: str) -> tuple[bool, str]:
    """從 yfinance 下載或更新指定代號的完整歷史資料並存成 CSV。"""
    import yfinance as yf

    sid = stock_id.strip().upper().replace(".TW", "").replace(".TWO", "")
    if not sid:
        return False, "代號不可為空"

    df_new = pd.DataFrame()
    used_ticker = ""
    for suffix in [".TW", ".TWO", ""]:
        ticker = f"{sid}{suffix}"
        try:
            tmp = yf.download(ticker, period="max", progress=False)
            if tmp is not None and not tmp.empty:
                df_new = tmp
                used_ticker = ticker
                break
        except Exception:
            continue

    if df_new.empty:
        return False, f"在 Yahoo Finance 找不到 {sid}（已嘗試 .TW / .TWO）的股價資料"

    df_new = df_new.reset_index()
    if isinstance(df_new.columns, pd.MultiIndex):
        df_new.columns = df_new.columns.get_level_values(0)

    df_new = df_new[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    df_new["Date"] = pd.to_datetime(df_new["Date"]).dt.strftime("%Y/%m/%d")
    for col in ["Open", "High", "Low", "Close"]:
        df_new[col] = df_new[col].astype(float).round(2)
    df_new["Volume"] = (df_new["Volume"].fillna(0) / 1000).astype(int)

    csv_path = os.path.join(DATA_DIR, f"{sid}.csv")
    df_new.to_csv(csv_path, index=False)
    load_stock.clear()
    return True, f"成功下載 {sid} ({used_ticker}) 共 {len(df_new)} 筆資料（{df_new['Date'].iloc[0]} ～ {df_new['Date'].iloc[-1]}）"



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
    df = df[~df.index.duplicated(keep="last")]
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
