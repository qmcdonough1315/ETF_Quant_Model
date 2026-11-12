# ETF Quant Model

## Workflow Pipeline
* **Universe:** 286 ETFs in 21 sleeves (`ETF_CATEGORIES` in `config.py`). Construction is long-only max-Sharpe with a 12% single-name cap, a 30% category cap, and an endogenous holdings count (names at or above a 1% weight, at most 15).
* **Paper ledger and TLH:** Each model run dollar-cost averages **~$3,846** (`$50k ÷ 13`) into the target weights and the same into VOO, laddering the $50k ETF sleeve over the 3-month min hold. Factor lots use a 91-day minimum hold, HIFO / least-gain lot selection on sells, a 30-day wash-sale window (including substantially identical peers), and beta-distance substitutes inside the same sleeve. See `PAPER_PORTFOLIO.md`.
* **Options / vol sleeve:** Separate $25k defined-risk paper book (+ $25k cash margin reserve) maps factor composite × IV Rank to credit spreads. See `OPTIONS_SLEEVE.md`. Live account/positions come from **Alpaca paper** (`modules/alpaca_client.py`, `ALPACA.md`). IV Rank history bootstraps from ThetaData free EOD via `run_iv_bootstrap.py` (no demo IVR).

---

## 📂 Module Breakdown

This quantitative model projects 3-month forward excess returns for a universe of sector ETFs using a multi-factor framework. Below is a guide to the codebase architecture:

* **`main.py`**  
  * *What it does:* The core execution engine. It coordinates data ingestion, runs dynamic beta estimation, computes expected factor premiums, outputs the final ranked list of long-only index weights, and then advances the paper portfolio ledger.
* **`modules/paper_portfolio.py`**  
  * *What it does:* Weekly dollar-cost-averaging and tax-aware ledger. It publishes a summary into the `paper_portfolio` Supabase table. Create that table with `supabase_paper_portfolio.sql`. Each run currently starts from a fresh ledger; lasting lot history needs the prior lots loaded before `process_week`.
* **`config.py`**  
  * *What it does:* The central configuration file. It stores global parameters such as your target ETF universe, lookback window lengths, and model factor selections (e.g., the Fama-French 5-factor + Carhart momentum model).
* **`backtest_engine.py`**  
  * *What it does:* The historical simulation framework. It tests how the quantitative model would have performed in past market periods, allowing you to evaluate strategy performance and drawdown characteristics safely out-of-sample.
* **`run_walkforward_backtest.py`**  
  * *What it does:* Implements a walk-forward optimization and testing loop. Instead of looking at a static historical window, it repeatedly trains the model on past data and tests it on subsequent unseen periods to prevent data snooping and overfitting.
* **`modules/data_ingestion.py`**  
  * *What it does:* Handles the retrieval and formatting of raw data. It pulls daily ETF historical prices via the Alpaca API and fetches macro risk factors (like market premium, size, value, and momentum) using factor libraries.
* **`modules/dynamic_beta_estimator.py`**  
  * *What it does:* The econometric heart of the model. It uses Ridge Regression (L2 regularization) to fix multicollinearity issues among sector ETFs and seeds a regularized Kalman Filter to track time-varying, adaptive factor sensitivities (betas) daily.
* **`modules/factor_model.py`**  
  * *What it does:* Manages multi-factor calculations, compounding daily factor premiums into 3-month rolling horizons to match your specific holding period without violating temporal independence assumptions.
* **`modules/portfolio_optimizer.py`**  
  * *What it does:* Applies constraints to translate raw model predictions into a tradeable portfolio. It enforces a strict long-only indexing framework, screens RMW drag and high volatility, and sizes weights with max-Sharpe subject to single-name and category caps.
* **`modules/paper_portfolio.py`**  
  * *What it does:* Advances the weekly paper ledger: DCA into the target weights, a parallel VOO sleeve, and tax-loss harvests that rotate into the closest same-category beta peer that is not wash-sale restricted.
* **`modules/utils.py`**  
  * *What it does:* Contains helper functions and shared utilities used across the pipeline to handle date formatting, data alignments, and logging.
