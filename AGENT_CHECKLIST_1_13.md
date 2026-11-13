# Cloud-agent checklist: items #1–#13

Use this tomorrow: open **one Cloud Agent per item** (or tightly coupled pair), paste the **Prompt** block, and require the **Done when** checks before merging.

Repo: `qmcdonough1315/ETF_Quant_Model`  
Related docs: `README.md`, `OPTIONS_BOOK.md`, `EXECUTIVE_SUMMARY.md`, `PAPER_PORTFOLIO.md`, `ALPACA.md`

**Working rule for every agent:** no demo/synthetic IVR or fake fills; prefer fixing the production path over adding a parallel “research-only” hack; open a PR on a `cursor/<name>-c180` branch; report evidence (tests, logs, before/after).

---

## Suggested order (dependency-aware)

| Wave | Items | Why |
|---|---|---|
| A — Evidence integrity | **#1**, then **#14-style period pack** (below) | Don’t trust performance until weights/costs match production |
| B — Paper truth | **#2**, **#5**, **#6**, **#7** | Closed ledger + reconcile + secrets |
| C — Risk policy | **#3**, then wire into desk/runbooks | Kill-switch before automating options |
| D — Realism | **#4**, **#10** | Costs + options backtest |
| E — Options production | **#8**, **#9**, **#11**, **#12**, **#13** | IV refresh, automation boundary, ops policies |

You can parallelize within a wave; avoid parallel agents editing the same core files (`main.py`, `paper_portfolio.py`, `run_walkforward_backtest.py`) without stacking PRs.

---

## #1 — Walk-forward must use production weights (+ costs hook)

**Problem:** `run_walkforward_backtest.py` uses equal-weight mean of picks; `backtest_engine.py` uses `Target_Weight`. Research ≠ traded book.

**Done when**
- [ ] Walk-forward period return = Σ wᵢ rᵢ with same weights production would have used at rebalance
- [ ] Optional flag for equal-weight ablation still available
- [ ] Pluggable cost model stub (bps one-way equity; documented defaults)
- [ ] Unit/smoke test: weighted return ≠ mean when weights unequal
- [ ] Printed summary still vs VTI/SPY/VGT (or VOO)

**Prompt (paste into a new Cloud Agent)**

```text
Repo: qmcdonough1315/ETF_Quant_Model. Work on a new cursor/*-c180 branch off main.

Fix item #1 from AGENT_CHECKLIST_1_13.md: make run_walkforward_backtest.py use production Target_Weight (Σ w_i r_i) to compound each holding window, matching score_and_rank_funds / portfolio_optimizer. Keep an explicit --equal-weight ablation flag. Add a simple transaction-cost hook (bps on turnover or rebalance notional; default configurable in config.py; can be 0). Align column naming (stop calling 3M windows “6M” if that is stale). Add a small test that weighted ≠ mean. Run a short walk-forward smoke if data/network allows; otherwise document how to run. Open/update PR with before/after explanation.
```

---

## #2 — Persist & reload paper lots / wash-sales

**Problem:** `run_paper_portfolio_step` can start from empty `Ledger`; `main.py` passes `recent_wash_sales = []`. Multi-week tax/DCA state is not closed.

**Done when**
- [ ] Prior lots (+ wash restrictions) load from Supabase (or documented store) before `process_week`
- [ ] After week, lots/restrictions write back
- [ ] `main.py` passes real restricted tickers into `score_and_rank_funds`
- [ ] Test: two sequential weeks do not reset cost basis
- [ ] Docs in `PAPER_PORTFOLIO.md` updated

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch.

Implement item #2 in AGENT_CHECKLIST_1_13.md: multi-week paper ledger continuity. Load prior lots / wash-sale restrictions from Supabase (extend schema if needed; ship SQL migration file). Persist after process_week. Wire main.py so restricted_tickers is not a hard-coded []. Add tests for two-week continuity. Update PAPER_PORTFOLIO.md. Do not invent demo lots—use empty state only when DB has no history. PR with schema + code + test evidence.
```

---

## #3 — Joint stress / kill-switch policy (ETF + options)

**Problem:** Long factor ETFs and short premium can fail together; no written combined loss budget or options halt rules in code/docs.

**Done when**
- [ ] One-pager policy: max ETF drawdown, max options sleeve loss vs $25k, reserve floor, halt conditions (e.g. IVR spike, gap, VIX threshold—pick measurable ones)
- [ ] Constants in `config.py` (or `RISK_POLICY.md` + config mirrors)
- [ ] `options_sleeve` / order path can return `skip` when kill-switch active (even if switch is env/config flag initially)
- [ ] Exec summary or OPTIONS_BOOK links to the policy

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch.

Implement item #3 from AGENT_CHECKLIST_1_13.md: joint ETF+options risk policy and kill-switch. Write RISK_POLICY.md (allocator-readable, ≤1 page body) covering combined drawdown budget, $25k options loss budget, cash reserve floor, and halt/resume rules. Add matching config knobs. Wire options signal/order construction to honor an active kill-switch (fail closed to skip). Link from EXECUTIVE_SUMMARY.md and OPTIONS_BOOK.md. No fake market data. PR with the policy and the code gate.
```

---

## #4 — Transaction costs / slippage realism

**Problem:** Backtests/paper can ignore equity spreads and options bid/ask; carry looks too clean.

**Done when**
- [ ] Equity walk-forward applies configurable bps (build on #1 hook)
- [ ] Options proposal path documents mid→limit conservatism (already negative credit limit; tighten if needed)
- [ ] Sensitivity table in docs or script output: 0 / 5 / 10 bps equity
- [ ] No silent zero-cost assumption in the “canonical” backtest entrypoint

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. Prefer stacking on the #1 PR branch if merged/available; else branch from main and note dependency.

Item #4 in AGENT_CHECKLIST_1_13.md: make costs first-class. Extend the walk-forward cost hook with clear config defaults, turnover-based equity costs, and a small CLI/report comparing 0/5/10 bps. For options, audit modules/options_orders.py so limit_price / credit assumptions are conservative vs mid and documented in OPTIONS_BOOK.md. Add tests for cost application. PR with a short “how costs affect headline Sharpe” note.
```

---

## #5 — Weekly reconcile: model ↔ Supabase ↔ Alpaca

**Problem:** Three sources of truth can drift; no automated exception report.

**Done when**
- [ ] Script or module: target weights vs Alpaca ETF positions vs last Supabase publish
- [ ] Options: open Alpaca mleg/positions vs last proposals (best-effort)
- [ ] Non-zero exit or clear `FAIL` lines on material drift
- [ ] Runnable in CI or documented weekly manual command
- [ ] README / PAPER_PORTFOLIO points to it

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model (and quirk_macro_web_dev only if required for types). New cursor/*-c180 branch.

Build item #5: a weekly reconciliation tool (e.g. scripts/reconcile_paper_book.py) that compares (1) latest model Target_Weight / Supabase factor_predictions portfolio_weights, (2) Alpaca paper equity positions, (3) optional options positions. Use existing alpaca_client + supabase env vars; presence-check secrets, never print them. Emit a human-readable drift report and a non-zero exit on material breaches (thresholds in config). Document how to run. PR with a dry-run against paper if secrets exist, else a mocked unit test.
```

---

## #6 — Close TLH/HIFO sell execution path

**Problem:** Buys closer to Alpaca paper; sells often ledger-only → broker ≠ tax ledger.

**Done when**
- [ ] Design choice documented: auto-place sells vs propose-only
- [ ] If auto: paper sell orders from harvest events, mapped into lots
- [ ] If propose-only: desk checklist + API to place with `confirm=true`
- [ ] Wash-sale peers still respected
- [ ] Tests for “harvest event → order intent” without requiring live broker

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch. Read ALPACA.md and PAPER_PORTFOLIO.md first.

Item #6: close the HIFO/TLH sell path. Prefer propose-and-confirm paper sells first (safer), with a clear flag for auto-place on paper only. Map harvest events in paper_portfolio to etf order intents; reuse place_equity_order patterns. Keep wash-sale / peer rules intact. Update ALPACA.md migration status. Tests for intent construction. Do not enable live (non-paper) trading. PR with evidence.
```

---

## #7 — Fix Actions Alpaca secret naming

**Problem:** `.github/workflows/weekly_run.yml` uses `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`; client expects `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` (and aliases). Sunday runs may skip brokerage silently.

**Done when**
- [ ] Workflow exports the names `alpaca_client` actually reads
- [ ] Short comment in workflow lists required GitHub secrets
- [ ] `ALPACA.md` matches
- [ ] Optional: workflow step that asserts env presence without printing values

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch.

Item #7: fix GitHub Actions Alpaca env alignment in .github/workflows/weekly_run.yml with modules/alpaca_client.py and ALPACA.md. Map secrets to ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (keep backward-compatible aliases if cheap). Add a presence-only check step (no value printing). Update docs. PR.
```

---

## #8 — IV Rank production refresh + fail-closed + XLRE gaps

**Problem:** Bootstrap exists; weekly job doesn’t refresh IV; desk must not invent IVR; XLRE may be short history.

**Done when**
- [ ] Documented/scheduled path to append recent EOD ATM IV (ThetaData and/or Alpaca)
- [ ] Options signal path **skips** ticker if IVR unavailable (fail closed)
- [ ] XLRE (and any sparse names) backfill script or one-off agent run logged
- [ ] `OPTIONS_BOOK.md` ops section updated

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch. Secrets may include THETADATA_API_KEY, SUPABASE_URL, SUPABASE_KEY (presence only).

Item #8: productionize IV Rank. (1) Fail-closed: build_signal / options_orders skip when IVR missing. (2) Add a small refresh path (script or weekly workflow step) to append recent ATM IV into option_iv_history—no demo data. (3) If Supabase access works, report row counts per Phase 1 ticker and backfill XLRE gaps vs SPY dates where feasible; else write CSV artifact and say SQL/upsert still needed. Evidence in PR + artifacts.
```

---

## #9 — Document or automate options propose/place vs `main.py`

**Problem:** Composites export from weekly model; mleg propose/place is desk-driven—boundary unclear.

**Done when**
- [ ] Explicit choice in docs: human-in-the-loop **or** automated paper propose
- [ ] If automate: gated by kill-switch (#3), IVR fail-closed (#8), margin caps
- [ ] If HITL: checklist in OPTIONS_BOOK / desk runbook; `main.py` unchanged but links clear
- [ ] No silent partial automation

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model (touch quirk_macro_web_dev only if desk copy needed). New cursor/*-c180 branch.

Item #9: clarify options execution boundary. Default recommendation: keep human-in-the-loop paper propose/place, but add a DESK_RUNBOOK.md (or OPTIONS_BOOK section) for Sunday: read composites → compute IVR → propose → confirm. Optionally add a --propose-options-paper flag path that only creates proposals (no place) behind kill-switch + IVR fail-closed. Do not auto-place without confirm=true paper guards. PR with the chosen design and minimal code if needed.
```

---

## #10 — Point-in-time options sleeve backtest (even crude)

**Problem:** No multi-year options walk-forward comparable to ETF research.

**Done when**
- [ ] Script replays Phase 1 rules with point-in-time IV history only
- [ ] Applies 50% profit / 2× stop heuristics (documented simplifications OK)
- [ ] Benchmarks: always-skip; naive short-put; risk-matched SPY hold
- [ ] Honest limitations section (no fantasy fills)
- [ ] Depends on #8 history quality

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch. Depends on option_iv_history (Supabase or local CSV).

Item #10: build a crude but honest point-in-time options sleeve backtest (e.g. run_options_sleeve_backtest.py). Use stored ATM IV → IVR, factor composite proxy if available or a documented stand-in, same Q1–Q4 map, DTE/Δ rules as simplified proxies if chain history is missing (state assumptions clearly). Include 50% take-profit and 2× stop. Compare to always-skip and a naive baseline. Use the period menu in AGENT_CHECKLIST_1_13.md § Walk-forward periods. PR + artifact metrics; no demo IV.
```

---

## #11 — Assignment / pin / ex-div policy

**Problem:** Short options on ETFs face early exercise / pin / distribution risk; policy not codified.

**Done when**
- [ ] `OPTIONS_RISK_OPS.md` or section in OPTIONS_BOOK: no holds into ex-div when short calls; max DTE into pin risk; roll/close rules
- [ ] Pre-trade checks in `options_orders.py` where data allows (else hard doc + desk checklist)
- [ ] Kill-switch interaction noted

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch.

Item #11: codify assignment/pin/ex-div policy for Phase 1 ETF short premium. Write clear ops rules; implement any enforceable pre-trade guards in options_orders.py (e.g. block short calls when known ex-div within N days if feed available; otherwise document desk obligation). Link from OPTIONS_BOOK.md. PR.
```

---

## #12 — Liquidity & capacity caps by name

**Problem:** Margin caps exist; open interest / spread / max contracts by ticker mostly don’t.

**Done when**
- [ ] Per-ticker max contracts / max % of OI (if OI available) / max bid-ask width filter
- [ ] SPY/QQQ/IWM looser than thin sector names (config table)
- [ ] Proposal skips with reason when liquidity fails
- [ ] Docs updated

**Prompt**

```text
Repo: qmcdonough1315/ETF_Quant_Model. New cursor/*-c180 branch.

Item #12: add liquidity/capacity filters to options proposals. Config table for Phase 1 tickers (max contracts, max mid spread width, optional min open interest). Enforce in options_orders.py with skip reasons. Stricter defaults for sector ETFs than SPY/QQQ/IWM. Tests with mock quotes. Update OPTIONS_BOOK.md. PR.
```

---

## #13 — Align LP story with Phase 1 “cheap IV” behavior

**Problem:** Thesis mentions under- *and* over-priced IV; code sells rich / skips cheap—does not buy undervalued vol.

**Done when**
- [ ] EXECUTIVE_SUMMARY + OPTIONS_BOOK state Phase 1 clearly: harvest rich IVR; stand aside when cheap
- [ ] Optional “Phase 2: long vol when IVR low + …” parked as future work—not implied live
- [ ] Desk UI copy checked if in quirk_macro_web_dev (only if agent has that repo)

**Prompt**

```text
Repos: qmcdonough1315/ETF_Quant_Model (and quirk_macro_web_dev if available). New cursor/*-c180 branch.

Item #13: align investor/desk language with Phase 1 code. Audit EXECUTIVE_SUMMARY.md, OPTIONS_BOOK.md, OPTIONS_SLEEVE.md, and web desk copy for claims about buying cheap IV. Phase 1 = sell elevated IVR credit structures; skip IVR < 30; no long-vol book yet. Add a short “Phase 2 candidates” note without enabling code. PR.
```

---

## Walk-forward periods (for #1 and #10 agents)

Pick **one canonical full sample** plus **stress slices**. Freeze them in `config.py` or a `BACKTEST_PERIODS.md` so agents don’t freestyle.

### Recommended menu

| ID | Window (month-end rebalance) | What it tests |
|---|---|---|
| `FULL` | **2019-01 → 2025-12** (or latest settled month) | Headline OOS-ish span post most modern ETF listings |
| `HOLD_OUT` | **2024-07 → latest** | True report card; **do not tune** knobs on this after locking |
| `COVID` | **2020-01 → 2020-12** | Crash + rebound; factor + vol together |
| `BEAR_22` | **2022-01 → 2022-12** | Inflation / rates bear; value-growth rotation |
| `VOL_18` | **2018-01 → 2018-12** | Late-cycle vol spike (if universe coverage OK) |
| `BULL_23_24` | **2023-01 → 2024-06** | Narrow leadership / calm-ish vol carry regime |
| `THEME_3_6` | rolling **6-month** hold ablation vs 3-month | Matches LP “3–6 months” narrative |

**Prompt add-on (append to #1 or #10 agent)**

```text
Also add BACKTEST_PERIODS.md (and optional config dict) with the period menu from AGENT_CHECKLIST_1_13.md. Run at least FULL (smoke) and COVID + BEAR_22 if data allows. Reserve HOLD_OUT for reporting only—do not fit hyperparameters on it in this task. Publish a markdown metrics table as an artifact.
```

### How to choose tomorrow morning

1. Run **#1** on `FULL` + `COVID` + `BEAR_22` first (weighted, with 0 and 5 bps).  
2. Lock **`HOLD_OUT`** dates in writing before any further tuning.  
3. Only after IV history quality (#8), run **#10** on the same stress IDs.  
4. If ETF coverage is thin before ~2019 for your sleeve-heavy universe, **do not** force 2015—start when ≥80% of the traded universe has returns (agent should measure and document).

---

## Tracker (copy into Linear/Notion if you want)

| ID | Owner agent | PR | Status |
|---|---|---|---|
| #1 Walk-forward weights | | | |
| #2 Ledger persistence | | | |
| #3 Kill-switch policy | | | |
| #4 Costs | | | |
| #5 Reconcile | | | |
| #6 TLH sells | | | |
| #7 Actions secrets | | | |
| #8 IV refresh + XLRE | | | |
| #9 Desk boundary | | | |
| #10 Options backtest | | | |
| #11 Assignment/ex-div | | | |
| #12 Liquidity caps | | | |
| #13 LP language | | | |
| Periods pack | | | |
