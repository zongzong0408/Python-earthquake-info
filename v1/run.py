import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import logging
import os
import re
import sys
import time
from typing import List, Optional, Protocol, Tuple

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ==============================================================================
# 0. 全域常數與日誌基礎設施 (Constants & Infrastructure Logging)
# ==============================================================================
# [架構意圖]：將外部相依的端點抽離為常數，避免字串散落在業務邏輯中，降低未來端點異動的修改成本
CWA_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001"
CWA_WEB_URL = "https://www.cwa.gov.tw/V8/C/E/MOD/MAP_LIST.html"
TIMEOUT_SEC = 5

# [架構意圖]：分別宣告標準輸出（stdout）與標準錯誤（stderr）的主控台物件，確保資料輸出與提示訊息在 Unix Pipe 下不互相污染
console = Console()
err_console = Console(stderr=True)
logger = logging.getLogger("EarthquakeQuery")

# ==============================================================================
# 1. 領域資料模型 (Domain Layer: Immutable Data Transfer Object)
# ==============================================================================
@dataclass(frozen=True)
class EarthquakeEvent:
    """
    [設計模式 - 不可變資料傳輸物件 (Immutable DTO)]
    - frozen=True：保證物件被建立後即無法被竄改，確保在多個函式管線流轉時具備線程安全（Thread-Safe）與狀態可預測性。
    """
    time: str                      # 地震發生時間 (格式: YYYY-MM-DD HH:MM:SS)
    magnitude: float               # 芮氏規模數值 (例如: 5.4)
    depth_km: float                # 震源深度 (單位: 公里)
    location: str                  # 震央所在地理描述
    max_intensity: Optional[str]   # 全臺觀測最大震度 (例如: '4級', '5弱', 若無則為 None)
    source: str                    # 資料來源識別標記 (用於可觀測性追蹤)

    def to_dict(self) -> dict:
        """[封裝方法]：將 DTO 轉換為標準字典，便於後續 JSON 序列化"""
        return asdict(self)

# ==============================================================================
# 2. 設計模式：擷取策略介面與實作 (Strategy Pattern - Data Ingestion)
# ==============================================================================
class FetchStrategy(Protocol):
    """
    [設計模式 - 策略介面 (Strategy Pattern Interface)]
    - 使用 Python 的 typing.Protocol 實現結構化型別（Structural Typing / Duck Typing）。
    - 任何具備 fetch 與 strategy_name 的物件皆可作為合法策略，無需顯式繼承 ABC，大幅降低耦合度。
    """
    @property
    def strategy_name(self) -> str:
        """傳回策略名稱"""
        ...

    def fetch(self, limit: int, session: requests.Session) -> List[EarthquakeEvent]:
        """定義獲取地震事件清單的抽象契約"""
        ...


class APIFetchStrategy:
    """
    [設計模式 - 具體策略 A：官方 RESTful API 擷取]
    - 職責：透過 HTTP 請求氣象署官方 API，並進行 JSON 結構化解析與震度計算。
    """
    def __init__(self, api_key: str):
        # [防呆注入]：初始化時強綁定 API Key，確保該策略具備執行先決條件
        self._api_key = api_key

    @property
    def strategy_name(self) -> str:
        return "Official API"

    def fetch(self, limit: int, session: requests.Session) -> List[EarthquakeEvent]:
        """
        [依賴注入 (DI)]：外部傳入 requests.Session，避免重複建立 TCP/TLS 握手連線
        """
        params = {"Authorization": self._api_key, "limit": limit, "format": "JSON"}
        
        # [防禦性網路呼叫]：加上超時限制（Timeout），防止外部伺服器卡住時造成程序懸掛
        response = session.get(CWA_API_URL, params=params, timeout=TIMEOUT_SEC)
        response.raise_for_status()

        # [型別與結構校驗]：驗證 API 回傳層級是否正常，避免 Key Error
        records = response.json().get("records", {}).get("Earthquake", [])
        if not isinstance(records, list):
            raise ValueError("CWA API 回傳結構非預期的 List 格式")

        events: List[EarthquakeEvent] = []
        for raw in records:
            info = raw.get("EarthquakeInfo", {})
            intensity_data = raw.get("Intensity", {})

            # [演算法 - 最大震度反演]：遍歷所有測站震度，萃取最大值以保留真實震度語意
            max_intensity_str: Optional[str] = None
            highest_val = -1

            shaking_areas = intensity_data.get("ShakingArea", [])
            if isinstance(shaking_areas, list):
                for area in shaking_areas:
                    val_str = str(area.get("AreaIntensity", "")).strip()
                    digits = re.findall(r"\d+", val_str)
                    if digits and int(digits[0]) > highest_val:
                        highest_val = int(digits[0])
                        max_intensity_str = val_str

            # [退避邏輯]：若分區測站無資料，嘗試從全局摘要欄位取得
            if not max_intensity_str:
                fallback = str(intensity_data.get("Earthquake", {}).get("MaximumEarthquakeIntensity", "")).strip()
                if fallback:
                    max_intensity_str = fallback

            # [實例化 DTO]：組裝不可變資料物件並加入回傳清單
            events.append(EarthquakeEvent(
                time=info.get("OriginTime", ""),
                magnitude=float(info.get("EarthquakeMagnitude", {}).get("MagnitudeValue", 0.0)),
                depth_km=float(info.get("FocalDepth", 0.0)),
                location=info.get("Epicenter", {}).get("Location", ""),
                max_intensity=max_intensity_str if max_intensity_str else "未知",
                source=self.strategy_name
            ))
        return events


class ScraperFetchStrategy:
    """
    [設計模式 - 具體策略 B：網頁爬蟲降級備援]
    - 職責：當無 API Key 或 API 故障時，解析氣象署 Web 即時列表 HTML 作為 Fallback。
    """
    @property
    def strategy_name(self) -> str:
        return "Web Scraper (Fallback)"

    def fetch(self, limit: int, session: requests.Session) -> List[EarthquakeEvent]:
        # [時間戳記防快取]：利用 Unix Timestamp 破壞瀏覽器與 CDN 的快取機制，確保取得最新資料
        timestamp = int(time.time() * 1000)
        url = f"{CWA_WEB_URL}?T={timestamp}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        response = session.get(url, headers=headers, timeout=TIMEOUT_SEC)
        response.raise_for_status()
        response.encoding = "utf-8"

        # [HTML 語法樹解析]：使用 BeautifulSoup 剖析網頁 DOM 節點
        soup = BeautifulSoup(response.text, "html.parser")
        events: List[EarthquakeEvent] = []
        current_year = datetime.now().year

        for item in soup.find_all("a"):
            text = item.get_text(strip=True)
            if not text:
                continue

            # [正則表達式萃取]：從非結構化文字中提取關鍵地震指標
            time_match = re.search(r"時間為([^，,]+)", text)
            loc_match = re.search(r"地點為([^，,]+)", text)
            depth_match = re.search(r"深度([\d\.]+)公里", text)
            mag_match = re.search(r"地震規模([\d\.]+)", text)

            # [條件短路]：任一必要指標缺失即視為無效雜訊節點，跳過處理
            if not all([time_match, loc_match, depth_match, mag_match]):
                continue

            # [日期邊界處理]：格式化純文字日期為標準 ISO 8601 風格字串
            raw_time = time_match.group(1)
            m = re.match(r"(\d+)月(\d+)日\s*(\d+)時(\d+)分", raw_time)
            if m:
                month, day, hour, minute = m.groups()
                formatted_time = f"{current_year}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute):02d}:00"
            else:
                formatted_time = raw_time

            # [限制切片]：注意爬蟲資料源無法提供細部測站震度，顯式填入 None
            events.append(EarthquakeEvent(
                time=formatted_time,
                magnitude=float(mag_match.group(1)),
                depth_km=float(depth_match.group(1)),
                location=loc_match.group(1).replace("位於", ""),
                max_intensity=None,
                source=self.strategy_name
            ))

            if len(events) >= limit:
                break
        return events

# ==============================================================================
# 3. 業務管線與協調層 (Orchestration & Functional Pipeline)
# ==============================================================================
def execute_fetch_pipeline(method: int, limit: int, session: requests.Session) -> Tuple[List[EarthquakeEvent], str]:
    """
    [設計模式 - 容錯降級協調器 (Graceful Degradation Pipeline)]
    - 職責：依據輸入參數調度最適策略，當主要策略（API）失敗時自動降級切換至備援策略（Scraper）。
    """
    load_dotenv()
    api_key = os.environ.get("CWA_API_KEY")

    # 策略路由分支：選擇優先執行的策略實例
    if method == 1:
        if not api_key:
            err_console.print("[dim]提示: 未設定 CWA_API_KEY，系統自動降級使用 Method 2 (網頁爬蟲)[/dim]")
            strategy = ScraperFetchStrategy()
            return strategy.fetch(limit, session), strategy.strategy_name
        try:
            strategy = APIFetchStrategy(api_key)
            return strategy.fetch(limit, session), strategy.strategy_name
        except (requests.RequestException, ValueError) as err:
            err_console.print(f"[dim]提示: 官方 API 請求異常 ({err})，自動降級切換為網頁爬蟲策略[/dim]")
            fallback_strategy = ScraperFetchStrategy()
            return fallback_strategy.fetch(limit, session), fallback_strategy.strategy_name

    err_console.print("[dim]提示: 爬蟲模式 (Method 2) 僅提供基礎地震資訊，無法取得各測站最大震度[/dim]")
    scraper_strategy = ScraperFetchStrategy()
    return scraper_strategy.fetch(limit, session), scraper_strategy.strategy_name


def parse_intensity_value(intensity_str: Optional[str]) -> int:
    """[輔助純函式]：將震度字串轉化為可比對之數值權重，用於多維度條件篩選"""
    if not intensity_str or intensity_str == "未知":
        return -1
    digits = re.findall(r"\d+", intensity_str)
    return int(digits[0]) if digits else -1


def filter_earthquake_pipeline(
    events: List[EarthquakeEvent],
    area: Optional[str] = None,
    mag_range: Optional[Tuple[float, float]] = None,
    min_intensity: Optional[int] = None,
    limit: int = 10
) -> List[EarthquakeEvent]:
    """
    [設計模式 - 純函式篩選管線 (Pure Functional Filter Pipeline)]
    - 特性：無副作用（No Side-effects），相同輸入保證相同輸出，過濾完畢後才實施 limit 切片。
    """
    filtered = []
    for e in events:
        # 地理字串模糊比對過濾
        if area and area not in e.location:
            continue
        # 芮氏規模閉區間過濾 [MIN, MAX]
        if mag_range and not (mag_range[0] <= e.magnitude <= mag_range[1]):
            continue
        # 最低震度閾值過濾
        if min_intensity is not None:
            if parse_intensity_value(e.max_intensity) < min_intensity:
                continue
        filtered.append(e)

    # [關鍵邏輯修正]：在滿足所有業務過濾條件後，才對結果實施最終筆數截斷
    return filtered[:limit]

# ==============================================================================
# 4. 設計模式：格式化與視覺化策略 (Formatter Strategies)
# ==============================================================================
def format_to_json(events: List[EarthquakeEvent], method_used: str) -> str:
    """[輸出策略 1]：將領域事件清單序列化為工業標準 JSON 格式字串"""
    has_missing = any(e.max_intensity is None for e in events)
    payload = {
        "status": "success",
        "metadata": {
            "count": len(events),
            "data_source": method_used,
            "notes": "此資料來源不包含詳細最大震度資訊" if has_missing else "資料完整"
        },
        "data": [e.to_dict() for e in events]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_to_text(events: List[EarthquakeEvent], method_used: str) -> str:
    """[輸出策略 2]：格式化為純文字清單，供純文字檔案匯出使用"""
    has_missing = any(e.max_intensity is None for e in events)
    lines = [f"查詢完成，共找到 {len(events)} 筆地震紀錄 (資料來源: {method_used})："]
    if has_missing:
        lines.append("(*註: 目前使用的資料來源不提供詳細最大震度資訊)")
    lines.append("")

    for idx, e in enumerate(events, 1):
        intensity_str = f"{e.max_intensity}" if e.max_intensity else "未知"
        lines.append(
            f"[{idx:02d}] 時間：{e.time}, 芮氏規模：{e.magnitude:.1f}, "
            f"深度：{e.depth_km:.1f}公里, 地點：{e.location}, 最大震度：{intensity_str}"
        )
    return "\n".join(lines)


def render_to_rich_terminal(events: List[EarthquakeEvent], method_used: str) -> None:
    """[輸出策略 3]：使用 Rich 終端函式庫渲染彩色儀表板，提升終端使用者體驗"""
    table = Table(
        title="臺灣即時地震資訊監控清單",
        caption=f"資料來源: [bold green]{method_used}[/bold green] | 呈現筆數: {len(events)}",
        header_style="bold cyan",
        border_style="bright_blue",
        show_lines=True
    )

    # 建立結構化欄位佈局
    table.add_column("項次", justify="center", style="dim", width=4)
    table.add_column("地震時間", justify="center", width=20)
    table.add_column("芮氏規模", justify="center", width=10)
    table.add_column("震源深度", justify="right", width=12)
    table.add_column("震央位置", style="bold white")
    table.add_column("最大震度", justify="center", width=10)

    for idx, e in enumerate(events, 1):
        # 依地震規模賦予語意色彩
        if e.magnitude >= 6.0:
            mag_display = f"[bold red]M {e.magnitude:.1f}[/bold red]"
        elif e.magnitude >= 5.0:
            mag_display = f"[bold yellow]M {e.magnitude:.1f}[/bold yellow]"
        else:
            mag_display = f"M {e.magnitude:.1f}"

        # 依震度數值賦予語意色彩
        intensity_val = parse_intensity_value(e.max_intensity)
        if intensity_val >= 5:
            intensity_display = f"[bold red]{e.max_intensity}[/bold red]"
        elif intensity_val >= 3:
            intensity_display = f"[bold yellow]{e.max_intensity}[/bold yellow]"
        elif intensity_val > 0:
            intensity_display = f"[green]{e.max_intensity}[/green]"
        else:
            intensity_display = "[dim]未知[/dim]"

        table.add_row(
            f"{idx:02d}",
            e.time,
            mag_display,
            f"{e.depth_km:.1f} km",
            e.location,
            intensity_display
        )

    # 將表格封裝於 Panel 外框中輸出，展現工業級 CLI 介面水準
    console.print(Panel(table, expand=False, border_style="cyan"))

# ==============================================================================
# 5. CLI 參數解析與主進入點 (Entry Point & Argument Parser)
# ==============================================================================
def parse_cli_args() -> argparse.Namespace:
    """[命令列介面層]：解析終端傳入參數並進行型別約束"""
    parser = argparse.ArgumentParser(description="臺灣即時地震資訊查詢工具 (Design-Pattern Functional CLI)")
    parser.add_argument("--method", type=int, choices=[1, 2], default=1, help="擷取策略 (1: 官方 API, 2: 網頁爬蟲)")
    parser.add_argument("--limit", type=int, default=10, help="最終顯示筆數上限 (預設: 10)")
    parser.add_argument("--area", type=str, help="特定縣市地區模糊篩選 (例如: 花蓮, 宜蘭)")
    parser.add_argument("--mag", type=float, nargs=2, metavar=('MIN', 'MAX'), help="芮氏規模區間 (例如: 4.5 7.0)")
    parser.add_argument("--intensity", type=int, choices=range(1, 8), help="最低震度等級數值過濾 (1-7)")
    parser.add_argument("--output", type=str, help="將結果寫出至檔案之路徑")
    parser.add_argument("--format", type=str, choices=['rich', 'txt', 'json'], default='rich', help="輸出呈現模式 (預設: rich)")
    return parser.parse_args()


def main():
    """主程序工作流協調中樞"""
    args = parse_cli_args()

    # [關鍵防禦策略]：為防止過濾後資料筆數不足，向前抓取 3 倍緩衝池樣本
    fetch_buffer_limit = max(args.limit * 3, 50)

    # [資源生命週期管理]：使用 with 語法確保 requests.Session 在結束時被正確關閉釋放
    with requests.Session() as http_session:
        
        # 階段 1：執行資料擷取管線
        raw_events, used_strategy_name = execute_fetch_pipeline(args.method, fetch_buffer_limit, http_session)

        if not raw_events:
            err_console.print("[bold red]錯誤：無法自目標來源獲取任何有效地震紀錄。[/bold red]")
            sys.exit(1)

        # 階段 2：執行純函式資料過濾管線
        mag_interval = (args.mag[0], args.mag[1]) if args.mag else None
        filtered_events = filter_earthquake_pipeline(
            events=raw_events,
            area=args.area,
            mag_range=mag_interval,
            min_intensity=args.intensity,
            limit=args.limit
        )

        if not filtered_events:
            err_console.print("[yellow]查無符合當前條件之地震紀錄。[/yellow]")
            sys.exit(0)

        # 階段 3：表現層分發（檔案輸出 vs 終端呈現）
        if args.output:
            # 檔案匯出強制限制為 txt 或 json 格式
            output_data = format_to_json(filtered_events, used_strategy_name) if args.format == 'json' else format_to_text(filtered_events, used_strategy_name)
            try:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(output_data)
                console.print(f"[bold green]✔ 資料已成功匯出至指定檔案: {args.output}[/bold green]")
            except IOError as err:
                err_console.print(f"[bold red]錯誤：檔案寫入失敗 ({err})[/bold red]")
                sys.exit(4)
        else:
            # 終端呈現模式切換
            if args.format == 'json':
                print(format_to_json(filtered_events, used_strategy_name))
            elif args.format == 'txt':
                print(format_to_text(filtered_events, used_strategy_name))
            else:
                render_to_rich_terminal(filtered_events, used_strategy_name)

    sys.exit(0)


if __name__ == "__main__":
    main()