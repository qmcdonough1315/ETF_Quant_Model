# Walk-forward period pack (frozen)

Canonical research windows for the ETF selector. Implemented in `config.BACKTEST_PERIODS` and selected via:

```bash
PYTHONPATH=. python3 run_walkforward_backtest.py --period FULL
PYTHONPATH=. python3 run_walkforward_backtest.py --period COVID --cost-bps 5
PYTHONPATH=. python3 run_walkforward_backtest.py --period COVID --cost-sensitivity   # 0/5/10 bps ladder
PYTHONPATH=. python3 run_walkforward_backtest.py --period FULL --equal-weight   # ablation only
PYTHONPATH=. python3 run_walkforward_backtest.py --smoke                       # tiny real universe, COVID window
PYTHONPATH=. python3 run_walkforward_backtest.py --period COVID --artifact-dir artifacts/wf

# Full research card ($100k · 50/50 ETF / options book · VOO + JEPI + 50/50 + VGT)
PYTHONPATH=. python3 scripts/run_walkforward_period_pack.py --cost-bps 5
PYTHONPATH=. python3 scripts/run_walkforward_period_pack.py --smoke --skip-options --periods COVID,BEAR_22
PYTHONPATH=. python3 scripts/render_walkforward_report.py --matrix /opt/cursor/artifacts/walkforward_research_card/period_matrix.json

# Options sleeve research (#10) — requires real option_iv_history (CSV or Supabase)
PYTHONPATH=. python3 run_options_sleeve_backtest.py --from-supabase
PYTHONPATH=. python3 run_options_sleeve_backtest.py --period HOLD_OUT --from-supabase
```

**Research card (allocator view)**

- Book: **$100k** at **50/50** ETF model / options book. Ops may still show $25k sleeve + $25k reserve; research **includes reserve in the options book** (collateral for bets).
- Benchmarks on the same 3M clock: **VOO** (primary), **JEPI** (peer proxy), **VOO_JEPI_50_50** (headline peer), **VGT** (style stress).
- Canonical pack periods: `config.RESEARCH_CARD_PERIODS` (`FULL`, `COVID`, `BEAR_22`, `BULL_23_24`, `HOLD_OUT`).
- Artifact: `period_matrix.json` + `WALKFORWARD_REPORT.md` (consumed by the quirkmacro.com Research tab).

**Rules**

- Default compounding uses production **`Target_Weight`** (Σ wᵢ rᵢ), not equal-weight mean.
- **`HOLD_OUT` is report-only** after lock — do not tune model knobs on it.
- If universe coverage is thin before ~2019, skip or annotate `VOL_18`; prefer `FULL` start when ≥80% of traded names have returns.
- Headline research-card equity cost: **5 bps** one-way (`RESEARCH_EQUITY_COST_BPS_ONE_WAY`). Sensitivity ladder remains **0 / 5 / 10** via `--cost-sensitivity`.
- Options sleeve backtest clamps to **IV history overlap** and refuses to invent IVR when a stress window is uncovered; uncovered windows keep the options column labeled as such and the **combined book falls back to 100% ETF** (no cash drag, no invented IV).

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
