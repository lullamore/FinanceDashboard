import logging 
from typing import List, Union
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_historical_prices(
    tickers: List[str], 
    start_date: Union[str, pd.Timestamp], 
    end_date: Union[str, pd.Timestamp]
) -> pd.DataFrame:
    try:
        # auto_adjust=True incorporates dividends and splits (Total Return)
        # threads=True speeds up downloads for large lists
        df = yf.download(
            tickers, 
            start=start_date, 
            end=end_date, 
            auto_adjust=True, 
            threads=True,
            progress=False  # Suppress the yfinance progress bar in production
        )
        
        # Extract just the Closing prices
        
        prices = df["Close"]

            
        # Edge Case Handling: yfinance returns a pd.Series if only 1 ticker is passed.
        # We must ALWAYS return a DataFrame to prevent downstream crashes.
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=tickers[0])
            
        return clean_price_data(prices)

    except Exception as e:
        logger.error(f"Failed to fetch data from yfinance: {e}")
        return pd.DataFrame()
    

def clean_price_data(prices_df: pd.DataFrame) -> pd.DataFrame:
    if prices_df.empty:
        return prices_df

    # Forward fill missing data (e.g., if a stock was halted for a day)
    cleaned_df = prices_df.ffill()
    
    # Drop rows at the beginning if some stocks IPO'd later than the start_date
    cleaned_df = cleaned_df.dropna(how='all')
    
    return cleaned_df