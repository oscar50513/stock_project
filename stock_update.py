import twstock
import os
import datetime 

path = os.getcwd()
print(path)
stocks = [i for i in os.listdir(path) if '.csv' in i]
print(stocks)
day = datetime.date.today().strftime("%Y/%m/%d")

for num in range(len(stocks)):
    with open(stocks[num], 'r') as file:
        new_info = file.readlines()[-1]
    if day not in new_info:
        need = []
        need.append(day)
        real = twstock.realtime.get(stocks[num].split('.')[0])
        name = list(real['realtime'].keys())[-3:]
        for i in name:
            need.append(str(eval(real['realtime'][i])))
        need.append(str(eval(real['realtime']['latest_trade_price'])))
        need.append(str(eval(real['realtime']['accumulate_trade_volume'])))
        print(need)
        connect = ','
        with open(stocks[num], 'a') as file:
            csv = connect.join(need)  #將串列轉換成以,區隔的字串
            csv += '\n' 
            file.write(csv)
        print('寫檔完成!')
    else:
        print('finish')