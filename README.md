# ETF Quant Model

## Workflow Pipeline
* **Testing:** Update the test scripts to validate the latest model changes (including the regularized Ridge regression and Kalman filter updates).
* **Universe Expansion:** Research and select a broader, more diverse array of sector-specific ETFs to scale the model population up to 200–400 assets.
* **Indexing** Introduce tax loss harvesting index mechanism with strict wash sale rules

---

## 📂 Module Breakdown

This quantitative model projects 3-month forward excess returns for a universe of sector ETFs using a multi-factor framework. Below is a guide to the codebase architecture:

* **`main.py`**  
  * *What it does:* The core execution engine. It coordinates data ingestion, runs dynamic beta estimation, computes expected factor premiums, and outputs the final ranked list of long-only index weights.
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
  * *What it does:* Applies constraints to translate raw model predictions into a tradeable portfolio. It enforces a strict long-only indexing framework, filtering out negative alpha predictions and sizing asset weights proportionally.
* **`modules/utils.py`**  
  * *What it does:* Contains helper functions and shared utilities used across the pipeline to handle date formatting, data alignments, and logging.
