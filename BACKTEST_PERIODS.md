# Walk-forward period pack (frozen)

Canonical research windows for the ETF selector. Implemented in `config.BACKTEST_PERIODS` and selected via:

```bash
PYTHONPATH=. python3 run_walkforward_backtest.py --period FULL
PYTHONPATH=. python3 run_walkforward_backtest.py --period COVID --cost-bps 5
PYTHONPATH=. python3 run_walkforward_backtest.py --period FULL --equal-weight   # ablation only
PYTHONPATH=. python3 run_walkforward_backtest.py --smoke                       # tiny real universe, COVID window
```

**Rules**

- Default compounding uses production **`Target_Weight`** (Σ wᵢ rᵢ), not equal-weight mean.
- **`HOLD_OUT` is report-only** after lock — do not tune model knobs on it.
- If universe coverage is thin before ~2019, skip or annotate `VOL_18`; prefer `FULL` start when ≥80% of traded names have returns.
- Headline cost sensitivity: **0 bps** (default) and **5 / 10 bps** one-way equity (`BACKTEST_EQUITY_COST_BPS_ONE_WAY`).

| ID | Start | End | Step | Tune? | Role |
|---|---|---|---|---|---|
| `FULL` | 2019-01 | 2025-12 | 3M | yes | Headline |
| `HOLD_OUT` | 2024-07 | latest | 3M | **no** | Locked report card |
| `COVID` | 2020-01 | 2020-12 | 3M | yes | Crash tape |
| `BEAR_22` | 2022-01 | 2022-12 | 3M | yes | Rates/inflation bear |
| `VOL_18` | 2018-01 | 2018-12 | 3M | yes | Late-cycle vol (coverage check) |
| `BULL_23_24` | 2023-01 | 2024-06 | 3M | yes | Calm / narrow leadership |
| `THEME_3_6` | 2019-01 | 2025-12 | **6M** | yes | Horizon ablation vs LP 3–6M story |

Wave A minimum: run **`FULL`** (smoke OK if network-limited), then **`COVID`** + **`BEAR_22`** at 0 and 5 bps when data allows.
