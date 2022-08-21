#!/usr/bin/env python
# coding: utf-8

# In[1]:


def update(detail,day,dec,close,price,buy,gain,money,stock):
    temp_detail = []
    temp_detail.append(day)                                                        #交易日期
    temp_detail.append(dec)                                                        #買賣 num股
    temp_detail.append(close)                                                      #成交價格: "收盤價"
    temp_detail.append(price)                                                      #持有成本(含稅)
    temp_detail.append(buy)                                                        #實際花費 buy元
    temp_detail.append(gain)                                                       #目前獲利
    temp_detail.append(money)                                                      #剩餘金額
    if dec[0]=='+':
        stock += int(dec[1:])
    else:
        stock -= int(dec[1:])
    temp_detail.append(stock)                                                      #更新庫存張數
    detail.append(temp_detail)                                                     #紀錄交易資訊至正是表格中
    detail_pd = pd.DataFrame(detail[1:],columns=detail[0])                         #將交易記錄製作成 DataFrame 
    return detail_pd,stock


# In[2]:


import math
import pandas as pd

# 記錄買賣資訊 
def buy_or_sell(day, decide, close, type_=1):
    global money, gain, buy, detail, stock, buy_unit, sell_unit, price, detail_pd, avg_price
    
    if decide == 'buy' and  money > 0 : 
        price = round(close * 1.001425, 1)                                             #計算含稅的股價
        
        if type_ == 1:                                                                 # type_1: 分段進場
            num = math.floor(buy_unit/price)                                           # 計算分段進場能購買的股數
            if (money- round(num*price)) > 0:                                              
                num = num                                                                 
            else:
                num = math.floor(money/price) 
        elif type_ == 2:                                                               # type_2: 全數進場
            num = math.floor(money/price)                                              # 計算剩餘金額能購買的股數
        
        buy = round(num*price)                                                         #計算實際花費
        money = money-buy                                                              #更新 money
        gain -= buy                                                                    #計算淨收益(含稅)
        detail_pd,stock = update(detail,day,'+' + str(num),close,price,'-' + str(buy),gain,money,stock)
        sell_unit = round(stock/5)                                                     #更新每次賣出單位
        
    elif decide == 'sell':       
        price = round(close * 0.995575)                                                #計算含稅的股價 
        
        if type_ == 1:                                                                 # type_1: 分段出場
            if (stock - sell_unit) > 0:                                                #計算購買股數
                num = sell_unit                                                                 
            else:
                num = stock
        elif type_ == 2:                                                               # type_2: 全數出場
            #print(day,'全數出場!')
            num = stock   
        
        sell = round(close * 0.995575 * num)                                           # 計算實際收入
        money = money + sell                                                           # 更新 money
        gain += sell                                                                   # 淨收益計算
        detail_pd,stock = update(detail,day,'-' + str(num),close,price,'+' + str(buy),gain,money,stock)
        buy_unit = round(money/5)                                                      #更新每次進場金額
        
    elif decide == 'over':
        sell = round(close * 0.995575 * stock)                                         # 計算實際收入
        money = money + sell                                                           # 更新 money
        gain += sell                                                                   # 淨收益計算
        num = stock                                                                    #將持有的股數全數出清
        detail_pd,stock = update(detail,day,'-' + str(num),close,round(close * 0.995575),'+' + str(buy),gain,money,stock)

