from datetime import datetime
import time
import requests
import twstock
from .config import IFTTT_KEY, get_discord_webhook_url


def notify_discord(
    sections: list[tuple[str, str]],
    webhook_url: str | None = None,
    title: str = "📊 台股與主動式 ETF 每日訊號雷達日報",
    color: int = 0xEF4444,
) -> tuple[bool, str]:
    """透過 Discord Webhook 發送彩色排版卡片 (Embed)。
    
    Parameters
    ----------
    sections : list of (field_name, field_value)
        要顯示在 Discord Embed 卡片中的區塊清單。
    webhook_url : str, optional
        Discord Webhook 網址，若未提供則自動從 .env 讀取 DISCORD_WEBHOOK_URL。
    title : str
        卡片標題。
    color : int
        左側色條顏色（預設台股多頭紅 0xEF4444）。
    """
    url = (webhook_url or get_discord_webhook_url()).strip()
    if not url:
        return False, "尚未設定 Discord Webhook 網址，請先在下方欄位貼上網址。"
    if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
        return False, "網址格式不正確，Discord Webhook 應以 https://discord.com/api/webhooks/ 開頭。"

    fields = []
    for name, val in sections:
        if val:
            fields.append({
                "name": name,
                "value": val[:1020],
                "inline": False,
            })

    payload = {
        "username": "台股訊號雷達 Bot",
        "embeds": [
            {
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {
                    "text": f"台灣股票與主動式 ETF 分析系統 • 發送時間 {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
                },
            }
        ],
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in (200, 204):
            return True, "✅ Discord 訊號日報已成功推播至你的頻道！"
        return False, f"Discord 發送失敗（HTTP {response.status_code}）：{response.text[:200]}"
    except Exception as e:
        return False, f"連線至 Discord 時發生錯誤：{e}"


def get_realtime_prices(stocks):
    """Fetch realtime prices for a list of stock IDs."""
    prices = []
    for num in stocks:
        data = twstock.realtime.get(num)
        if data["success"]:
            price_str = data["realtime"]["latest_trade_price"]
            if price_str == "-":
                prices.append("null")
            else:
                try:
                    prices.append(round(float(price_str), 2))
                except ValueError:
                    prices.append("null")
        else:
            print(f"twstock 讀取錯誤，錯誤原因: {data['rtmessage']}")
            prices.append("null")
        time.sleep(3)
    return prices


def notify_ifttt(event_name, values):
    """(Legacy) Send a notification via IFTTT Webhooks."""
    if not IFTTT_KEY:
        return False, "IFTTT_KEY 尚未設定。"
    url = f"https://maker.ifttt.com/trigger/{event_name}/with/key/{IFTTT_KEY}"
    payload = {f"value{i+1}": str(val) for i, val in enumerate(values[:3])}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True, f"[{event_name}] 發送成功"
        return False, f"[{event_name}] 失敗 (HTTP {response.status_code})"
    except Exception as e:
        return False, str(e)
