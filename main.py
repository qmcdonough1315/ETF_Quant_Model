import config
from modules.data_ingestion import fetch_all_data
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts
from modules.fund_scorer import score_and_rank_funds
from modules.portfolio_optimizer import portfolio_expected_metrics
from modules.supabase_exporter import export_to_supabase

try:
    from modules.paper_portfolio import run_paper_portfolio_step
except Exception:  # pragma: no cover - optional until module is synced
    run_paper_portfolio_step = None


def main():
    print(f"Initializing Quantitative Pipeline ({config.FORECAST_HORIZON_MONTHS}-Month Horizon)...")

    # 1. Ingest Data
    prices, factors, macro = fetch_all_data(config.ETF_POPULATION)

    # 2. Kalman Filter Betas
    beta_profiles = run_kalman_filter_regressions(prices, factors)

    # 3. Forecast Factor Returns
    forecast_report = generate_factor_forecasts(
        factors,
        macro,
        threshold=config.MIN_FACTOR_THRESHOLD,
    )

    print(f"--- PREDICTED {config.FORECAST_HORIZON_MONTHS}-MONTH FACTOR EXCESS RETURNS ---")
    for factor, ret in forecast_report["predictions"].items():
        print(f"  • {factor:8s}: {ret * 100:+.2f}%")

    # --- TAX-LOSS HARVESTING / WASH-SALE RESTRICTIONS ---
    # Populated by the paper ledger once lot history is persisted in Supabase.
    recent_wash_sales = []

    # 4. Score funds and size via long-only max-Sharpe MVO
    #    (single-name + category caps; holdings count is endogenous)
    top_picks, top_betas = score_and_rank_funds(
        beta_profiles=beta_profiles,
        forecast_report=forecast_report,
        prices=prices,
        restricted_tickers=recent_wash_sales,
    )

    n_holdings = len(top_picks)
    print(
        f"\n--- ETF PORTFOLIO ({n_holdings} holdings, "
        f"{config.FORECAST_HORIZON_MONTHS}-MONTH EXPECTED RETURNS & WEIGHTS) ---"
    )
    cols = ["Ticker", "Total_Expected_Return_3M", "Volatility", "Target_Weight"]
    if "Category" in top_picks.columns:
        cols = ["Ticker", "Category", "Total_Expected_Return_3M", "Volatility", "Target_Weight"]
    print(top_picks[cols].to_string(index=False))

    print(f"\n--- FACTOR BETAS PROJECTION TABLE ({n_holdings} ETFs) ---")
    print(top_betas.to_string(index=False))

    port_exp_return, port_vol, port_sharpe = portfolio_expected_metrics(top_picks, prices)

    print("\n--- PORTFOLIO SUMMARY METRICS ---")
    print(f"  • Total Expected Return (3M) : {port_exp_return:+.2%}")
    print(f"  • Expected Volatility        : {port_vol:.2%}")
    print(f"  • Expected Sharpe Ratio      : {port_sharpe:.2f}\n")

    export_to_supabase(
        forecast_report=forecast_report,
        portfolio_df=top_picks,
        portfolio_return=port_exp_return,
        portfolio_vol=port_vol,
        portfolio_sharpe=port_sharpe,
    )

    # 5. Paper DCA + tax-aware ledger (summary export; full history replayed on site).
    #    A price-feed failure must not fail the weekly factor export above.
    if run_paper_portfolio_step is not None and not top_picks.empty:
        print("--- PAPER PORTFOLIO STEP ---")
        try:
            summary = run_paper_portfolio_step(top_picks, beta_profiles=beta_profiles)
        except Exception as exc:
            print(f"  • Paper portfolio step failed: {exc}")
            summary = None
        if summary:
            print(f"  • Strategy value : ${summary.get('strategy_value', 0):,.2f}")
            print(f"  • VOO value      : ${summary.get('voo_value', 0):,.2f}")
            print(f"  • Net taxable    : ${summary.get('net_taxable', 0):,.2f}")


if __name__ == "__main__":
    main()
