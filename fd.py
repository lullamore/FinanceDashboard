import pandas as pd
import yfinance as yf

import os
import pandas as pd
import yfinance as yf

# Define the local cache file
cache_file = "market_data_cache.csv"

# Check if the file already exists on your computer
if os.path.exists(cache_file):
    print("Loading data from local cache...")
    close_df = pd.read_csv(cache_file, index_col=0, parse_dates=True,date_format='%Y-%m-%d')
else:
    print("Downloading fresh data from Yahoo Finance...")
    df = yf.download(['AAPL', 'MSFT', 'GOOGL', 'NVDA','AMZN', 'SPY'], start='2020-01-01', end='2024-01-01')
    close_df = df['Close']
    
    # Save the downloaded data to your hard drive for next time
    close_df.to_csv(cache_file)

pct_change_grid=close_df.pct_change().dropna()
cum_pct_change=(1+pct_change_grid).cumprod()-1
annualised_volatility = pct_change_grid.std() * (252 ** 0.5)
# here we assume r_date=log(1+pct_change) is iid. Therefore var(r_year) = var(r_date) * 252
drawdown=(cum_pct_change- cum_pct_change.cummax()) / cum_pct_change.cummax()
maximum_drawdown=drawdown.min()*-1
#maximum of the difference between historical high up to date and the current value. Why there's denominator?
print(close_df)
print(pct_change_grid)
print(cum_pct_change)
print(annualised_volatility)
print(maximum_drawdown)