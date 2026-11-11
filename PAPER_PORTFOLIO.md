# Paper Portfolio & Tax-Aware DCA Strategy

## Objective
Simulate (and later execute) a weekly paper account that dollar-cost averages **$1,000** into each Sunday model run’s target weights, while applying a tax-aware exit policy and wash-sale-safe tax-loss harvesting (TLH).

## Capital schedule
- **Inception / catch-up start:** `2026-09-20` model run (inclusive). Earlier runs are ignored.
- On each model `execution_date` on/after inception, schedule fills for the **next business-day open**.
- Deploy **$1,000** across that run’s `Target_Weight` vector (fractional shares allowed).
- In parallel, deploy **$1,000** into **VOO** on the same fill date (benchmark sleeve).
- Track lot-level cost basis, open/close dates, and mark-to-market value.
- The Factor tab shows a week-by-week cumulative return table from inception through the latest run.

## Holding & exit policy (factor sleeve only)
Lots are evaluated once they clear a **~3-month / 91-day** minimum hold:

1. **Loss + model no longer allocates to the ticker** → sell (harvest). Ticker enters a 30-day wash-sale restriction (including substantially identical peers).
2. **Loss + model still allocates** → sell and **immediately rotate** proceeds into a category/factor peer that is not wash-sale restricted, to keep economic exposure while harvesting the loss.
3. **Gain + holding period < 365 days** → hold for long-term treatment, **unless** cumulative harvested losses are large enough to offset the gain **and** the model no longer allocates to the name.
4. **Gain + holding period ≥ 365 days + no allocation** → sell as a long-term gain.
5. **VOO sleeve** is buy-and-hold for benchmark purity (no TLH).

## Dashboard tiles (ETF / Factor tab)
- Factor strategy: cumulative % return, portfolio value, cost basis
- VOO DCA: cumulative % return, portfolio value, cost basis
- Tax ledger: cumulative realized gains/losses, net taxable, cumulative unrealized gains/losses

## Persistence (model repo)
Weekly `main.py` should call `modules/paper_portfolio.py` after portfolio construction and upsert summaries into Supabase table `paper_portfolio` (see `supabase_paper_portfolio.sql`).

Until that table exists / model repo is updated, the Quirk Macro site **replays** historical `factor_predictions.portfolio_weights` with Yahoo daily opens via `src/lib/paper-portfolio.server.ts`.
