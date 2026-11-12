-- Run once in the Quirk Macro Supabase project.
-- Stores daily ATM implied vol for Phase 1 optionable ETFs (IV Rank inputs).

create table if not exists public.option_iv_history (
  id bigserial primary key,
  as_of_date date not null,
  ticker text not null,
  atm_iv double precision not null,
  dte integer,
  call_iv double precision,
  put_iv double precision,
  spot double precision,
  call_strike double precision,
  put_strike double precision,
  call_mid double precision,
  put_mid double precision,
  source text not null default 'thetadata_eod',
  created_at timestamptz not null default now(),
  unique (as_of_date, ticker, source)
);

create index if not exists option_iv_history_ticker_date_idx
  on public.option_iv_history (ticker, as_of_date desc);

alter table public.option_iv_history enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'option_iv_history' and policyname = 'option_iv_history_read'
  ) then
    create policy option_iv_history_read on public.option_iv_history
      for select using (true);
  end if;
end $$;

-- Optional materialized-friendly view: latest IV Rank per ticker (252-session window).
-- App code can also compute this on read from option_iv_history.
create or replace view public.option_iv_rank_latest as
with ranked as (
  select
    ticker,
    as_of_date,
    atm_iv,
    source,
    row_number() over (partition by ticker, source order by as_of_date desc) as rn
  from public.option_iv_history
),
latest as (
  select * from ranked where rn = 1
),
windowed as (
  select
    h.ticker,
    h.source,
    l.as_of_date,
    l.atm_iv as current_iv,
    min(h.atm_iv) as iv_min,
    max(h.atm_iv) as iv_max,
    count(*) as n_obs
  from latest l
  join public.option_iv_history h
    on h.ticker = l.ticker
   and h.source = l.source
   and h.as_of_date > (l.as_of_date - interval '400 days')
   and h.as_of_date <= l.as_of_date
  group by h.ticker, h.source, l.as_of_date, l.atm_iv
)
select
  ticker,
  source,
  as_of_date,
  current_iv,
  iv_min,
  iv_max,
  n_obs,
  case
    when iv_max > iv_min then 100.0 * (current_iv - iv_min) / (iv_max - iv_min)
    else null
  end as iv_rank
from windowed;
