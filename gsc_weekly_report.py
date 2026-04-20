from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import os

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]

end_date = date.today() - timedelta(days=1)
start_date = end_date - timedelta(days=6)

credentials = service_account.Credentials.from_service_account_file(
    KEY_FILE, scopes=SCOPES
)

service = build("searchconsole", "v1", credentials=credentials)

request = {
    "startDate": start_date.isoformat(),
    "endDate": end_date.isoformat(),
    "dimensions": ["query"],
    "rowLimit": 100
}

response = service.searchanalytics().query(
    siteUrl=SITE_URL,
    body=request
).execute()

rows = response.get("rows", [])
data = []

for row in rows:
    data.append({
        "query": row["keys"][0],
        "clicks": row.get("clicks", 0),
        "impressions": row.get("impressions", 0),
        "ctr": row.get("ctr", 0),
        "position": row.get("position", 0)
    })

df = pd.DataFrame(data)
df.to_csv("weekly_gsc_report.csv", index=False)

print(f"Saved weekly_gsc_report.csv for {start_date} to {end_date}")
