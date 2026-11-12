# Alpaca paper ledger

Quirk Macro uses **Alpaca paper** (`https://paper-api.alpaca.markets`) as the live brokerage ledger for account equity, cash, buying power, and option/equity positions.

## Secrets (never commit)

| Env var | Purpose |
|---|---|
| `ALPACA_API_KEY_ID` | Paper API key ID |
| `ALPACA_API_SECRET_KEY` | Paper API secret |
| `ALPACA_API_BASE_URL` | Optional; defaults to `https://paper-api.alpaca.markets` |

Aliases `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` / `APCA_API_BASE_URL` are also accepted.

## Code

- Python: `modules/alpaca_client.py` — account, positions, option contracts, `place_mleg_order`
- Python: `modules/options_orders.py` — signal → defined-risk mleg proposal (credit `limit_price` is **negative**)
- Web: `src/lib/alpaca.server.ts` + `src/lib/alpaca.functions.ts` — ledger, propose, place
- Web: `src/lib/options-orders.ts` — pure contract picker + mleg payload builder

## Orders (paper only)

`POST /v2/orders` with `order_class: mleg`. Credit spreads **must** use a negative `limit_price`. Placement is refused unless the base URL is `paper-api.alpaca.markets` and `confirm=true`.

## Migration status

1. **Done:** Options Book + Summary read Alpaca paper account/positions when secrets are present.
2. **Done:** Propose/place defined-risk option orders from the factor×IVR signal engine (Options Book paper trade desk).
3. **Done (buys):** Drive weekly ETF DCA fills through Alpaca paper equity orders (`modules/etf_orders.py` + `place_equity_order`). HIFO/TLH sell path stays in the paper ledger; fills map to lots via `lot_from_alpaca_fill`. VOO sleeve optional on propose. Sells / full TLH broker execution are still ledger-side.
