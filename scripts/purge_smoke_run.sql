-- =============================================================================
-- PURGE: SMOKE-20261113-1453-ET  (weekly model smoke on 2026-11-13)
-- =============================================================================
-- America/New_York wall clock start: 2026-11-13 14:54:03 ET
-- Supabase created_at (UTC):         2026-11-13T19:54:22.163964+00:00
-- execution_date key:                2026-11-13
-- factor_predictions id range:       366 .. 410  (45 rows)
--
-- ████████████████████████████████████████████████████████████████████████████
-- ██  DO NOT RUN ANY DELETE/TRUNCATE ON option_iv_history                   ██
-- ██  DO NOT TOUCH option_iv_rank_latest (view)                             ██
-- ██  Pre/post smoke IV row count was unchanged: 3501                       ██
-- ████████████████████████████████████████████████████████████████████████████
--
-- Review the SELECT audits below, then run the DELETEs only if they match.
-- Prefer running inside a transaction and COMMIT only after row counts look right.
-- =============================================================================

begin;

-- ---------- AUDIT (read-only) ----------
select 'factor_predictions' as tbl, count(*) as n
from public.factor_predictions
where execution_date = '2026-11-13';

select id, data_type, ticker_or_factor, value
from public.factor_predictions
where execution_date = '2026-11-13'
order by id;

select 'paper_lots' as tbl, count(*) as n
from public.paper_lots
where run_date::date = '2026-11-13';

select id, ticker, strategy, status, run_date, shares
from public.paper_lots
where run_date::date = '2026-11-13'
order by ticker, strategy;

select * from public.paper_ledger_state where id = 'default';

select 'paper_portfolio' as tbl, count(*) as n
from public.paper_portfolio
where execution_date = '2026-11-13';

-- Sanity: IV history must still be present (do not delete)
select 'option_iv_history_MUST_STAY' as tbl, count(*) as n
from public.option_iv_history;

-- ---------- PURGE (smoke only) ----------
delete from public.factor_predictions
where execution_date = '2026-11-13'
  and id between 366 and 410;

-- Belt-and-suspenders if ids ever differ but date is still smoke-only:
-- (Uncomment ONLY if audit shows no legitimate non-smoke rows on 2026-11-13)
-- delete from public.factor_predictions where execution_date = '2026-11-13';

delete from public.paper_lots
where id in (
  'bcbedb77-b938-44fa-9b26-70eb9393bbb3',
  'b88af5b8-5736-49ea-b422-e2d5c897f95f',
  '30369403-8778-4003-bb45-4527deb0ec72',
  '63f94bf7-fb36-44a4-8663-8156a993f8e2',
  '98ede371-b5e7-40eb-a353-5ed4959976d8',
  'c19dac6f-1397-42bb-b287-b6c54a4139a6',
  '28c798ae-cd97-4714-b523-aba54b71cbe3',
  'd5fb99fe-e08a-4ce2-8277-62974ed6bc46',
  '95594235-2329-4d8e-a590-2a51f954a559',
  'e4299e3d-acbd-43e8-9720-ab053b11ba60',
  'e35dd2d3-9a2f-4433-8dd9-f57fff0c7bb3',
  'd0bbc10b-222d-4513-a30c-50d2a7c1e76c'
);

-- No paper_portfolio rows were written (export crashed before insert).
delete from public.paper_portfolio
where execution_date = '2026-11-13';

-- Reset ledger continuity to pre-smoke empty state (pre-run: run_count=0, no lots)
update public.paper_ledger_state
set
  cash_factor = 0,
  cash_voo = 0,
  cum_realized_gains = 0,
  cum_realized_losses = 0,
  run_count = 0,
  updated_at = now()
where id = 'default';

-- ---------- POST-PURGE CHECKS ----------
select 'factor_predictions_remaining_on_date' as check, count(*) as n
from public.factor_predictions where execution_date = '2026-11-13';

select 'paper_lots_remaining_smoke' as check, count(*) as n
from public.paper_lots where run_date::date = '2026-11-13';

select 'paper_ledger_state' as check, run_count, cash_factor, cash_voo
from public.paper_ledger_state where id = 'default';

select 'option_iv_history_still_ok' as check, count(*) as n
from public.option_iv_history;
-- Expect n ≈ 3501 (or whatever pre-smoke count was). If this drops, ROLLBACK immediately.

-- commit;   -- uncomment after audits look correct
-- rollback; -- use if anything looks wrong
