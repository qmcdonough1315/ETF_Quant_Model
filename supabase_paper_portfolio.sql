-- Run once in the Quirk Macro Supabase project.
-- Grants match the existing factor_predictions publishable-key read pattern.

create table if not exists public.paper_portfolio (
  id bigserial primary key,
  execution_date date not null,
  data_type text not null,
  ticker_or_factor text not null,
  value double precision not null,
  created_at timestamptz not null default now()
);

create index if not exists paper_portfolio_date_idx
  on public.paper_portfolio (execution_date desc);

create index if not exists paper_portfolio_type_idx
  on public.paper_portfolio (data_type, ticker_or_factor);

alter table public.paper_portfolio enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'paper_portfolio' and policyname = 'paper_portfolio_read'
  ) then
    create policy paper_portfolio_read on public.paper_portfolio
      for select using (true);
  end if;
end $$;

-- Optional lot-level detail for future UI drill-down.
create table if not exists public.paper_lots (
  id uuid primary key,
  strategy text not null check (strategy in ('factor', 'voo')),
  ticker text not null,
  shares double precision not null,
  cost_per_share double precision not null,
  cost_basis double precision not null,
  opened_on date not null,
  run_date date not null,
  status text not null check (status in ('open', 'closed')),
  closed_on date,
  close_price double precision,
  realized_pnl double precision,
  close_reason text,
  replacement_for text,
  updated_at timestamptz not null default now()
);

create index if not exists paper_lots_status_idx on public.paper_lots (status, strategy);

alter table public.paper_lots enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'paper_lots' and policyname = 'paper_lots_read'
  ) then
    create policy paper_lots_read on public.paper_lots
      for select using (true);
  end if;
end $$;
