import streamlit as st
import fetch_data
import metric_calculator
import datetime

st.title("Interactive Financial Dashboard")
st.markdown(
    """ 
    This is where you can compare financial stats of different stocks!

    """
)

tickers = st.sidebar.multiselect(
    "Select Tickers / ETFs",
    options=["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "QQQ", "SPY"],
    default=["AAPL", "MSFT", "NVDA"]
)

rfr = st.sidebar.number_input("Risk-Free Rate (%)", value=2.0, step=0.1) / 100

start_date = datetime.date(2020, 1, 1)
end_date = datetime.date.today()

start_date,end_date=st.date_input('Daterange',value=(start_date,end_date))

# --- 2: User Inputs (Indicators) ---
st.sidebar.header("2. Metrics Setup")
available_metrics = [
    "Cumulative Return", "Annualized Volatility", 
    "Max Drawdown", "Sharpe Ratio", "Beta", "Alpha"
]
selected_metrics = st.sidebar.multiselect(
    "Select Indicators to Compute",
    options=available_metrics,
    default=["Sharpe Ratio", "Max Drawdown", "Alpha"]
)

st.sidebar.header("3. Chart Configuration")
if selected_metrics:
    sort_by = st.sidebar.selectbox("Sort Chart By", options=selected_metrics)
    sort_order = st.sidebar.radio("Sort Order", options=["Ascending", "Descending"])
    ascending_bool = True if sort_order == "Ascending" else False
else:
    sort_by = None
    ascending_bool = False

# --- Main App Logic ---
if not tickers:
    st.info("👈 Please select at least one ticker in the sidebar.")
else:
    all_tickers = list(set(tickers + ['SPY']))
    
    with st.spinner("Fetching market data..."):
        prices = fetch_data.fetch_historical_prices(all_tickers, start_date, end_date)
    
    if prices.empty:
        st.error("No data fetched. Check your tickers and date range.")
    else:
        # Compute stats
        stats_df,corr = metric_calculator.calculate_portfolio_metrics(prices, rfr=rfr)
        
        # Filter to user-selected metrics (keeping 'Ticker' as the index/identifier)
        display_cols = ["Ticker"] + selected_metrics
        filtered_stats = stats_df[display_cols]#!!!!!!!!!!!!!
        
        # Apply Sorting based on user selection
        if sort_by:
            filtered_stats = filtered_stats.sort_values(by=sort_by, ascending=ascending_bool)
        
        # --- UI Layout: Table & Chart ---
        st.subheader("Statistical Summary")
    
        # Display the sorted dataframe across the full width
        st.dataframe(
            filtered_stats.set_index("Ticker").style.format("{:.3f}"), 
            use_container_width=True
        )

