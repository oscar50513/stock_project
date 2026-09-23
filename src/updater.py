import twstock
import os
import glob
import datetime

def update_daily_csv(directory="."):
    """Updates all stock CSV files in the given directory with today's closing price."""
    # Only match CSV files that look like valid stock IDs (e.g., 2330.csv)
    # The old code indiscriminately used all .csv files which caused issues with files like TEJ2330.csv
    csv_files = glob.glob(os.path.join(directory, "[0-9]*.csv"))
    
    day_str = datetime.date.today().strftime("%Y/%m/%d")
    
    for file_path in csv_files:
        stock_id = os.path.basename(file_path).replace('.csv', '')
        
        # Check if today is already in the file
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                if not lines:
                    continue
                last_line = lines[-1]
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            continue
            
        if day_str in last_line:
            print(f"{stock_id} already updated for {day_str}.")
            continue
            
        print(f"Updating {stock_id} for {day_str}...")
        try:
            real = twstock.realtime.get(stock_id)
            if not real or not real.get('success'):
                print(f"Failed to get data for {stock_id}: {real.get('rtmessage', 'Unknown Error')}")
                continue
                
            rt = real['realtime']
            # Safely get OHLCV
            try:
                # Use float instead of eval for security
                open_p = float(rt.get('open', 0))
                high_p = float(rt.get('high', 0))
                low_p = float(rt.get('low', 0))
                close_p = float(rt.get('latest_trade_price', 0))
                vol = int(rt.get('accumulate_trade_volume', 0))
            except (ValueError, TypeError):
                print(f"Invalid data format received for {stock_id}")
                continue
                
            # Date,Open,High,Low,Close,Volume
            new_row = f"{day_str},{open_p},{high_p},{low_p},{close_p},{vol}\n"
            
            with open(file_path, 'a', encoding='utf-8') as file:
                file.write(new_row)
            print(f"{stock_id} write successful!")
            
        except Exception as e:
            print(f"Unexpected error updating {stock_id}: {e}")

if __name__ == "__main__":
    path = os.getcwd()
    print(f"Running update in {path}")
    update_daily_csv(path)
