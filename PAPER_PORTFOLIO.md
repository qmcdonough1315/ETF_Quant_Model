# Paper Portfolio & Tax-Aware DCA Strategy

## Objective
Simulate (and later execute) a weekly paper account that dollar-cost averages **~$3,846.15** (`$50,000 ÷ 13`) into each Sunday model run’s target weights, while applying a tax-aware exit policy, HIFO lot selection, and wash-sale-safe tax-loss harvesting (TLH).

The broader paper book is **$100k**:
- **$50k** ETF factor sleeve (13-week DCA ladder)
- **$25k** short-options / vol sleeve (defined-risk; see `modules/options_sleeve.py`)
- **$25k** cash-engine margin reserve (weekly top yield)

## Capital schedule (ETF sleeve)
- **Inception / catch-up start:** `2026-09-20` model run (inclusive). Earlier runs are ignored.
- On each model `execution_date` on/after inception, schedule fills for the **next business-day open**.
- Deploy **`ETF_TARGET_CAPITAL_USD / DCA_WEEKS`** (~$3,846.15) across that run’s `Target_Weight` vector (fractional shares allowed).
- In parallel, deploy the same weekly amount into **VOO** (benchmark sleeve).
- Undeployed ETF capital during the ramp (`etf_float_remaining`) parks in the cash/yield engine but is **earmarked for future DCA** — not options margin.
- After week 13 the ETF sleeve is fully invested; week 14+ only rotates via tax / model rules.
- Track lot-level cost basis, open/close dates, and mark-to-market value.

## Holding & exit policy (factor sleeve only)
Lots are evaluated once they clear a **~3-month / 91-day** minimum hold. Eligible lots are processed in **least unrealized $ gain first** order (highest cost basis first at a common mark — HIFO):

1. **Loss + model no longer allocates to the ticker** → sell (harvest). Ticker enters a 30-day wash-sale restriction (including substantially identical peers).
2. **Loss + model still allocates** → sell and **immediately rotate** proceeds into a same-category peer that is not wash-sale restricted. When factor betas are available, the substitute is the eligible peer with the smallest Euclidean distance in `(Mkt, SMB, HML, RMW, CMA, WML)` beta space.
3. **Gain + holding period < 365 days** → hold for long-term treatment, **unless** cumulative harvested losses are large enough to offset the gain **and** the model no longer allocates to the name. If selling, least-gain / highest-basis lots go first.
4. **Gain + holding period ≥ 365 days + no allocation** → sell as a long-term gain (again HIFO / least-gain first).
5. **VOO sleeve** is buy-and-hold for benchmark purity (no TLH).

### Example
Week-1 QQQ lot at $100 basis and week-12 QQQ lot at $200 basis: if the model drops QQQ for SPY after both lots are eligible, sell the **$200** lot first so the low-basis winner can keep seasoning toward LTCG when policy allows.

## Dashboard tiles (ETF / Factor tab)
- Factor strategy: cumulative % return, portfolio value, cost basis
- VOO DCA: cumulative % return, portfolio value, cost basis
- Asset-mix benchmark sleeve
- Tax ledger: cumulative realized gains/losses, net taxable, cumulative unrealized gains/losses
- Options / vol sleeve panel (Phase 1 rules + signal examples)
- ETF float remaining during the 13-week ramp

## Persistence (model repo)
Weekly `main.py` calls `modules/paper_portfolio.py` after portfolio construction and inserts that week's summary into Supabase table `paper_portfolio` (see `supabase_paper_portfolio.sql`). The call passes the Kalman beta profiles so a harvest can rotate into the closest same-sleeve peer.

The weekly step still starts from an empty ledger unless a caller passes a prior `Ledger`. Multi-week lot continuity is not loaded back from `paper_lots` yet. The Quirk Macro Factor tab keeps replaying historical `factor_predictions.portfolio_weights` with Yahoo daily opens via `src/lib/paper-portfolio.server.ts`.
