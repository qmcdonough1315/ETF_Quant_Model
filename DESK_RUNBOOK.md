# Sunday desk runbook (options sleeve)

**Design choice (Wave E / #9): human-in-the-loop.**  
`main.py` exports ETF weights + options composites only. It does **not** auto-propose or auto-place options. Paper mleg place requires desk confirmation (`confirm=true` on paper-api).

Related: [`OPTIONS_BOOK.md`](OPTIONS_BOOK.md) · [`OPTIONS_RISK_OPS.md`](OPTIONS_RISK_OPS.md) · [`RISK_POLICY.md`](RISK_POLICY.md) · [`ALPACA.md`](ALPACA.md)

---

## Boundary (no silent automation)

| Step | Owner | Automation? |
|---|---|---|
| Weekly factor model + composites → Supabase | `main.py` / Actions | Yes |
| Refresh ATM IV → `option_iv_history` | Actions IV step / `scripts/refresh_option_iv_history.py` | Yes (append only; no invent) |
| Read IVR + composites → structure map | Desk / `scripts/propose_options_paper.py` | Assistive board only |
| Chain pick → credit limit proposal | Options Trade Desk (web) | Human triggers |
| Place paper mleg | Desk with `confirm=true` | **Never** from `main.py` |

Optional CLI (proposals / skips only — never places):

```bash
PYTHONPATH=. python3 scripts/propose_options_paper.py
PYTHONPATH=. python3 scripts/propose_options_paper.py --tickers SPY,QQQ,XLK --out /tmp/options_board.json
```

---

## Sunday checklist

1. **Kill-switch** — Read [`RISK_POLICY.md`](RISK_POLICY.md). If yellow/red or `QUIRK_KILL_SWITCH=1`, **stop** (no new short premium).
2. **IV freshness** — Confirm weekly IV refresh ran (or run `scripts/refresh_option_iv_history.py --days 7`). Missing IVR → **skip** that ticker (fail closed).
3. **Composites** — Factor tab / Supabase `options_composite` for Phase 1 names.
4. **Signal board** — Run `propose_options_paper.py` or open Options Sleeve panel. Q4 / missing IV / kill-switch = skip.
5. **Ops filters** — Ex-div / pin rules ([`OPTIONS_RISK_OPS.md`](OPTIONS_RISK_OPS.md)); liquidity caps (sector vs SPY/QQQ/IWM).
6. **Propose** — Options Trade Desk: build mleg, check credit limit haircut, size vs name/sector caps.
7. **Confirm place** — Paper only, `confirm=true`. Do not place live.
8. **Log** — Note skips (IVR, liquidity, ex-div, kill-switch) in the desk session notes.

---

## Phase 1 behavior (language lock)

- **Sell** elevated IVR credit structures (prefer IVR ≥ 50; gate IVR ≥ 30).
- **Stand aside** when IV is cheap (IVR &lt; 30) — Phase 1 does **not** buy undervalued vol.
- Phase 2 long-vol ideas are parked in docs only — not enabled in code.
