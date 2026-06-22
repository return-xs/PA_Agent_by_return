from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import ExchangeInformationResponse

from datetime import datetime
import os
import pandas as pd
import logging
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")

configuration = ConfigurationRestAPI(api_key=API_KEY, api_secret=API_SECRET, base_path=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL)

client = DerivativesTradingUsdsFutures(config_rest_api=configuration)

"""
访问币安api需要设置代理:
HTTPS_PROXY="http://127.0.0.1:7890"
HTTP_PROXY="http://127.0.0.1:7890"
"""
if __name__ == "__main__":
    symbol = 'HYPEUSDT'

    # 输入您要获取历史数据的时间范围
    # start_date = '2026-01-01'
    # end_date = '2025-09-30'
    start_date = None
    end_date = int(datetime.strptime('2026-06-22 18:30:00', '%Y-%m-%d %H:%M:%S').timestamp()) * 1000

    # 获取历史数据
    interval = '5m'
    response = client.rest_api.kline_candlestick_data(symbol, interval, start_date, end_date)

    data: ExchangeInformationResponse = response.data()

    # 将数据转换为Pandas数据框
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])

    # 将时间戳转换为日期
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms')

    # 删除无用的列
    df = df.drop(['timestamp', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'], axis=1)

    # 将数据保存为CSV文件
    df.to_csv(f'{symbol}_{interval}_data.csv', index=False)