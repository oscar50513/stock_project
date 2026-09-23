import os
from dotenv import load_dotenv

load_dotenv()

# IFTTT Webhook Key
IFTTT_KEY = os.getenv("IFTTT_KEY", "bXj-ujwlSFKchJbyOHUVDL")
