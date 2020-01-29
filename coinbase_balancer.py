'''
Coinbase Balancer
2020 - Sandy Bay

Re-balances every hour based on manually fixed allocations
Defaults to limit orders which are cancelled if unfilled and recalculated for the new rebalance

Dependencies
pip install cbpro

'''
import math
import time
import pandas as pd
import numpy as np
import cbpro
from apscheduler.schedulers.blocking import BlockingScheduler

# set keys
api_key = ''
api_secret = ''
passphrase = ''

# set weights
# look for 6 to 12 month value
# hedge fiat (usd,rub,try,eur)
# focus on trusted cryptos with the following priority
# security
# value
# usage
# fees
# privacy
# speed

lastweights = {
    "XLM":0.005,
    "ETC":0.005,
    "LTC":0.01,
    "BTC": 0.93,  
    "GBP": 0.05 } 

# globals
prices = {} # asset prices in btc
prices['BTC'] = 1.0
BTCGBP = 0.0
balances = {}
balancesbtc = {}
totalbtc = 0
diffs = {}
steps = {}
ticks = {}
minQtys = {}

# connect
public_client = cbpro.PublicClient()
auth_client = cbpro.AuthenticatedClient(api_key, api_secret, passphrase)

def getPrices():
    global prices, BTCGBP
    # get prices
    for asset in lastweights:
        if asset != 'BTC':
            if asset == 'GBP':
                priceinfo = public_client.get_product_ticker(product_id='BTC-GBP')
                p = float(priceinfo['price'])
                BTCGBP = p
                prices['GBP'] = 1 / p
            else:
                priceinfo = public_client.get_product_ticker(product_id=(asset+'-BTC'))
                p = float(priceinfo['price'])
                prices[asset] = p
    
    print('Prices (BTC)')
    print(prices)

def getBalance():
    global balances, balancesbtc, totalbtc 
    totalbtc = 0
    # get balance
    info = auth_client.get_accounts()
    # print(info)
    for balance in info:
        # print('{}: {}'.format(balance['currency'],balance['balance']))
        bal =  float( balance['balance'] )
        asset = balance['currency']
        if asset in lastweights:
            balances[ asset ] = bal
            balancesbtc[ asset ] = bal * prices[asset]
            totalbtc = totalbtc + bal * prices[asset]
    # # print(balances)
    print("Balances (BTC)")
    print(balancesbtc)

def getDiffs():
    global diffs
    # get difference
    for asset in lastweights:
        adjshare = totalbtc * lastweights[asset]
        currshare = balancesbtc[asset]
        diff = adjshare - currshare
        diffs [ asset ] = diff
    diffs = dict(sorted(diffs.items(), key=lambda x: x[1]))
    print('Adjustments (BTC)')
    print(diffs)

def cancelOrders():
    # cancel current orders
    print('Canceling open orders')
    orders = auth_client.get_orders()
    for order in orders:
        sym = order['product_id']
        asset = sym[0:-4]
        if asset in lastweights:
            orderid = order['id']
            result = auth_client.cancel_order(orderid)
            print(result)
            # print('Cancel, {}, {}'.format(asset,orderid))


def step_size_to_precision(ss):
    return ss.find('1') - 1

def format_value(val, step_size_str):
    precision = step_size_to_precision(step_size_str)
    if precision > 0:
        return "{:0.0{}f}".format(val, precision)
    return math.floor(int(val))

def getSteps():
    global steps, ticks, minQtys
    # step sizes
    info = public_client.get_products()
    for dat in info:
        sym = dat['id']
        asset = dat['base_currency']
        quote = dat['quote_currency']
        if quote == 'BTC' and asset in lastweights:
            steps[asset] = dat['base_min_size'] 
            ticks[asset] = dat['quote_increment']
            minQtys[asset] = dat['base_min_size']
        elif sym == 'BTC-GBP':
            steps[sym] = dat['base_min_size'] 
            ticks[sym] = dat['quote_increment']
            minQtys['GBP'] = dat['base_min_size']

def placeOrders():
    # all go through btc
    # this can be smart routed later
    global diffs
    print('Setting orders')
    getSteps()
    # set sell orders
    for asset in diffs:
        diff = diffs[asset]
        if asset != 'BTC':
            thresh = float(minQtys[asset])
            if  diff <  -0.001 : # threshold $ 1
                if asset != 'BTC' and asset != 'GBP':
                    sym = asset + '-BTC'
                    amount = 0-diff # amount in btc
                    if ( amount / prices[asset] ) > thresh:
                        diffs[asset] = diffs[asset] + amount
                        diffs['BTC'] = diffs[asset] - amount
                        amount = format_value ( amount / prices[asset] , steps[asset] )
                        price = format_value ( prices [ asset ] + 0.007 * prices [ asset ], ticks[asset] )# adjust for fee
                        print('Setting sell order for {}, amount:{}, price:{}'.format(asset,amount,price))
                        auth_client.place_limit_order(
                            product_id = sym, 
                            side = 'sell', 
                            price = price, 
                            size = amount )
                        
                    
                elif asset == 'GBP':
                    sym = 'BTC-GBP'
                    amount = 0-diff
                    if amount > ( thresh / BTCGBP ):
                        diffs[asset] = diffs[asset] + amount
                        diffs['BTC'] = diffs[asset] - amount
                        amount = format_value ( amount  , steps[sym] )
                        price = format_value ( BTCGBP - 0.007 * BTCGBP , ticks[sym])# adjust for fee
                        print('Setting buy order for {}, amount:{}, price:{}'.format(asset,amount,price))
                        auth_client.place_limit_order(
                            product_id = sym, 
                            side = 'buy', 
                            price = price, 
                            size = amount )
                        

    # set buy orders
    diffs = dict(sorted(diffs.items(), key=lambda x: x[1], reverse=True))

    for asset in diffs:
        diff = diffs[ asset ]
        if asset != 'BTC':
            thresh = float( minQtys[ asset ] )
            if  diff >  0.001 : # threshold $ 1
                if asset != 'BTC' and asset != 'GBP':
                    sym = asset + '-BTC'
                    amount = diff
                    print('{}: amount: {},thresh: {}'.format(sym,( amount / prices[asset] ),thresh))
                    if ( amount / prices[asset] ) > thresh:
                        diffs[asset] = diffs[asset] - amount
                        diffs['BTC'] = diffs[asset] + amount
                        amount = format_value ( amount / prices[asset] , steps[asset] )
                        price = format_value ( prices [ asset ] - 0.007 * prices [ asset ] , ticks[asset] )# adjust for fee
                        print('Setting buy order for {}, amount:{}, price:{}'.format(asset,amount,price))
                        auth_client.place_limit_order(
                            product_id = sym, 
                            side = 'buy', 
                            price = price, 
                            size = amount )
                        
                    
                elif asset == 'GBP':
                    sym = 'BTC-GBP'
                    amount = diff
                    if amount > ( thresh / BTCGBP ):
                        diffs[asset] = diffs[asset] - amount
                        diffs['BTC'] = diffs[asset] + amount
                        amount = format_value ( amount  , steps[sym] )
                        price = format_value ( BTCGBP + 0.007 * BTCGBP , ticks[sym])# adjust for fee
                        print('Setting sell order for {}, amount:{}, price:{}'.format(asset,amount,price))
                        auth_client.place_limit_order(
                            product_id = sym, 
                            side = 'sell', 
                            price = price, 
                            size = amount )                
                        

    print ( 'Final differences' )
    print ( diffs )

def iteratey():
    getPrices()
    getBalance()
    getDiffs()
    cancelOrders()
    placeOrders()    

iteratey()

scheduler = BlockingScheduler()
scheduler.add_job(iteratey, 'interval', hours=1)
scheduler.start()
