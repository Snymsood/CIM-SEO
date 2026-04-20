from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import os

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]


def get_service():
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials)


def fetch_query_data(service, start_date, end_date, row_limit=250):
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["query"],
        "rowLimit": row_limit,
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
            "position": row.get("position", 0),
        })

    return pd.DataFrame(data)


def prepare_comparison(current_df, previous_df):
    current_df = current_df.rename(columns={
        "clicks": "clicks_current",
        "impressions": "impressions_current",
        "ctr": "ctr_current",
        "position": "position_current",
    })

    previous_df = previous_df.rename(columns={
        "clicks": "clicks_previous",
        "impressions": "impressions_previous",
        "ctr": "ctr_previous",
        "position": "position_previous",
    })

    merged_df = pd.merge(
        current_df,
        previous_df,
        on="query",
        how="outer"
    ).fillna(0)

    merged_df["clicks_change"] = merged_df["clicks_current"] - merged_df["clicks_previous"]
    merged_df["impressions_change"] = merged_df["impressions_current"] - merged_df["impressions_previous"]
    merged_df["ctr_change"] = merged_df["ctr_current"] - merged_df["ctr_previous"]
    merged_df["position_change"] = merged_df["position_current"] - merged_df["position_previous"]

    return merged_df.sort_values(by="clicks_current", ascending=False)


def write_summary(merged_df, current_start, current_end, previous_start, previous_end):
    total_clicks_current = merged_df["clicks_current"].sum()
    total_clicks_previous = merged_df["clicks_previous"].sum()
    total_impressions_current = merged_df["impressions_current"].sum()
    total_impressions_previous = merged_df["impressions_previous"].sum()

    top_queries = merged_df.sort_values(by="clicks_current", ascending=False).head(10)
    gainers = merged_df.sort_values(by="clicks_change", ascending=False).head(10)
    losers = merged_df.sort_values(by="clicks_change", ascending=True).head(10)

    lines = []
    lines.append(f"# Weekly GSC Summary")
    lines.append("")
    lines.append(f"**Current period:** {current_start} to {current_end}")
    lines.append(f"**Previous period:** {previous_start} to {previous_end}")
    lines.append("")
    lines.append("## Overall performance")
    lines.append(f"- Clicks: {total_clicks_current:.0f} (previous: {total_clicks_previous:.0f}, change: {total_clicks_current - total_clicks_previous:.0f})")
    lines.append(f"- Impressions: {total_impressions_current:.0f} (previous: {total_impressions_previous:.0f}, change: {total_impressions_current - total_impressions_previous:.0f})")
    lines.append("")
    lines.append("## Top 10 queries by current clicks")

    for _, row in top_queries.iterrows():
        lines.append(
            f"- {row['query']}: {row['clicks_current']:.0f} clicks, "
            f"{row['impressions_current']:.0f} impressions, "
            f"CTR {row['ctr_current']:.2%}, position {row['position_current']:.2f}"
        )

    lines.append("")
    lines.append("## Top 10 gainers by clicks")

    for _, row in gainers.iterrows():
        lines.append(
            f"- {row['query']}: change {row['clicks_change']:.0f} "
            f"({row['clicks_previous']:.0f} → {row['clicks_current']:.0f})"
        )

    lines.append("")
    lines.append("## Top 10 losers by clicks")

    for _, row in losers.iterrows():
        lines.append(
            f"- {row['query']}: change {row['clicks_change']:.0f} "
            f"({row['clicks_previous']:.0f} → {row['clicks_current']:.0f})"
        )

    with open("weekly_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    service = get_service()

    current_end = date.today() - timedelta(days=1)
    current_start = current_end - timedelta(days=6)

    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)

    current_df = fetch_query_data(service, current_start, current_end)
    previous_df = fetch_query_data(service, previous_start, previous_end)

    merged_df = prepare_comparison(current_df, previous_df)

    current_df.to_csv("weekly_gsc_report.csv", index=False)
    merged_df.to_csv("weekly_comparison.csv", index=False)

    top_queries = merged_df.sort_values(by="clicks_current", ascending=False).head(25)
    gainers = merged_df.sort_values(by="clicks_change", ascending=False).head(25)
    losers = merged_df.sort_values(by="clicks_change", ascending=True).head(25)

    top_queries.to_csv("top_queries.csv", index=False)
    gainers.to_csv("biggest_gainers.csv", index=False)
    losers.to_csv("biggest_losers.csv", index=False)

    write_summary(
        merged_df,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    print(f"Saved weekly_gsc_report.csv for {current_start} to {current_end}")
    print(f"Saved weekly_comparison.csv for {previous_start} to {previous_end} vs {current_start} to {current_end}")
    print("Saved weekly_summary.md, top_queries.csv, biggest_gainers.csv, biggest_losers.csv")


if __name__ == "__main__":
    main()
