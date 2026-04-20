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


def empty_dimension_df(dimension_name):
    return pd.DataFrame(columns=[dimension_name, "clicks", "impressions", "ctr", "position"])


def fetch_dimension_data(service, start_date, end_date, dimension, row_limit=250):
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": [dimension],
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
            dimension: row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0),
            "position": row.get("position", 0),
        })

    df = pd.DataFrame(data)

    if df.empty:
        return empty_dimension_df(dimension)

    return df


def prepare_comparison(current_df, previous_df, key_column):
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

    merged_df = pd.merge(current_df, previous_df, on=key_column, how="outer").fillna(0)

    merged_df["clicks_change"] = merged_df["clicks_current"] - merged_df["clicks_previous"]
    merged_df["impressions_change"] = merged_df["impressions_current"] - merged_df["impressions_previous"]
    merged_df["ctr_change"] = merged_df["ctr_current"] - merged_df["ctr_previous"]
    merged_df["position_change"] = merged_df["position_current"] - merged_df["position_previous"]

    merged_df["is_new"] = (merged_df["clicks_previous"] == 0) & (merged_df["clicks_current"] > 0)
    merged_df["is_lost"] = (merged_df["clicks_previous"] > 0) & (merged_df["clicks_current"] == 0)

    return merged_df.sort_values(by="clicks_current", ascending=False)


def safe_pct_change(current, previous):
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def format_pct_change(current, previous):
    pct = safe_pct_change(current, previous)
    if pct is None:
        return "n/a"
    return f"{pct:+.1f}%"


def build_executive_read(total_clicks_current, total_clicks_previous,
                         total_impressions_current, total_impressions_previous,
                         weighted_ctr_current, weighted_ctr_previous,
                         avg_position_current, avg_position_previous,
                         top_queries_df):
    lines = []

    if total_clicks_current > total_clicks_previous:
        lines.append("* overall clicks are up")
    elif total_clicks_current < total_clicks_previous:
        lines.append("* overall clicks are down")
    else:
        lines.append("* overall clicks are flat")

    impressions_pct = safe_pct_change(total_impressions_current, total_impressions_previous)
    if impressions_pct is None:
        lines.append("* impressions have no prior baseline")
    elif abs(impressions_pct) < 3:
        lines.append("* impressions are basically flat")
    elif total_impressions_current > total_impressions_previous:
        lines.append("* impressions are up")
    else:
        lines.append("* impressions are down")

    if weighted_ctr_current > weighted_ctr_previous:
        lines.append("* CTR improved")
    elif weighted_ctr_current < weighted_ctr_previous:
        lines.append("* CTR declined")
    else:
        lines.append("* CTR was flat")

    # lower position is better
    if avg_position_current < avg_position_previous:
        lines.append("* average position improved")
    elif avg_position_current > avg_position_previous:
        lines.append("* average position declined")
    else:
        lines.append("* average position was flat")

    branded_mask = top_queries_df["query"].str.contains(
        r"cim connect|vancouver 2026|cim 2026|cim vancouver",
        case=False,
        na=False
    )
    branded_clicks = top_queries_df.loc[branded_mask, "clicks_current"].sum()
    total_top_clicks = top_queries_df["clicks_current"].sum()

    if total_top_clicks > 0 and (branded_clicks / total_top_clicks) >= 0.4:
        lines.append("* most growth is concentrated around CIM Connect / Vancouver 2026 branded demand")

    return lines


def write_summary(query_df, page_df, current_start, current_end, previous_start, previous_end):
    total_clicks_current = query_df["clicks_current"].sum()
    total_clicks_previous = query_df["clicks_previous"].sum()
    total_impressions_current = query_df["impressions_current"].sum()
    total_impressions_previous = query_df["impressions_previous"].sum()

    weighted_ctr_current = (
        total_clicks_current / total_impressions_current
        if total_impressions_current > 0 else 0
    )
    weighted_ctr_previous = (
        total_clicks_previous / total_impressions_previous
        if total_impressions_previous > 0 else 0
    )

    avg_position_current = (
        query_df.loc[query_df["impressions_current"] > 0, "position_current"].mean()
        if not query_df.loc[query_df["impressions_current"] > 0].empty else 0
    )
    avg_position_previous = (
        query_df.loc[query_df["impressions_previous"] > 0, "position_previous"].mean()
        if not query_df.loc[query_df["impressions_previous"] > 0].empty else 0
    )

    top_queries = query_df.sort_values(by="clicks_current", ascending=False).head(10)
    gainers = query_df.sort_values(by="clicks_change", ascending=False).head(10)
    losers = query_df.sort_values(by="clicks_change", ascending=True).head(10)
    new_queries = query_df[query_df["is_new"]].sort_values(by="clicks_current", ascending=False).head(10)
    lost_queries = query_df[query_df["is_lost"]].sort_values(by="clicks_previous", ascending=False).head(10)

    top_pages = page_df.sort_values(by="clicks_current", ascending=False).head(10)
    page_gainers = page_df.sort_values(by="clicks_change", ascending=False).head(10)
    page_losers = page_df.sort_values(by="clicks_change", ascending=True).head(10)

    executive_read = build_executive_read(
        total_clicks_current,
        total_clicks_previous,
        total_impressions_current,
        total_impressions_previous,
        weighted_ctr_current,
        weighted_ctr_previous,
        avg_position_current,
        avg_position_previous,
        top_queries,
    )

    lines = []
    lines.append("# Weekly GSC Summary")
    lines.append("")
    lines.append("## Executive read")
    lines.append("")
    for line in executive_read:
        lines.append(line)

    lines.append("")
    lines.append(f"**Current period:** {current_start} to {current_end}")
    lines.append(f"**Previous period:** {previous_start} to {previous_end}")
    lines.append("")
    lines.append("## Overall performance")
    lines.append(
        f"- Clicks: {total_clicks_current:.0f} vs {total_clicks_previous:.0f} "
        f"({format_pct_change(total_clicks_current, total_clicks_previous)})"
    )
    lines.append(
        f"- Impressions: {total_impressions_current:.0f} vs {total_impressions_previous:.0f} "
        f"({format_pct_change(total_impressions_current, total_impressions_previous)})"
    )
    lines.append(f"- CTR: {weighted_ctr_current:.2%} vs {weighted_ctr_previous:.2%}")
    lines.append(f"- Avg position: {avg_position_current:.2f} vs {avg_position_previous:.2f}")

    lines.append("")
    lines.append("## Top queries")
    for _, row in top_queries.iterrows():
        lines.append(
            f"- {row['query']}: {row['clicks_current']:.0f} clicks, "
            f"{row['impressions_current']:.0f} impressions, "
            f"CTR {row['ctr_current']:.2%}, position {row['position_current']:.2f}"
        )

    lines.append("")
    lines.append("## Biggest gainers")
    for _, row in gainers.iterrows():
        lines.append(
            f"- {row['query']}: {row['clicks_previous']:.0f} → {row['clicks_current']:.0f} "
            f"({row['clicks_change']:+.0f})"
        )

    lines.append("")
    lines.append("## Biggest losers")
    for _, row in losers.iterrows():
        lines.append(
            f"- {row['query']}: {row['clicks_previous']:.0f} → {row['clicks_current']:.0f} "
            f"({row['clicks_change']:+.0f})"
        )

    lines.append("")
    lines.append("## New queries")
    if new_queries.empty:
        lines.append("- None")
    else:
        for _, row in new_queries.iterrows():
            lines.append(
                f"- {row['query']}: {row['clicks_current']:.0f} clicks, "
                f"{row['impressions_current']:.0f} impressions"
            )

    lines.append("")
    lines.append("## Lost queries")
    if lost_queries.empty:
        lines.append("- None")
    else:
        for _, row in lost_queries.iterrows():
            lines.append(
                f"- {row['query']}: dropped from {row['clicks_previous']:.0f} clicks to 0"
            )

    lines.append("")
    lines.append("## Top pages")
    for _, row in top_pages.iterrows():
        lines.append(
            f"- {row['page']}: {row['clicks_current']:.0f} clicks, "
            f"{row['impressions_current']:.0f} impressions, "
            f"CTR {row['ctr_current']:.2%}, position {row['position_current']:.2f}"
        )

    lines.append("")
    lines.append("## Page gainers")
    for _, row in page_gainers.iterrows():
        lines.append(
            f"- {row['page']}: {row['clicks_previous']:.0f} → {row['clicks_current']:.0f} "
            f"({row['clicks_change']:+.0f})"
        )

    lines.append("")
    lines.append("## Page losers")
    for _, row in page_losers.iterrows():
        lines.append(
            f"- {row['page']}: {row['clicks_previous']:.0f} → {row['clicks_current']:.0f} "
            f"({row['clicks_change']:+.0f})"
        )

    with open("weekly_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    service = get_service()

    current_end = date.today() - timedelta(days=1)
    current_start = current_end - timedelta(days=6)

    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)

    current_query_df = fetch_dimension_data(service, current_start, current_end, "query", row_limit=250)
    previous_query_df = fetch_dimension_data(service, previous_start, previous_end, "query", row_limit=250)

    current_page_df = fetch_dimension_data(service, current_start, current_end, "page", row_limit=250)
    previous_page_df = fetch_dimension_data(service, previous_start, previous_end, "page", row_limit=250)

    query_comparison_df = prepare_comparison(current_query_df, previous_query_df, "query")
    page_comparison_df = prepare_comparison(current_page_df, previous_page_df, "page")

    current_query_df.to_csv("weekly_gsc_report.csv", index=False)
    query_comparison_df.to_csv("weekly_comparison.csv", index=False)

    top_queries = query_comparison_df.sort_values(by="clicks_current", ascending=False).head(25)
    gainers = query_comparison_df.sort_values(by="clicks_change", ascending=False).head(25)
    losers = query_comparison_df.sort_values(by="clicks_change", ascending=True).head(25)

    top_queries.to_csv("top_queries.csv", index=False)
    gainers.to_csv("biggest_gainers.csv", index=False)
    losers.to_csv("biggest_losers.csv", index=False)

    current_page_df.to_csv("weekly_pages_report.csv", index=False)
    page_comparison_df.to_csv("weekly_pages_comparison.csv", index=False)

    top_pages = page_comparison_df.sort_values(by="clicks_current", ascending=False).head(25)
    page_gainers = page_comparison_df.sort_values(by="clicks_change", ascending=False).head(25)
    page_losers = page_comparison_df.sort_values(by="clicks_change", ascending=True).head(25)

    top_pages.to_csv("top_pages.csv", index=False)
    page_gainers.to_csv("page_gainers.csv", index=False)
    page_losers.to_csv("page_losers.csv", index=False)

    write_summary(
        query_comparison_df,
        page_comparison_df,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    print(f"Saved weekly_gsc_report.csv for {current_start} to {current_end}")
    print(f"Saved weekly_comparison.csv for {previous_start} to {previous_end} vs {current_start} to {current_end}")
    print("Saved query and page reports, plus weekly_summary.md")


if __name__ == "__main__":
    main()
