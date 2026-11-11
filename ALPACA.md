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

- Python: `modules/alpaca_client.py` — account, positions, option contracts
- Web: `src/lib/alpaca.server.ts` + `src/lib/alpaca.functions.ts` — Summary / Options Book live snapshot

## Migration status

1. **Done:** Options Book + Summary read Alpaca paper account/positions when secrets are present.
2. **Next:** Place/manage defined-risk option orders from the factor×IVR signal engine.
3. **Later:** Drive ETF DCA fills through Alpaca orders while keeping HIFO/TLH lot logic in our ledger (or sync lots from Alpaca fills).
