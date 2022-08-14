import twstock as ts
import time
import requests

stocks = ['2330', '0056', '2317']
p = []
for num in stocks:
    data = ts.realtime.get(num)
    if data['success']: 
        price = data['realtime']['latest_trade_price']
        if price == '-':
            price = 'null'
        else:
            price = round(eval(price), 2)
        p.append(price)
        time.sleep(3)
    else:
        print('twstock 讀取錯誤，錯誤原因:' + data['rtmessage'])
        p.append('null')
        time.sleep(3)

url = 'https://maker.ifttt.com/trigger/Test/with/key/bXj-ujwlSFKchJbyOHUVDL?'
for i in range(2):
    url += 'value' + str(i+1) + '=' + str(p[i]) + '&'
url += 'value' + str(i+2) + '=' + str(p[i+1]) 

push = requests.get(url)

stocks = ['2610', '2618']
p = []
for num in stocks:
    data = ts.realtime.get(num)
    if data['success']: 
        price = data['realtime']['latest_trade_price']
        if price == '-':
            price = 'null'
        else:
            price = round(eval(price), 2)
        p.append(price)
        time.sleep(3)
    else:
        print('twstock 讀取錯誤，錯誤原因:' + data['rtmessage'])
        p.append('null')
        time.sleep(3)

url = 'https://maker.ifttt.com/trigger/stockLINE/with/key/bXj-ujwlSFKchJbyOHUVDL?'
for i in range(len(stocks)-1):
    url += 'value' + str(i+1) + '=' + str(p[i]) + '&'
url += 'value' + str(i+2) + '=' + str(p[i+1]) 
push = requests.get(url)

print("success!")
