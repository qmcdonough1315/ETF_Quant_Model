# Options / Volatility Paper Sleeve (cheat sheet)

Full MBA-friendly narrative: **[`OPTIONS_BOOK.md`](OPTIONS_BOOK.md)**. Broker details: [`ALPACA.md`](ALPACA.md). ETF model: [`README.md`](README.md).

## Role
Express **shorts** and modest **long extension** without changing the long-only ETF MVO. Capital: **$25k** options buying power + **$25k** cash-engine margin reserve.

## Phase 1 universe
Liquid ETF options: SPY, QQQ, IWM, and major sector ETFs (`PHASE1_OPTIONABLE_ETFS` in `modules/options_sleeve.py`).

## Signal map (factor composite × IV Rank)
| Regime | Condition | Structure |
|---|---|---|
| Q1 | High composite, IVR ≥ 30% (prefer ≥ 50%) | Bull put spread · ~25Δ · 30–45 DTE |
| Q2 | Low composite, IVR elevated | Bear call spread · ~25Δ · 30–45 DTE |
| Q3 | Neutral composite, IVR elevated | Iron condor · ~18Δ wings |
| Q4 | IVR < 30% | Skip short premium |

## Risk controls
- Defined-risk only (no naked shorts in Phase 1)
- Take profit at 50% of credit; stop at 2× credit
- Per-name margin ≤ 2% of the $100k book; per-sector ≤ 12% of options+cash
- Options stress must fit inside the $25k cash reserve
- Never pull capital from the ETF sleeve

## IV Rank data (live, no demo)
- **Definition (v1):** ~30 DTE ATM IV = average of call and put Black–Scholes IVs from mid prices.
- **Bootstrap:** ThetaData free-tier EOD (`run_iv_bootstrap.py`) → `option_iv_history` (see `supabase_option_iv_history.sql`).
- **Ongoing:** Alpaca ATM IV snapshots append to the same table (source differs); desk must never invent IVR.
- **Composite:** Cross-sectional z-score of Phase 1 ETF `Total_Expected_Return_3M` exported as `factor_predictions.data_type = options_composite`.

## Code
- Python: `modules/options_sleeve.py`, `modules/options_orders.py`, `modules/thetadata_iv_bootstrap.py`, `modules/options_composite.py`, constants in `config.py`
- Dashboard: `OptionsSleevePanel` + `OptionsTradeDesk` + `options-sleeve-rules.ts` / `options-orders.ts`
