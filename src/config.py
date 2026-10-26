import os
from dotenv import load_dotenv, set_key

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(ENV_PATH, override=True)

# Discord Webhook URL (主要推播管道)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Legacy IFTTT Webhook Key
IFTTT_KEY = os.getenv("IFTTT_KEY", "")


def get_discord_webhook_url() -> str:
    """重新載入 .env 並回傳最新的 DISCORD_WEBHOOK_URL。"""
    load_dotenv(ENV_PATH, override=True)
    return os.getenv("DISCORD_WEBHOOK_URL", "").strip()


def save_discord_webhook_url(url: str) -> None:
    """將 DISCORD_WEBHOOK_URL 寫入專案根目錄的 .env 檔案中持久化保存。"""
    clean_url = url.strip()
    if not os.path.exists(ENV_PATH):
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(f"DISCORD_WEBHOOK_URL={clean_url}\n")
    else:
        set_key(ENV_PATH, "DISCORD_WEBHOOK_URL", clean_url)
    os.environ["DISCORD_WEBHOOK_URL"] = clean_url


def get_gcal_webhook_url() -> str:
    """重新載入 .env 並回傳最新的 GOOGLE_CALENDAR_WEBHOOK_URL。"""
    load_dotenv(ENV_PATH, override=True)
    return os.getenv("GOOGLE_CALENDAR_WEBHOOK_URL", "").strip()


def save_gcal_webhook_url(url: str) -> None:
    """將 GOOGLE_CALENDAR_WEBHOOK_URL 寫入專案根目錄的 .env 檔案中持久化保存。"""
    clean_url = url.strip()
    if not os.path.exists(ENV_PATH):
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(f"GOOGLE_CALENDAR_WEBHOOK_URL={clean_url}\n")
    else:
        set_key(ENV_PATH, "GOOGLE_CALENDAR_WEBHOOK_URL", clean_url)
    os.environ["GOOGLE_CALENDAR_WEBHOOK_URL"] = clean_url

