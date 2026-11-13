-- Wave B (#2): multi-week paper ledger continuity.
-- Run once in the Quirk Macro Supabase project (service_role writes; anon read optional).
-- Companion to supabase_paper_portfolio.sql (paper_portfolio + paper_lots).

-- Ensure paper_lots exists (idempotent with the original migration).
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
create index if not exists paper_lots_ticker_idx on public.paper_lots (ticker, status);

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

-- Active wash-sale restrictions (ticker → sale date).
create table if not exists public.paper_wash_sales (
  ticker text primary key,
  sold_on date not null,
  updated_at timestamptz not null default now()
);

alter table public.paper_wash_sales enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'paper_wash_sales' and policyname = 'paper_wash_sales_read'
  ) then
    create policy paper_wash_sales_read on public.paper_wash_sales
      for select using (true);
  end if;
end $$;

-- Singleton cash / realized / run_count state for the paper book.
create table if not exists public.paper_ledger_state (
  id text primary key default 'default',
  cash_factor double precision not null default 0,
  cash_voo double precision not null default 0,
  cum_realized_gains double precision not null default 0,
  cum_realized_losses double precision not null default 0,
  run_count integer not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.paper_ledger_state enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'paper_ledger_state' and policyname = 'paper_ledger_state_read'
  ) then
    create policy paper_ledger_state_read on public.paper_ledger_state
      for select using (true);
  end if;
end $$;

insert into public.paper_ledger_state (id)
values ('default')
on conflict (id) do nothing;
