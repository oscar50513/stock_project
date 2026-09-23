import requests
import twstock
import time
from .config import IFTTT_KEY

def get_realtime_prices(stocks):
    """Fetch realtime prices for a list of stock IDs."""
    prices = []
    for num in stocks:
        data = twstock.realtime.get(num)
        if data['success']:
            price_str = data['realtime']['latest_trade_price']
            if price_str == '-':
                prices.append('null')
            else:
                try:
                    prices.append(round(float(price_str), 2))
                except ValueError:
                    prices.append('null')
        else:
            print(f"twstock 讀取錯誤，錯誤原因: {data['rtmessage']}")
            prices.append('null')
        time.sleep(3)
    return prices

def notify_ifttt(event_name, values):
    """Send a notification via IFTTT Webhooks."""
    if not IFTTT_KEY:
        print("IFTTT_KEY is not set.")
        return
        
    url = f'https://maker.ifttt.com/trigger/{event_name}/with/key/{IFTTT_KEY}?'
    
    # Construct URL parameters dynamically
    params = []
    for i, val in enumerate(values):
        if i >= 3: # IFTTT supports up to 3 values (value1, value2, value3)
            break
        params.append(f"value{i+1}={val}")
        
    url += "&".join(params)
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            print(f"[{event_name}] Notification sent successfully!")
        else:
            print(f"[{event_name}] Failed to send notification. Status: {response.status_code}")
    except Exception as e:
        print(f"[{event_name}] Error sending notification: {e}")

def run_notifications():
    """Run the notification workflow for predefined stocks."""
    print("Checking prices for batch 1...")
    stocks_1 = ['2330', '0056', '2317']
    prices_1 = get_realtime_prices(stocks_1)
    notify_ifttt('Test', prices_1)
    
    print("Checking prices for batch 2...")
    stocks_2 = ['2610', '2618']
    prices_2 = get_realtime_prices(stocks_2)
    notify_ifttt('stockLINE', prices_2)
    
    print("Notification process complete!")

if __name__ == "__main__":
    run_notifications()
