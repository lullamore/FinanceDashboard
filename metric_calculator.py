
import pandas as pd


def calculate_portfolio_metrics(
    close_df: pd.DataFrame,
    rfr: float = 0.02, 
) -> Tuple[d.DataFrame, pd.DataFrame]:

    pct_change_grid=close_df.pct_change().dropna()
    cum_pct_change=(1+pct_change_grid).cumprod()-1
    annualised_volatility = pct_change_grid.std() * (252 ** 0.5)
    # here we assume r_date=log(1+pct_change) is iid. Therefore var(r_year) = var(r_date) * 252
    wealth_index=cum_pct_change+1
    drawdown=(wealth_index - wealth_index.cummax()) / wealth_index.cummax()
    #maximum_drawdown: maximum percentage loss if you can possibly achieve
    maximum_drawdown=drawdown.min()*-1
    #maximum of the difference between historical high up to date and the current value divided by peak value?
    #!need rfr input from user
    sharpe_ratio=(pct_change_grid.mean()*252-rfr)/ annualised_volatility
    #sharp ratio= mean annual return / std annual return
    corr_matrix=pct_change_grid.corr()
    cov_matrix=pct_change_grid.cov()

    betas=cov_matrix['SPY']/cov_matrix['SPY']['SPY']
    annualized_return=pct_change_grid.mean()*252
    # reflects how a change in market return affects change in stock's return
    alphas=(annualized_return-rfr)-betas*(annualized_return['SPY']-rfr)
    # how much does chosen stock beat market benchmark, annualized
    metrics_df = pd.DataFrame({'Ticker': close_df.columns,
        "Total Return": cum_pct_change.iloc[-1],
        "Annualized Return": annualized_return,
        "Annualized Volatility": annualised_volatility,
        "Max Drawdown": maximum_drawdown,
        "Sharpe Ratio": sharpe_ratio,
        "Beta": betas,
        "Alpha": alphas
    })
    
    return (metrics_df, corr_matrix)