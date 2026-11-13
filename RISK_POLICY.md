# Joint risk policy & kill-switch (Wave C)

Allocator-readable one-pager for the **$100k** paper stack. Code mirrors these knobs in `config.py` and `modules/risk_policy.py`. Options propose/place **fail closed** (skip) when the kill-switch is active.

---

## Capital mix

| Sleeve | Share | Dollars |
|---|---|---|
| ETF factor book | 50% | $50k |
| Options / vol | 25% | $25k |
| Cash / margin reserve | 25% | $25k |

Cash is ballast and options stress buffer — **never** pulled from the ETF sleeve to fund premium selling.

---

## Primary de-risk rule (your lock)

**Max combined drawdown before de-risking: 15% of total NAV** from the book high-water mark.

With 25% in cash, a **15% book drawdown** is approximately a **20% decline on the ETF + options risk sleeves** (the 75% that can mark against you), holding cash flat:

\[
0.15 \approx 0.75 \times 0.20
\]

| Level | Combined NAV vs peak | Action |
|---|---|---|
| **Green** | DD &lt; 10% | Normal process |
| **Yellow** | DD ≥ **10%** | Halt **new** short-premium; manage existing; review ETF DCA size |
| **Red (de-risk)** | DD ≥ **15%** | **Kill-switch ON**: no new options risk; pause ETF DCA (or cut to ≤50%); raise cash; desk confirm before resume |
| **Catastrophic** | DD ≥ **25%** | Flatten options where practical; ETF hold-only / discretionary |

Resume only when NAV recovers inside the yellow band **and** desk clears the checklist (VIX, reserve floor, open risk).

---

## Options sleeve loss budget (vs $25k)

Complements the book rule — trip whichever fires first.

| Level | Options MTM P&amp;L | Action |
|---|---|---|
| Soft | **−$5,000 (−20%)** | Halt new short premium |
| Hard | **−$10,000 (−40%)** | Kill-switch; work down risk |

Per-trade stops remain: take profit **50%** of credit; stop ~**2×** credit. Name/sector margin caps unchanged (2% of book / 12% of options+cash).

## Cash reserve floor

Free cash reserve must stay ≥ **50% of $25k = $12,500**. Breach → treat as kill-switch for **new** options risk.

## ETF sleeve (do not fight the 3-month thesis)

Tight stops on the factor book would contradict horizon patience. Use sleeve marks only as **review** triggers unless the **combined 15%** rule fires:

| ETF sleeve vs cost / peak | Action |
|---|---|
| −15% | Review concentrations; no forced liquidation |
| −25% | Optional trim of weakest non-thesis names; still prefer combined rule |

## Measurable market kill inputs (new short premium)

Any one is enough to set kill-switch / skip new credit structures:

- Combined NAV drawdown ≥ **15%** (red)
- Options sleeve P&amp;L ≤ **−$10k**
- Cash reserve &lt; **$12,500**
- Spot **VIX ≥ 35** (soft halt new shorts at VIX ≥ 30 if configured)
- Manual env override: `QUIRK_KILL_SWITCH=1`

---

## What “de-risk” means in code (Phase 1)

1. `modules/risk_policy.py` evaluates inputs → `KillSwitchState`.
2. `build_signal` / `propose_defined_risk_trade` return **skip** when active (fail closed).
3. ETF DCA pause is a **desk/process** flag in summary logs until automation is added; do not silently invent sells.

See also: [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md) · [`OPTIONS_BOOK.md`](OPTIONS_BOOK.md) · [`AGENT_CHECKLIST_1_13.md`](AGENT_CHECKLIST_1_13.md) #3.
