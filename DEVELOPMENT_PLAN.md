# StockRadar 下一階段開發計劃書（交辦給 Gemini Flash 執行規格書）

> **文件目的**：本開發計劃書定義了 `StockRadar（台股與主動式 ETF 量化分析工作站）` 的下一階段（Phase 2）功能升級與程式碼品質優化任務。
> **執行模型**：Gemini Flash（請嚴格依照本規格書之檔案路徑、函式介面、台股配色規範與驗收指令逐步實作）。
> **審查機制**：全部任務完成後，將由主審查 Agent 執行自動化測試（`AppTest`）與程式碼品質審查（Code Review）。

---

## ⚠️ 全局開發鐵律（Gemini Flash 必讀約束）

在修改任何檔案前，**必須**嚴格遵守以下 6 點專案規範（違反任一項將無法通過審查）：

1. **Python 虛擬環境**：所有指令與測試必須使用專案目錄下的 `.venv/bin/python`（Python 3.14），不可使用系統預設 `python`。
2. **台股「紅漲綠跌」視覺鐵律**：
   - 上漲 / 獲利 / 偏多 / 正超額報酬：必須使用 **紅色（`#ef4444` 或 `delta_color="red"` / `delta_arrow="up"`）**。
   - 下跌 / 虧損 / 偏空 / 負超額報酬：必須使用 **綠色（`#22c55e` 或 `delta_color="green"` / `delta_arrow="down"`）**。
   - 熱力圖（Heatmap）若代表報酬率或績效：低值到高值必須使用綠到紅（例如 `RdYlGn_r`），不可使用美股預設 `RdYlGn`。
3. **Streamlit 1.63 新版 API 規範**：
   - **禁止使用已棄用的 `use_container_width`**！請全面使用 `width="stretch"`（取代 `use_container_width=True`）或 `width="content"`（取代 `use_container_width=False`）。
   - `st.metric` 若 `delta` 字串包含中文字首（例如 `"單日 +1.2%"`），必須明確傳入 `delta_color="red"|"green"|"gray"` 與 `delta_arrow="up"|"down"|"off"`，若為純資訊說明（非漲跌）則傳入 `delta_color="off", delta_arrow="off"`。
4. **Pandas 3.x 相容性**：
   - `DataFrame.style.applymap()` 已移除，所有表格上色必須使用 **`DataFrame.style.map()`**。
   - 時間序列重取樣（Resample）月底請使用 `"ME"`（不可使用舊版 `"M"`）。
5. **PyArrow 序列化安全**：
   - 傳給 `st.dataframe` 或 `st.table` 的 DataFrame，同一欄位（Column）內的資料型別必須一致（不可混放 `int` 與 `str`），避免觸發 `pyarrow.lib.ArrowTypeError`。
6. **機密檔案保護**：
   - 嚴禁將 `.env`、`paper_portfolio.json`、`node_modules/`、`dist/` 加入 Git Commit。

---

## 📋 任務拆解清單（共 5 大任務）

---

### Task 1：消除所有棄用警告與 PyArrow 轉型警告（Code Hygiene）

- **目標檔案**：
  - [`app_pages/overview.py`](app_pages/overview.py)
  - [`app_pages/paper_trade.py`](app_pages/paper_trade.py)
  - [`app_pages/data_mgmt.py`](app_pages/data_mgmt.py)
- **實作細節**：
  1. 在 [`app_pages/overview.py`](app_pages/overview.py) 第 343–355 行的 `stats` 字典中，`"交易日數": len(df)` 目前為 `int`，而其他項目為 `str`，導致 `st.table` 觸發 `pyarrow.lib.ArrowTypeError`。請將其改為字串格式：`f"{len(df):,} 天"`。
  2. 搜尋 `app_pages/` 目錄下所有剩餘的 `use_container_width=True`，全部替換為 `width="stretch"`（若為 `st.plotly_chart` 或 `st.altair_chart` 或 `st.dataframe` 或 `st.button` 皆適用，因為 Streamlit 1.63 原生支援 `width="stretch"` 或預設自動延展）。
- **驗收標準**：
  - 執行 `AppTest` 測試全部 7 個頁面時，終端機**不得再出現** `Please replace use_container_width with width` 或 `pyarrow.lib.ArrowTypeError` 警告。

---

### Task 2：側邊欄全局「資料鮮度狀態列」與「一鍵同步最新收盤價」按鈕

- **目標檔案**：
  - [`streamlit_app.py`](streamlit_app.py)
  - [`fill_yfinance_gap.py`](fill_yfinance_gap.py)
- **實作細節**：
  1. 在 [`fill_yfinance_gap.py`](fill_yfinance_gap.py) 新增一個可被外部呼叫的匯總函式 `update_all_csvs() -> tuple[int, str]`：
     - 掃描專案根目錄所有 `[0-9]*.csv` 並執行 `fill_gaps(csv_path)`。
     - 回傳 `(更新成功的檔案數, 最新資料日期字串)`。
  2. 在 [`streamlit_app.py`](streamlit_app.py) 的共同 `with st.sidebar:` 區塊底部（在 `pg.run()` 之前或側邊欄導覽下方）：
     - 讀取 `2330`（或任一可用標的）的最新一筆日期，顯示簡潔狀態：`📅 最新資料日：YYYY/MM/DD`。
     - 新增一顆按鈕 `st.button(":material/sync: 同步最新收盤價", width="stretch")`：點擊時顯示 `st.spinner("正在從 Yahoo Finance 同步全市場最新收盤價...")`，呼叫 `update_all_csvs()`、清除 `load_stock.clear()` 快取，並以 `st.toast` 提示更新完成後 `st.rerun()`。
- **驗收標準**：
  - 在任何一個頁面打開左側欄，都能看到最新資料日期與「同步最新收盤價」按鈕，且 `AppTest.from_file("streamlit_app.py").run()` 無任何例外。

---

### Task 3：主動式 ETF 專區升級 — 新增「上漲／下跌捕獲率 (Capture Ratios)」與「一鍵匯出 CSV 報表」

- **目標檔案**：
  - [`app_pages/active_etf.py`](app_pages/active_etf.py)
- **實作細節**：
  1. **上漲／下跌捕獲率（Upside / Downside Capture Ratio）計算**：
     - 在 [`app_pages/active_etf.py`](app_pages/active_etf.py) 的「主動操盤績效檢驗表 (`perf_rows`)」中，利用對齊後的日報酬率 `r_etf` 與基準日報酬率 `r_bench`：
       - **上漲捕獲率 (`upside_capture`)**：取 `r_bench > 0` 的交易日，計算 `(r_etf[r_bench > 0].mean() / r_bench[r_bench > 0].mean()) * 100`（若分母為 0 則設為 `100.0`）。數值 `> 100%` 代表大盤上漲時該主動式 ETF 漲更兇。
       - **下跌捕獲率 (`downside_capture`)**：取 `r_bench < 0` 的交易日，計算 `(r_etf[r_bench < 0].mean() / r_bench[r_bench < 0].mean()) * 100`（若分母為 0 則設為 `100.0`）。數值 `< 100%` 代表大盤下跌時該主動式 ETF 更抗跌。
     - 將 `"上漲捕獲率%"` 與 `"下跌捕獲率%"` 加入 `perf_df` 表格並格式化為 `"{:.1f}%"`。
  2. **一鍵匯出 CSV 按鈕**：
     - 在「主動操盤績效檢驗表」區塊右上方或表格下方，新增 `st.download_button`：
       - 標籤：`":material/download: 匯出主動式 ETF 績效檢驗表 (CSV)"`
       - 內容：`perf_df.to_csv().encode("utf-8-sig")`（使用 `utf-8-sig` 確保 Excel 打開繁體中文不亂碼）
       - 檔名：`f"active_etf_performance_{horizon}.csv"`
- **驗收標準**：
  - `app_pages/active_etf.py` 表格正確顯示 `上漲捕獲率%` 與 `下跌捕獲率%`，且下載按鈕可正常渲染不報錯。

---

### Task 4：模擬交易紀錄簿升級 — 支援「整張／零股切換」、「ETF 0.1% 證交稅率」與「停損／停利目標價警示」

- **目標檔案**：
  - [`app_pages/paper_trade.py`](app_pages/paper_trade.py)
- **實作細節**：
  1. **區分個股與 ETF 證交稅率**：
     - 台股一般股票賣出證交稅為 `0.3%`（`0.003`），但 ETF（代號以 `00` 開頭，如 `0050`、`00830`、`00980A` 等）賣出證交稅僅為 **`0.1%`（`0.001`）**。
     - 請在 [`app_pages/paper_trade.py`](app_pages/paper_trade.py) 新增輔助函式 `get_sell_fee_rate(sid: str) -> float`，若 `sid.startswith("00")` 則回傳 `0.001425 + 0.001`，否則回傳 `0.001425 + 0.003`。
  2. **支援「整張（1,000 股）」與「零股（1 股）」下單切換**：
     - 在左側下單面板新增 `st.segmented_control("交易單位", ["整張 (1,000股)", "零股 (股)"], default="整張 (1,000股)")`。
     - 若選「整張」，輸入張數（`order_shares = lots * 1000`）；若選「零股」，輸入股數（`1 ～ 999` 股，`order_shares = shares`）。
     - 持倉明細表格改為同時顯示「持有股數」（例如 `1,500 股 (1.5 張)`），以完整相容舊有 `paper_portfolio.json` 的 `shares` 欄位。
  3. **持倉停損／停利目標價設定與觸價提醒**：
     - 在左側欄或持倉明細下方，允許使用者針對目前已持有的股票設定選填的 `stop_loss_price`（停損價）與 `take_profit_price`（停利價），儲存於 `pf["holdings"][sid]` 中。
     - 在主畫面「持倉明細」上方，自動檢查每檔持倉的最新收盤價：
       - 若 `現價 >= take_profit_price`，顯示紅色喜訊 `st.error(f"🎯 【停利達標】{sid} 現價 {price:.2f} 已突破設定停利價 {tp:.2f}！", icon=":material/celebration:")`（台股紅代表停利達標）。
       - 若 `現價 <= stop_loss_price`，顯示綠色警示 `st.success(f"⚠️ 【停損觸發】{sid} 現價 {price:.2f} 已跌破設定停損價 {sl:.2f}，請注意風險！", icon=":material/warning:")`。
- **驗收標準**：
  - 舊版 `paper_portfolio.json` 結構無縫相容（缺少 `stop_loss_price` / `take_profit_price` 時預設為 `None` 不報錯），且 `AppTest` 測試通過。

---

### Task 5：個股技術分析頁 — 新增「近 10 日漲跌著色」與「關鍵支撐／壓力價位速覽卡」

- **目標檔案**：
  - [`app_pages/overview.py`](app_pages/overview.py)
- **實作細節**：
  1. **關鍵支撐與壓力價位速覽（Support & Resistance Panel）**：
     - 在 [`app_pages/overview.py`](app_pages/overview.py) K 線圖下方，新增一個 `with st.container(border=True):` 區塊，標題為 `":material/layers: 關鍵技術支撐與壓力價位"`。
     - 自動計算並以橫向 `st.metric`（搭配 `delta` 顯示距離目前收盤價的差距 `%`，`delta_color="off", delta_arrow="off"`）列出：
       - **近期壓力 1（布林上軌 +2σ）**
       - **近期壓力 2（20 日波段高點）**
       - **多空分水嶺（20MA 月線）**
       - **近期支撐 1（20 日波段低點）**
       - **近期支撐 2（布林下軌 -2σ）**
  2. **最近 10 筆資料表格加上單日漲跌%與台股紅漲綠跌著色**：
     - 在 [`app_pages/overview.py`](app_pages/overview.py) 底部的「最近 10 筆資料」表格中，新增一欄 `"漲跌%"`（`df["Close"].pct_change() * 100`），並使用 `.style.map()` 將正數染為台股紅 `#ef4444`、負數染為台股綠 `#22c55e`。
- **驗收標準**：
  - `app_pages/overview.py` 渲染正常、無任何 `use_container_width` 或 `ArrowTypeError` 警告。

---

## 🧪 自動化驗收指令（Gemini Flash 完成後必跑）

請在完成上述 5 個任務後，於專案根目錄執行以下驗證腳本，確認所有頁面 `0 Warning, 0 Exception`：

```bash
.venv/bin/python -c '
from streamlit.testing.v1 import AppTest

pages = [
    "streamlit_app.py",
    "app_pages/overview.py",
    "app_pages/screener.py",
    "app_pages/active_etf.py",
    "app_pages/comparison.py",
    "app_pages/backtest.py",
    "app_pages/paper_trade.py",
    "app_pages/data_mgmt.py",
]

for p in pages:
    at = AppTest.from_file(p, default_timeout=30).run()
    assert not at.exception, f"❌ FAILED in {p}: {at.exception}"
    print(f"✅ PASSED: {p}")
'
```
