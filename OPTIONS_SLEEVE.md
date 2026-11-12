# Options / Volatility Paper Sleeve

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

## Code
- Python: `modules/options_sleeve.py`, `modules/options_orders.py`, constants in `config.py`
- Dashboard: `OptionsSleevePanel` + `OptionsTradeDesk` + `options-sleeve-rules.ts` / `options-orders.ts`
