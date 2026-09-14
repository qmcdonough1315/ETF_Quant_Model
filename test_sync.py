import os
from supabase import create_client

url = "YOUR_SUPABASE_URL"
key = "YOUR_SUPABASE_SERVICE_ROLE_KEY"

supabase = create_client(url, key)

data = [{
    "execution_date": "2026-09-14",
    "data_type": "factor_returns",
    "ticker_or_factor": "Mkt_RF",
    "value": 0.0759
}]

res = supabase.table("factor_predictions").insert(data).execute()
print("Inserted rows:", res.data)
