# 🇹🇼 臺灣即時地震資訊分析與監控系統 (Taiwan Earthquake Sentinel)

> 一套基於 Python 3.12 純函式管線（Functional Pipeline）與結構型策略模式（Protocol-based Strategy Pattern）打造的高可靠性地震資訊 CLI 戰情工具。

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Architecture: Functional Pipeline](https://img.shields.io/badge/architecture-functional--pipeline-green.svg)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)

---

## 📖 目錄 (Table of Contents)
- [🇹🇼 臺灣即時地震資訊分析與監控系統 (Taiwan Earthquake Sentinel)](#-臺灣即時地震資訊分析與監控系統-taiwan-earthquake-sentinel)
  - [📖 目錄 (Table of Contents)](#-目錄-table-of-contents)
  - [🌟 核心特性 (Core Features)](#-核心特性-core-features)
  - [🏛️ 系統架構拓撲 (System Architecture)](#️-系統架構拓撲-system-architecture)
  - [🚀 快速開始 (Quick Start)](#-快速開始-quick-start)
    - [環境需求](#環境需求)
    - [安裝與配置](#安裝與配置)
  - [💻 命令列使用指南 (CLI Reference)](#-命令列使用指南-cli-reference)
    - [常用指令範例](#常用指令範例)
    - [完整參數清單](#完整參數清單)
  - [🛠️ 核心設計原則與模式 (Design Patterns)](#️-核心設計原則與模式-design-patterns)
  - [🚦 錯誤處理與退出碼規格 (Error Handling \& Exit Codes)](#-錯誤處理與退出碼規格-error-handling--exit-codes)
  - [🔭 未來演進願景 (Roadmap)](#-未來演進願景-roadmap)
  - [📄 授權條款 (License)](#-授權條款-license)

---

## 🌟 核心特性 (Core Features)

1. **雙通道資料獲取與優雅降級 (Dual-Channel Ingestion & Graceful Degradation)**：
   - **主要策略**：串接中央氣象署（CWA）官方 Open API，精準獲取結構化觀測數據。
   - **備援策略**：當無 API 金鑰或網路服務異常時，系統自動無縫降級切換至 Web 即時解析爬蟲，保障服務高可用性。
2. **新制震度語意保留 (CWA 10-Level Intensity Precision)**：
   - 拒絕粗暴的數值四捨五入，完整相容 CWA 2020 年起實施的新制 10 級震度（包含 `5弱`、`5強`、`6弱`、`6強`、`7級`），杜絕工程決策失真。
3. **無狀態純函式管線 (Pure Functional Data Pipeline)**：
   - 剔除過度設計的空殼類別，以「不可變資料容器（Frozen DTO）+ 一級函式（First-Class Functions）」流轉數據，杜絕全域狀態污染。
4. **工業級終端美學 (Rich Terminal UI)**：
   - 內建 `Rich` 格式化終端排版，根據規模（Magnitude）與最大震度自動呈現色階警示，同時支援 `json` 與 `txt` 管道匯出。
5. **緩衝池過濾演算法 (Buffer-Pool Filtering)**：
   - 解決傳統 CLI「先截斷、後過濾」導致的資料丟失缺陷，先獲取充足樣本池進行多維度篩選，再實施最終切片，確保資料完整性。

---

## 🏛️ 系統架構拓撲 (System Architecture)

系統數據流遵循單向不可變管線（Unidirectional Pipeline）：

```
┌────────────────────────────────────────────────────────┐
│                   CLI 輸入介面 (argparse)              │
│       (--method, --limit, --area, --mag, --intensity)  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│      1. 資料擷取層 (Protocol-based Fetch Pipeline)      │
│  ┌────────────────────────┐    ┌────────────────────┐  │
│  │   APIFetchStrategy     │ ──►│ ScraperFallback    │  │
│  │   (CWA Official API)   │Fail│ (Web DOM Parser)   │  │
│  └────────────────────────┘    └────────────────────┘  │
│            │ (依賴注入 requests.Session 連線池)         │
└────────────┼───────────────────────────────────────────┘
             │ 產出 List[EarthquakeEvent] (不可變 DTO 陣列)
┌────────────▼───────────────────────────────────────────┐
│      2. 純函式篩選層 (Functional Filter Pipeline)       │
│         - 地理模糊比對 (Area Filter)                   │
│         - 芮氏規模區間比對 (Magnitude Range)            │
│         - 震度等級權重閥值比對 (Intensity Rank)         │
│         - 最終結果切片截斷 (Buffer -> Limit Slice)     │
└────────────┬───────────────────────────────────────────┘
             │
┌────────────▼───────────────────────────────────────────┐
│      3. 表現分發層 (Presentation Strategies)           │
│    ┌──────────────┐    ┌─────────────┐    ┌─────────┐  │
│    │ Rich Terminal│    │ JSON Stream │    │ Text Log│  │
│    │  (預設儀表板) │    │ (結構化資料) │    │(檔案備存)│  │
│    └──────────────┘    └─────────────┘    └─────────┘  │
└────────────────────────────────────────────────────────┘

```

---

## 🚀 快速開始 (Quick Start)

### 環境需求

* **作業系統**：Linux / macOS / Windows 10+
* **Python 版本**：`Python >= 3.12`
* **推薦工具鏈**：[uv](https://github.com/astral-sh/uv) (極速 Python 套件管理工具)

### 安裝與配置

1. **取得原始碼**：
```bash
git clone [https://github.com/your-username/earthquake_sentinel.git](https://github.com/your-username/earthquake_sentinel.git)
cd earthquake_sentinel

```


2. **建立虛擬環境與安裝相依套件**：
```bash
# 使用現代化工具 uv (推薦，3 秒內完成)
uv venv --python 3.12
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install requests beautifulsoup4 rich python-dotenv

# 或使用標準 pip
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

```


3. **環境變數配置**：
複製環境變數範本並填入你的中央氣象署 API 金鑰（若不填寫，系統將自動啟動網頁爬蟲降級機制）：
```bash
echo "CWA_API_KEY=你的中央氣象署授權碼" > .env

```


> 💡 氣象署授權碼可至 [氣象資料開放平台](https://opendata.cwa.gov.tw/) 免費申請。



---

## 💻 命令列使用指南 (CLI Reference)

### 常用指令範例

* **預設檢視（顯示最近 10 筆地震，終端高美化表格）**：
```bash
python main.py

```


* **指定縣市區域與最低規模篩選**：
```bash
python main.py --area 花蓮 --mag 4.5 7.5 --limit 5

```


* **強制使用備援爬蟲模式 (Method 2)**：
```bash
python main.py --method 2 --limit 5

```


* **以結構化 JSON 格式輸出並匯出至檔案**：
```bash
python main.py --limit 20 --format json --output result.json

```


* **純文字報表輸出（適合重定向至日誌管線）**：
```bash
python main.py --format txt > earthquake.log

```



### 完整參數清單

| 參數標籤 (Flag) | 型別 (Type) | 預設值 | 說明 |
| --- | --- | --- | --- |
| `--method` | `int` (1 或 2) | `1` | 獲取策略：`1` 為官方 API（需 Key），`2` 為網頁即時爬蟲 |
| `--limit` | `int` | `10` | 最終顯示與產出的最大資料筆數 |
| `--area` | `str` | `None` | 震央所在地模糊比對篩選（例如：`花蓮`、`宜蘭`、`臺南`） |
| `--mag` | `float` (兩數值) | `None` | 芮氏規模閉區間篩選，語法：`--mag <MIN> <MAX>` |
| `--intensity` | `int` (1~7) | `None` | 最低震度閾值篩選（以數值級數 1~7 進行下限過濾） |
| `--format` | `str` | `rich` | 輸出格式策略：`rich` (彩色表格)、`txt` (文字條目)、`json` |
| `--output` | `str` | `None` | 指定檔案寫入路徑（若指定，將自動關閉終端互動呈現） |

---

## 🛠️ 核心設計原則與模式 (Design Patterns)

本系統不盲目堆疊框架，恪守以下工程原則：

* **Protocol 結構型策略模式（Structural Strategy Pattern）**：
定義 `FetchStrategy` 協議，透過靜態型別標註（Type Hints）約定介面邊界，使系統可隨時熱插拔新的數據源（例如介接日本 JMA 或美國 USGS API）而無需改動現有業務過濾邏輯。
* **依賴注入（Dependency Injection, DI）**：
資料獲取函式不於內部臨時實例化 HTTP 客戶端，統一由頂層注入 `requests.Session` 連線池實體，落實資源生命週期管理（Resource Lifecyle Control）。
* **不可變性與純函式（Immutability & Pure Functions）**：
`filter_earthquakes` 與 `format_as_*` 皆為純函式，無任何隱性副作用（Side-effects），大幅提升單元測試（Unit Test）覆蓋可行性。

---

## 🚦 錯誤處理與退出碼規格 (Error Handling & Exit Codes)

為符合 POSIX CLI 自動化整合標準，本工具定義了明確的程序退出碼（Exit Codes）：

| 退出碼 (Exit Code) | 狀態意義 | 觸發情境與處置指引 |
| --- | --- | --- |
| **`0`** | `SUCCESS` | 資料查詢、過濾與輸出完全成功。 |
| **`1`** | `DATA_NOT_FOUND / NETWORK_ERR` | 外部網路全面中斷，或篩選條件過於嚴苛導致查無任何匹配資料。 |
| **`2`** | `INVALID_ARGUMENTS` | 命令列參數型別錯誤（由 `argparse` 自動攔截觸發）。 |
| **`4`** | `IO_WRITE_ERROR` | 指定之 `--output` 檔案路徑無法寫入（如權限不足或磁碟空間已滿）。 |

---

## 🔭 未來演進願景 (Roadmap)

* [ ] **串流管線改造（Streaming Ingestion）**：針對海量歷史資料封存檔，使用 Python Generator (`yield`) 重構過濾鏈，達成 $O(1)$ 恆定記憶體消耗。
* [ ] **非同步長常駐整合（AsyncIO / Webhook）**：封裝非同步客戶端，支援推播至 Discord / Slack 頻道與 LINE Notify。
* [ ] **大地地質空間決策整合（Geotechnical GIS & RAG）**：結合經濟部地調所圖資與地層柱狀圖，評估地震對特定基地之土壤液化與差異沉陷風險。

---

## 📄 授權條款 (License)

本專案採用 [MIT 授權條款](https://www.google.com/search?q=LICENSE) 釋出，允許自由修改、散布與商業使用，惟須保留原始著作權聲明。

```

---

## 📦 環境配置與依賴管理 (Environment & Tooling)

在本地終端機驗證文檔與代碼一致性的檢核流程：

```bash
# 1. 驗證代碼格式規範 (Code Quality)
uv run ruff check main.py

# 2. 驗證 README 範例指令是否 100% 能在本地執行成功
uv run main.py --limit 3
uv run main.py --area 花蓮 --limit 2
uv run main.py --format json --output test_output.json

# 3. 清理測試產物
rm test_output.json
```