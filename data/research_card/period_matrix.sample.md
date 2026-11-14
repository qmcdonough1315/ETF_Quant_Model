# Walk-forward research card

- Generated: `2026-11-13T23:46:46.130650+00:00`
- Run id: `sample`
- Book: $100,000 at 50/50 ETF model / options book (reserve included in options book)
- ETF costs: 5.0 bps one-way · step 3M · weights `Target_Weight` · rf=0.03
- Headline peer: `VOO_JEPI_50_50`

Allocator view is $100k at 50/50 ETF model / options book. Paper ops may still show $25k options sleeve + $25k margin reserve; research collapses that reserve into the options book (collateral for bets). Idle options cash earns 0 in this card unless noted. THIS FILE IS A SCHEMA SAMPLE with illustrative numbers — not live backtest output.

## Period matrix

| Period | Story | Combined | vs peer | Sharpe | MDD | Hit vs peer | Options |
|---|---|---:|---:|---:|---:|---:|---|
| FULL | Headline span post most modern ETF listings | +42.00% | +4.00% | 0.55 | -18.00% | +55.00% | sample |
| COVID | Crash + rebound | +12.00% | +3.00% | 0.35 | -22.00% | +50.00% | sample |
| BEAR_22 | Inflation / rates bear | -8.00% | +2.00% | 0.10 | -20.00% | +40.00% | sample |
| BULL_23_24 | Narrow leadership / calmer vol regime | +28.00% | +4.00% | 0.70 | -8.00% | +60.00% | sample |
| HOLD_OUT | Report card only — do not tune knobs after locking | +9.00% | +1.00% | 0.45 | -6.00% | +50.00% | sample |

## Benchmarks

- `VOO` — Primary patient beta (primary)
- `JEPI` — Peer proxy — equity + premium (peer_proxy)
- `VOO_JEPI_50_50` — Closest twin to 50/50 ETF + premium stack (headline_peer)
- `VGT` — Style stress (tech concentration) (style_stress)

## Period detail

### FULL — Headline span post most modern ETF listings

- Window: `2019-01-31` → `2025-12-31` · coverage=+92.00%
- ETF sleeve: +46.20% · Sharpe 0.60 · avg turnover 0.250
- Options book: status `sample` · +37.80% · n_trades=12
- VOO: +36.10% · Sharpe 0.50
- JEPI: +34.20% · Sharpe 0.55
- VOO_JEPI_50_50: +38.00% · Sharpe 0.55
- VGT: +45.60% · Sharpe 0.65

### COVID — Crash + rebound

- Window: `2020-01-31` → `2020-12-31` · coverage=+92.00%
- ETF sleeve: +13.20% · Sharpe 0.40 · avg turnover 0.250
- Options book: status `sample` · +10.80% · n_trades=12
- VOO: +7.60% · Sharpe 0.30
- JEPI: +7.20% · Sharpe 0.35
- VOO_JEPI_50_50: +8.00% · Sharpe 0.35
- VGT: +9.60% · Sharpe 0.45

### BEAR_22 — Inflation / rates bear

- Window: `2022-01-31` → `2022-12-31` · coverage=+92.00%
- ETF sleeve: -8.80% · Sharpe 0.15 · avg turnover 0.250
- Options book: status `sample` · -7.20% · n_trades=12
- VOO: -11.40% · Sharpe 0.05
- JEPI: -10.80% · Sharpe 0.10
- VOO_JEPI_50_50: -12.00% · Sharpe 0.10
- VGT: -14.40% · Sharpe 0.20

### BULL_23_24 — Narrow leadership / calmer vol regime

- Window: `2023-01-31` → `2024-06-30` · coverage=+92.00%
- ETF sleeve: +30.80% · Sharpe 0.75 · avg turnover 0.250
- Options book: status `sample` · +25.20% · n_trades=12
- VOO: +20.90% · Sharpe 0.65
- JEPI: +19.80% · Sharpe 0.70
- VOO_JEPI_50_50: +22.00% · Sharpe 0.70
- VGT: +26.40% · Sharpe 0.80

### HOLD_OUT — Report card only — do not tune knobs after locking

- Window: `2024-07-31` → `latest` · coverage=+92.00%
- ETF sleeve: +9.90% · Sharpe 0.50 · avg turnover 0.250
- Options book: status `sample` · +8.10% · n_trades=12
- VOO: +6.65% · Sharpe 0.40
- JEPI: +6.30% · Sharpe 0.45
- VOO_JEPI_50_50: +7.00% · Sharpe 0.45
- VGT: +8.40% · Sharpe 0.55
