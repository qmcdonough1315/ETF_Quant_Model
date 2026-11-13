# Options Book (Volatility Paper Sleeve)

How the $25k defined-risk options sleeve works: signals, structures, IV Rank, execution, and how it relates to the ETF factor model.

**Audience:** Comfortable with Black–Scholes pricing and the idea of \(\Delta\), \(\Theta\), \(\mathcal{V}\) (vega), but not necessarily a full-time vol trader. ETF factor context: [`README.md`](README.md). Ops cheat sheet: [`OPTIONS_SLEEVE.md`](OPTIONS_SLEEVE.md). Broker wiring: [`ALPACA.md`](ALPACA.md).

---

## 1. Why a separate options book?

The ETF engine is **long-only**. It cannot express “this sector looks rich” with a short stock position. The options sleeve sits **outside** the MVO:

- **$25k** options buying power for defined-risk credit structures
- **$25k** cash-engine reserve that must cover options stress
- **Never** pulls capital from the $50k ETF sleeve

Economic jobs:

| Goal | How options help |
|---|---|
| Modest long extension | Bull put credit spreads when the factor view is bullish *and* option premium is rich |
| Short / hedge expression | Bear call credit spreads when the factor view is bearish *and* premium is rich |
| Range / mean-reversion vol | Iron condors when the view is neutral but implied vol is elevated |
| Avoid selling cheap insurance | Skip when IV Rank is low |

Phase 1 underlyings (`PHASE1_OPTIONABLE_ETFS`): **SPY, QQQ, IWM**, and the major Select Sector SPDRs (**XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC**).

---

## 2. Black–Scholes refresher (what we actually use)

For a European option, Black–Scholes maps inputs \((S, K, T, r, \sigma, \text{call/put})\) to a model price. In markets we usually observe the **price** and solve for \(\sigma\) — that \(\sigma\) is **implied volatility (IV)**.

In this repo:

- We take **mid** = \((\text{bid}+\text{ask})/2\) (fallback to close if needed) — `modules/black_scholes_iv.py`.
- We invert BS numerically for call and put IVs separately.
- Daily **ATM IV** ≈ average of those two IVs for strikes nearest spot, on the expiry closest to **~30 calendar days** (window 20–45 DTE). See `modules/thetadata_iv_bootstrap.py`.

Why average call and put? Put–call parity and microstructure noise mean one side can be briefly stale; averaging ATM mids is a simple robust ATM vol estimate for ranking, not a full surface model.

**Delta (\(\Delta\))** here is used as a *moneyness shortcut*: ~25Δ short strikes for directional credit spreads, ~18Δ for iron-condor wings. You do not need a full Greeks desk to use the map — higher |Δ| means closer to the money and more directional risk.

---

## 3. Implied volatility vs IV Rank (the missing vocabulary)

### 3.1 IV is a level; IV Rank is a percentile-like score

- **IV** answers: “What volatility is the option market pricing *right now*?”
- **IV Rank (IVR)** answers: “Where is today’s IV relative to its own recent history?”

Classic definition used in `modules/iv_rank.py`:

\[
\text{IVR} = 100 \times \frac{\text{IV}_{\text{now}} - \text{IV}_{\min}}{\text{IV}_{\max} - \text{IV}_{\min}}
\]

over a lookback window (about one year / ~252 sessions of stored ATM IV).

| IVR | Interpretation for *sellers* of premium |
|---|---|
| Near 0 | IV is near its recent low — insurance is cheap; we **do not** sell |
| ~50 | Middle of the recent range |
| Near 100 | IV near recent high — rich premium; selling is more attractive *all else equal* |

**Important:** High IVR does **not** mean “the market will fall.” It means option prices are expensive versus their own past. We still require a factor view (below) before choosing *which* credit structure.

Config gates (`config.py`):

- Skip short premium if IVR &lt; **30** (`OPTIONS_IVR_MIN`)
- Prefer setups with IVR ≥ **50** (`OPTIONS_IVR_PREFERRED`)

### 3.2 Where the history comes from

No demo / synthetic IVR. History lives in Supabase table `option_iv_history` (`supabase_option_iv_history.sql`).

Bootstrap from ThetaData free-tier EOD:

```bash
pip install thetadata pandas numpy supabase python-dotenv
PYTHONPATH=. python3 run_iv_bootstrap.py --tickers SPY --no-upsert   # smoke
PYTHONPATH=. python3 run_iv_bootstrap.py                             # Phase 1 + upsert
# or upsert a CSV later:
PYTHONPATH=. python3 scripts/upsert_iv_history_csv.py data/option_iv_history/atm_iv_bootstrap.csv
```

Requires `THETADATA_API_KEY`, and `SUPABASE_URL` / `SUPABASE_KEY` for upsert. Ongoing snapshots can append with a different `source` field; desk rules forbid inventing IVR when history is missing.

---

## 4. The second axis: factor composite

Weekly, the ETF model produces `Total_Expected_Return_3M` for the universe. For Phase 1 names we convert that cross-section into a **z-score** (`modules/options_composite.py`):

\[
z_i = \frac{r_i - \bar r}{\sigma_r}
\]

clipped to about ±3. That score is dimensionless and comparable week to week.

| Composite \(z\) | Plain reading |
|---|---|
| \(z \ge +0.5\) | Relatively bullish in this week’s Phase 1 cross-section |
| \(z \le -0.5\) | Relatively bearish |
| \(|z| &lt; 0.5\) | Neutral / middle of the pack |

Exported as `factor_predictions` rows with `data_type = options_composite` for the web desk.

---

## 5. Regime map → structures

`modules/options_sleeve.py` implements a quadrant map:

| Regime | Condition | Structure | Short Δ target | DTE |
|---|---|---|---|---|
| Q1 | High composite, IVR ≥ 30 (prefer ≥ 50) | **Bull put spread** | ~0.25 | 30–45 |
| Q2 | Low composite, IVR elevated | **Bear call spread** | ~0.25 | 30–45 |
| Q3 | Neutral composite, IVR elevated | **Iron condor** | ~0.18 wings | 30–45 |
| Q4 | IVR &lt; 30 | **Skip** | — | — |

### 5.1 What each structure is (MBA picture)

**Bull put credit spread**  
Sell a put closer to the money; buy a lower put (same expiry). Collect credit. Profit if the underlying stays **above** the short put. Max loss = width − credit (defined risk). This is how we lean long *without* buying shares in the options sleeve.

**Bear call credit spread**  
Sell a call; buy a higher call. Profit if the underlying stays **below** the short call. Defined-risk short / rich-valuation expression.

**Iron condor**  
Bull put spread + bear call spread (same expiry). Profit in a **range**; two credits, two defined wings. Used when the factor view is neutral but premium is worth selling.

All Phase 1 trades are **defined-risk** (no naked shorts).

### 5.2 Risk / exit rules

| Control | Setting |
|---|---|
| Take profit | 50% of credit received |
| Stop | ~2× credit (loss ≈ 2× premium) |
| Per-name margin | ≤ 2% of the $100k book |
| Per-sector margin | ≤ 12% of options+cash ($50k) |
| Stress | Must fit inside the $25k cash reserve |
| Capital wall | Never fund from the ETF sleeve |

Contract sizing (`size_spread_contracts`): \(\text{qty} = \lfloor \text{budget} / ((\text{width}-\text{credit})\times 100) \rfloor\).

---

## 6. Execution path

```text
ETF model scores → Phase 1 z-score composites
        ↓
IV history → IV Rank per ticker
        ↓
classify_regime → OptionsSignal
        ↓
options_orders: pick expiry / strikes from chain → TradeProposal
        ↓
Alpaca paper mleg order (credit limit_price is negative)
```

Key modules:

| Module | Role |
|---|---|
| `modules/options_sleeve.py` | Regime map, sizing helpers, Phase 1 universe |
| `modules/options_composite.py` | Cross-sectional z-scores |
| `modules/options_orders.py` | Signal + chain → multi-leg proposal |
| `modules/black_scholes_iv.py` | Mid → BS IV |
| `modules/iv_rank.py` | IVR from stored history |
| `modules/thetadata_iv_bootstrap.py` | ~30 DTE ATM IV history pull |
| `modules/alpaca_client.py` | Paper account / `place_mleg_order` |
| `run_iv_bootstrap.py` | CLI for history bootstrap |

Web desk (Quirk Macro repo): Options Book UI proposes/places using the same rules (`options-orders.ts`, `options-sleeve-rules.ts`). Paper-only placement requires `confirm=true` against `paper-api.alpaca.markets`.

---

## 7. How we evaluate the options book

The options sleeve is **younger** than the ETF walk-forward. Treat evaluation in layers:

### 7.1 Signal hygiene (must-pass)

- IVR computed only from **real** ATM history (no placeholders).
- Structures respect IVR gate and defined-risk constraints.
- Margin and sector caps bind before size.

### 7.2 Paper trading process P&amp;L

- Track credit received, max loss at entry, exit at 50% profit or 2× stop.
- Compare sleeve equity / buying power on Alpaca paper vs the $25k notional.
- Monitor whether losses ever pressure the $25k cash reserve rule.

### 7.3 What we do *not* claim yet

There is **no** multi-year walk-forward for options comparable to `run_walkforward_backtest.py` for ETFs. Until that exists, options results are **paper-process evidence**, not a published edge study. When a formal options backtest is added, it should:

1. Reconstruct IVR with point-in-time history only.
2. Use the same regime map and DTE/Δ rules.
3. Include friction (bid/ask, early exits) and the capital wall vs the ETF book.
4. Benchmark against “always skip,” “sell 25Δ puts every month,” and buy-and-hold SPY *on a risk-matched notional* — not raw dollar P&amp;L alone.

### 7.4 Coupling check with the ETF model

A useful qualitative test: when the factor book is heavily long a sector, does Q1 (bull puts) dominate that name while Q2 stays scarce? When composites flip negative with high IVR, do bear calls appear? The options book should **amplify** the factor view under rich vol — not fight the long-only book with unmanaged directional shorts.

---

## 8. Worked mini-example

Suppose for XLK this week:

- Model `Total_Expected_Return_3M` is high vs other Phase 1 names → composite \(z \approx +1.2\)
- ATM IV history shows IVR ≈ 55

Regime → **Q1** → propose a **30–45 DTE bull put spread** ~25Δ short put, long put further OTM, size so max loss ≤ name/sector caps. If IVR were 20 instead, regime → **Q4** and we skip even though the factor view is bullish — we refuse to sell cheap insurance.

---

## 9. Related files & commands

```bash
# Bootstrap / refresh IV history (Phase 1)
PYTHONPATH=. python3 run_iv_bootstrap.py

# Upsert an existing CSV
PYTHONPATH=. python3 scripts/upsert_iv_history_csv.py

# IV / IVR unit tests
PYTHONPATH=. python3 -m pytest tests/test_black_scholes_iv.py -q
```

SQL: `supabase_option_iv_history.sql` (table + `option_iv_rank_latest` view).

Constants: `OPTIONS_*` block in `config.py`.
