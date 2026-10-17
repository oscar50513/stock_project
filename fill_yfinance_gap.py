import yfinance as yf
import pandas as pd
import os
import glob
from datetime import datetime, timedelta

def fill_gaps(csv_path):
    stock_id = os.path.basename(csv_path).replace('.csv', '')
    if not (stock_id and stock_id[0].isdigit()):
        print(f"Skipping {csv_path}, not a valid stock/ETF ID")
        return
    
    # Read the existing CSV
    try:
        df_exist = pd.read_csv(csv_path, parse_dates=['Date'])
    except Exception as e:
        print(f"Error reading {csv_path}: {e}")
        return
        
    if df_exist.empty:
        return
        
    last_date = df_exist['Date'].iloc[-1]
    # yf requires start date, we fetch from last_date + 1 day
    start_date = last_date + timedelta(days=1)
    if start_date > datetime.now():
        print(f"{stock_id} is already up to date.")
        return
        
    start_str = start_date.strftime('%Y-%m-%d')
    print(f"Fetching {stock_id} from {start_str} to today...")
    
    ticker = f"{stock_id}.TW"
    try:
        df_new = yf.download(ticker, start=start_str, progress=False)
    except Exception as e:
        print(f"Failed to fetch {stock_id}: {e}")
        return
        
    if df_new.empty:
        print(f"No new data for {stock_id}.")
        return
        
    # Format to match original: Date,Open,High,Low,Close,Volume
    df_new = df_new.reset_index()
    # Handle yfinance multiindex columns if they exist
    if isinstance(df_new.columns, pd.MultiIndex):
        df_new.columns = df_new.columns.get_level_values(0)
        
    df_new = df_new[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
    df_new['Date'] = df_new['Date'].dt.strftime('%Y/%m/%d')
    
    # Round float values
    for col in ['Open', 'High', 'Low', 'Close']:
        df_new[col] = df_new[col].round(2)
        
    # Volume might be in shares, but old data is in lots (1000 shares). 
    # Let's check old volume. E.g. TSMC on 2022/08/19 is 13950 (which is 13 million shares).
    # yfinance gives shares. So we divide by 1000.
    df_new['Volume'] = (df_new['Volume'] / 1000).astype(int)
    
    # Append
    print(f"Appending {len(df_new)} rows to {csv_path}")
    df_new.to_csv(csv_path, mode='a', header=False, index=False)

if __name__ == '__main__':
    csvs = glob.glob('*.csv')
    for csv in csvs:
        fill_gaps(csv)
    print("Done filling gaps.")
