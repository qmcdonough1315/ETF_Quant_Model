# ETF Quant Model

A practical guide to the long-only ETF factor book: what it predicts, how it sizes positions, how it executes, and how we judge whether it works.

**Allocator one-pager:** [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md).  
**Risk / kill-switch (15% combined DD):** [`RISK_POLICY.md`](RISK_POLICY.md).  
**Next build wave (Cloud Agent prompts #1–#13):** [`AGENT_CHECKLIST_1_13.md`](AGENT_CHECKLIST_1_13.md).

**Audience:** Someone who knows Black–Scholes, linear algebra, and multivariate calculus, but may not live in factor investing, Kalman filters, or options volatility every day. Companion docs: [`OPTIONS_BOOK.md`](OPTIONS_BOOK.md) (options / vol sleeve), [`PAPER_PORTFOLIO.md`](PAPER_PORTFOLIO.md) (DCA + tax ledger), [`ALPACA.md`](ALPACA.md) (paper brokerage).

---

## 1. What this system is trying to do

Think of the ETF model as a **forecasting and portfolio construction engine**, not a day trader.

1. **Estimate** how sensitive each ETF is to a small set of systematic risk factors (market, size, value, profitability, investment, momentum).
2. **Forecast** those factor premiums over the next **~3 months**.
3. **Score** each ETF: expected return ≈ (factor exposures × forecasted premiums) + a shrunk residual (“alpha”).
4. **Optimize** a long-only portfolio (max Sharpe) with concentration caps.
5. **Execute** via a paper ledger: weekly DCA into target weights, with tax-aware exits, plus a separate options sleeve that *does not* short the ETF book.

Capital design for the full Quirk Macro paper book (**$100k**):

| Sleeve | Capital | Job |
|---|---|---|
| ETF factor book | $50k | Long-only multi-factor ETF portfolio, DCA’d over 13 weeks |
| Options / vol | $25k | Defined-risk short premium / modest long extension |
| Cash / margin reserve | $25k | Yield parking + options stress buffer |

The ETF sleeve never funds options margin. Options never change the long-only MVO constraints.

---

## 2. Intuition: factors before Kalman

### 2.1 Why factors at all?

A single ETF’s return can be written, roughly, as:

\[
R_i - R_f \approx \alpha_i + \beta_{i,\text{Mkt}}\,f_{\text{Mkt}} + \beta_{i,\text{SMB}}\,f_{\text{SMB}} + \cdots + \varepsilon_i
\]

If you believe the \(f\)’s (factor premiums) are somewhat predictable over a 3-month horizon, and you can estimate the \(\beta\)’s, you can rank ETFs by expected excess return without forecasting every ticker in isolation.

### 2.2 Fama–French 5 + Carhart (what each letter means)

We use Ken French’s monthly research factors (`modules/data_ingestion.py`):

| Factor | Code | Plain-English meaning |
|---|---|---|
| Market excess | `Mkt_RF` | Equity market return minus the risk-free rate |
| Size | `SMB` | Small stocks minus big stocks (“Small Minus Big”) |
| Value | `HML` | Cheap (high book-to-market) minus expensive (“High Minus Low”) |
| Profitability | `RMW` | Robust operating profitability minus weak (“Robust Minus Weak”) |
| Investment | `CMA` | Conservative asset growth minus aggressive (“Conservative Minus Aggressive”) |
| Momentum | `WML` | Recent winners minus losers (“Winners Minus Losers”; Carhart) |

**Mental model:** these are *long–short research portfolios*, not products you buy. An ETF’s **beta** to `HML` answers: “When value stocks outperform growth, how much does this ETF tend to move with that spread?”

Config tilts (`FACTOR_TILTS` in `config.py`) deliberately overweight value (`HML`), investment (`CMA`), and momentum (`WML`) in the scoring step when those premiums are in the forecast.

### 2.3 Alpha (the leftover)

\(\alpha_i\) is whatever average excess return is **not** explained by the six factors. In live scoring we **shrink** it toward the cross-sectional mean (`ALPHA_SHRINKAGE_WEIGHT = 0.75`) so one noisy residual does not dominate the portfolio.

---

## 3. Dynamic betas: Ridge seed + Kalman filter

Static OLS betas assume exposures are constant. Sector and style exposures drift. We estimate a **time-varying** state vector

\[
\theta_t = (\alpha_t,\ \beta_{\text{Mkt},t},\ \beta_{\text{SMB},t},\ \beta_{\text{HML},t},\ \beta_{\text{RMW},t},\ \beta_{\text{CMA},t},\ \beta_{\text{WML},t})^\top
\]

in `modules/dynamic_beta_estimator.py`.

### 3.1 Kalman filter in one paragraph

A Kalman filter is a recursive estimator for a hidden state that evolves slowly and is observed noisily.

- **State equation (how betas wander):** \(\theta_t = \theta_{t-1} + w_t\) with tiny process noise (we use a random-walk transition).
- **Observation equation (what we see):** \(R_{i,t}-R_{f,t} = x_t^\top \theta_t + v_t\), where \(x_t\) stacks \(1\) and the six factor returns that month.

Each month the filter **predicts** the next state, then **updates** using the new residual. If you know the Kalman gain from a filtering course: when observation noise is large relative to process noise, betas move slowly (our setting).

### 3.2 Why Ridge first?

Factor returns are correlated. Plain OLS on a short window can explode coefficients (multicollinearity). We:

1. Fit **RidgeCV** on the first ~12 months (L2 penalty chosen by cross-validation).
2. Use that coefficient vector as the Kalman **initial state**.

Ridge is the usual \(\ell_2\)-regularized least squares: \(\min_\beta \|y-X\beta\|^2 + \lambda\|\beta\|^2\). It shrinks collinear directions without dropping factors.

### 3.3 What the live score uses

For each ETF we take a short exponentially weighted average of the **latest** Kalman states (last three months, EWM), then compute:

\[
\mathbb{E}[R_i]_{3\text{m}} \approx \underbrace{\beta_i^\top (\text{tilted factor forecasts})}_{\text{factor piece}} + \underbrace{\text{shrunk }\alpha_i}_{\text{residual piece}}
\]

That is `Total_Expected_Return_3M` in `modules/fund_scorer.py`.

---

## 4. Forecasting factor premiums

`modules/factor_forecaster.py` trains a **LightGBM** multi-output regressor:

- **Targets:** compounded forward 3-month returns of each factor.
- **Features:** lagged factor returns, short rolling means, and lagged macro series from FRED (yield curve, credit spreads, CPI, VIX, USD, oil, etc.), plus a few interaction terms (e.g. stagflation-style CPI × curve).

At each weekly production run we fit on history available through “now” and predict the latest feature row. This is a supervised ML forecast of *factor* returns, not of individual ETFs.

---

## 5. Portfolio construction (long-only MVO)

`modules/portfolio_optimizer.py` turns scores into weights.

**Screens before optimization**

- Drop names where profitability beta × forecasted `RMW` is a drag.
- Cap extreme 3-month volatility unless expected return / vol clears an exception.

**Objective**

- Maximize a Sharpe-like objective over a candidate pool (~40 names), using Ledoit–Wolf shrunk covariance on monthly returns scaled to the 3-month horizon.
- Extra tilt in the objective toward positive `HML` / `CMA` exposure when those premiums are forecast positive.

**Hard constraints** (`config.py`)

| Constraint | Value | Why |
|---|---|---|
| Long-only | weights ≥ 0 | No short ETF book |
| Single-name cap | 12% | Avoid one-ticker concentration |
| Category cap | 30% | Avoid stacking near-substitutes in one sleeve |
| Min weight kept | 1% | Drop dust after optimize |
| Soft max names | 15 | Endogenous holdings count, not a forced N |

Output: `Target_Weight` vector consumed by the paper DCA / Alpaca equity propose path.

---

## 6. Universe

`ETF_CATEGORIES` in `config.py` holds **~286 ETFs across 21 sleeves** (core, mid/small, growth/value, sectors, alts, fixed income, international, etc.). Category labels also drive:

- portfolio category caps, and
- tax-loss harvest **substitutes** (closest same-sleeve peer in beta space).

---

## 7. Execution & operating cadence

### 7.1 Weekly production path

```text
fetch prices + Ken French factors + FRED macro
        ↓
Kalman betas per ETF
        ↓
LightGBM 3M factor forecasts
        ↓
score ETFs → long-only max-Sharpe weights
        ↓
export factor_predictions (+ options composites) to Supabase
        ↓
paper portfolio step (DCA / TLH summary)
```

Entry point: `main.py`. Scheduled by `.github/workflows/weekly_run.yml` (Sundays 13:00 UTC / 9:00 AM Eastern when on EDT).

### 7.2 Paper ETF ledger (summary)

See [`PAPER_PORTFOLIO.md`](PAPER_PORTFOLIO.md) for full rules. Short version:

- Deploy ~$3,846/week (`$50k ÷ 13`) into model weights and the same into **VOO** (benchmark sleeve).
- 91-day minimum hold; HIFO / least-gain lot selection; 30-day wash-sale window.
- Harvest rotations prefer the nearest same-category peer in 6-factor beta Euclidean distance.
- Alpaca paper places **equity buys**; HIFO/TLH sells are still ledger-side (see `ALPACA.md`).

### 7.3 Options sleeve (separate)

Factor scores for Phase 1 optionable ETFs are z-scored into an **options composite** and combined with **IV Rank** to choose credit structures. Full narrative: [`OPTIONS_BOOK.md`](OPTIONS_BOOK.md).

---

## 8. How we benchmark / backtest

We do **not** judge the model by a single in-sample fit. Two related engines exist:

### 8.1 Walk-forward backtest (primary research loop)

Script: `run_walkforward_backtest.py` (shared helpers in `modules/backtest_returns.py`; also `backtest_engine.py`).

**Idea:** At rebalance date \(t\), use **only** data ≤ \(t\) to estimate betas, forecast factors, and build weights. Then hold that portfolio for the next **3 months**, record the realized return as **Σ wᵢ rᵢ** using production `Target_Weight`, advance \(t\) by 3 months, and repeat. That is the standard defense against look-ahead bias / data snooping. Use `--equal-weight` only as an ablation; `--cost-bps` applies one-way equity costs on traded notional (default **0 bps is printed explicitly** as research-optimistic — use `--cost-sensitivity` for the **0 / 5 / 10 bps** ladder on the same gross/turnover path).

**Frozen windows:** [`BACKTEST_PERIODS.md`](BACKTEST_PERIODS.md) / `config.BACKTEST_PERIODS` (`FULL`, `HOLD_OUT`, `COVID`, `BEAR_22`, …).

**Benchmarks compound in parallel on the same holding windows:**

| Benchmark | Role |
|---|---|
| **VTI** | Broad US total market |
| **SPY** | Large-cap S&P 500 |
| **VGT** | Tech-heavy growth sleeve (style stress test) |

**Reported metrics**

- Ending wealth vs start capital
- Total return over the test span
- Annualized volatility of the 3-month period returns
- Annualized Sharpe of those period returns (rf assumed ~3% unless overridden)

Run locally:

```bash
PYTHONPATH=. python3 run_walkforward_backtest.py
```

### 8.2 Live / paper benchmarks

On the Quirk Macro Factor tab / paper ledger:

- Factor strategy cumulative return & value vs cost basis
- Parallel **VOO DCA** sleeve (same weekly dollars, buy-and-hold — no TLH)
- Tax ledger (realized / unrealized)
- Options sleeve P&amp;L is tracked separately and must not raid ETF capital

### 8.3 What “good” means (honest criteria)

Prefer comparing **risk-adjusted** outcomes (Sharpe, drawdown behavior) and **implementation realism** (turnover, wash-sale friction, concentration) against VTI/SPY/VOO — not raw return alone. A model that beats SPY only by taking much more concentrated risk is not automatically a win.

---

## 9. Code map (ETF path)

| Path | Role |
|---|---|
| `main.py` | Weekly orchestration + Supabase export + paper step |
| `config.py` | Universe, tilts, MVO caps, paper/options constants |
| `modules/data_ingestion.py` | ETF returns, Ken French factors, FRED macro |
| `modules/dynamic_beta_estimator.py` | Ridge-seeded Kalman betas |
| `modules/factor_forecaster.py` | LightGBM 3M factor forecasts |
| `modules/fund_scorer.py` | \(\beta^\top f +\) shrunk \(\alpha\) |
| `modules/portfolio_optimizer.py` | Screens + long-only max-Sharpe |
| `modules/paper_portfolio.py` | DCA / HIFO / TLH ledger |
| `modules/etf_orders.py` | Alpaca equity buy proposals |
| `modules/supabase_exporter.py` | Persist predictions / weights |
| `backtest_engine.py` / `run_walkforward_backtest.py` | Historical walk-forward |
| `.github/workflows/weekly_run.yml` | Scheduled production run |

---

## 10. Quick start

```bash
# Weekly production (needs SUPABASE_* and market data access)
python main.py

# Research backtest (production weights; see BACKTEST_PERIODS.md)
PYTHONPATH=. python3 run_walkforward_backtest.py --period FULL
PYTHONPATH=. python3 run_walkforward_backtest.py --period COVID --cost-bps 5
PYTHONPATH=. python3 run_walkforward_backtest.py --period COVID --cost-sensitivity
PYTHONPATH=. python3 run_walkforward_backtest.py --smoke   # fast end-to-end on a small liquid universe

# Options sleeve research backtest (real IV history only)
PYTHONPATH=. python3 run_options_sleeve_backtest.py --from-supabase

# IV refresh / coverage (Wave E)
PYTHONPATH=. python3 scripts/refresh_option_iv_history.py --days 7
PYTHONPATH=. python3 scripts/report_iv_coverage.py

# Options HITL signal board (never places)
PYTHONPATH=. python3 scripts/propose_options_paper.py

# Unit tests (paper HIFO / DCA helpers, IV math when present)
PYTHONPATH=. python3 -m pytest tests/ -q

# Paper book reconcile (model ↔ Supabase ↔ Alpaca)
PYTHONPATH=. python3 scripts/reconcile_paper_book.py
```

Desk / ops: [`DESK_RUNBOOK.md`](DESK_RUNBOOK.md), [`OPTIONS_RISK_OPS.md`](OPTIONS_RISK_OPS.md).  
Paper ledger continuity SQL: `supabase_paper_ledger_continuity.sql` (Wave B).

Secrets used by various paths (never commit values): `SUPABASE_URL`, `SUPABASE_KEY`, Alpaca paper keys (`ALPACA.md`), and for IV history `THETADATA_API_KEY` (`OPTIONS_BOOK.md`).
