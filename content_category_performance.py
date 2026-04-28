import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from seo_utils import get_weekly_date_windows

# GSC Configuration
GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
GSC_KEY_FILE = "gsc-key.json"
GSC_PROPERTY = os.environ.get("GSC_PROPERTY")

# GA4 Configuration
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID")
GA4_KEY_FILE = "ga4-key.json"

CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

def get_gsc_service():
    if not os.path.exists(GSC_KEY_FILE): return None
    creds = service_account.Credentials.from_service_account_file(GSC_KEY_FILE, scopes=GSC_SCOPES)
    return build("searchconsole", "v1", credentials=creds)

def get_ga4_client():
    if not os.path.exists(GA4_KEY_FILE): return None
    creds = service_account.Credentials.from_service_account_file(GA4_KEY_FILE)
    return BetaAnalyticsDataClient(credentials=creds)

def categorize_url(url):
    url = str(url).lower().split('?')[0].rstrip('/')
    
    # Subdomains first
    if "magazine.cim.org" in url: return "Magazine"
    if "convention.cim.org" in url: return "Events"
    if "mrmr.cim.org" in url: return "Technical Standards"
    if "memo.cim.org" in url: return "Regional News"
    if "com.metsoc.org" in url: return "Societies"
    
    # Path patterns
    if "/events" in url or "/calendar" in url: return "Events"
    if "/professional-development" in url or "/short-courses" in url: return "Education"
    if "/library" in url or "/technical-resources" in url or "/cim-journal" in url: return "Technical Library"
    if "/membership" in url: return "Membership"
    if "/scholarships" in url or "/student" in url: return "Student/Scholarships"
    if "/news" in url or "/press-releases" in url: return "News/Press"
    if "/awards" in url: return "Awards"
    if "/about-us" in url: return "Institute Info"
    if url == "https://www.cim.org": return "Homepage"
    
    return "Other"

def fetch_gsc_data(service, start_date, end_date):
    if not service: return pd.DataFrame()
    # Pulling 25k rows to capture almost everything
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["page"],
        "rowLimit": 25000,
    }
    response = service.searchanalytics().query(siteUrl=GSC_PROPERTY, body=request).execute()
    rows = response.get("rows", [])
    data = []
    for row in rows:
        url = row["keys"][0]
        data.append({
            "page": url,
            "category": categorize_url(url),
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "position": row.get("position", 0)
        })
    return pd.DataFrame(data)

def fetch_ga4_data(client, start_date, end_date):
    if not client: return pd.DataFrame()
    # Pulling 25k rows from GA4 too
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration")
        ],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=25000
    )
    response = client.run_report(request)
    data = []
    base_url = "https://www.cim.org"
    for row in response.rows:
        path = row.dimension_values[0].value
        url = base_url + path if path.startswith('/') else path
        data.append({
            "page": url,
            "category": categorize_url(url),
            "sessions": float(row.metric_values[0].value),
            "engagement_rate": float(row.metric_values[1].value),
            "avg_duration": float(row.metric_values[2].value)
        })
    return pd.DataFrame(data)

def generate_visualizations(df):
    if df.empty: return
    
    # Filter out categories with very low traffic for cleaner charts
    plot_df = df[df['sessions'] > 10].copy()
    if plot_df.empty: plot_df = df.copy()

    # 1. Content Ecosystem Map (Bubble Chart)
    # X: Impressions (Reach), Y: Engagement Rate (Quality), Size: Sessions (Impact)
    plt.figure(figsize=(14, 8))
    sns.set_style("whitegrid")
    
    # Log scale for impressions as it can vary wildly
    plot_df['log_impressions'] = np.log10(plot_df['impressions'] + 1)
    
    scatter = sns.scatterplot(
        data=plot_df,
        x='log_impressions',
        y='engagement_rate',
        size='sessions',
        hue='category',
        sizes=(100, 2000),
        alpha=0.6,
        palette='viridis'
    )
    
    plt.title("CIM Content Ecosystem Map: Visibility vs. Quality", fontsize=18, pad=20, fontweight='bold', color='#212878')
    plt.xlabel("Search Visibility (Log10 Impressions)", fontsize=12)
    plt.ylabel("Engagement Rate (%)", fontsize=12)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0.)
    
    # Add quadrants labels
    plt.text(plot_df['log_impressions'].min(), 0.9, 'Hidden Gems', alpha=0.3, fontsize=14)
    plt.text(plot_df['log_impressions'].max()-0.5, 0.9, 'Content Champions', alpha=0.3, fontsize=14)
    plt.text(plot_df['log_impressions'].min(), 0.3, 'Underperformers', alpha=0.3, fontsize=14)
    plt.text(plot_df['log_impressions'].max()-0.5, 0.3, 'Broad Reach', alpha=0.3, fontsize=14)

    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "content_ecosystem_map.png", dpi=200)
    plt.close()

    # 2. Share of Voice (Donut Chart)
    plt.figure(figsize=(10, 8))
    data = plot_df.groupby('category')['sessions'].sum().sort_values(ascending=False)
    colors = sns.color_palette('pastel')[0:len(data)]
    
    plt.pie(data, labels=data.index, autopct='%1.1f%%', startangle=140, 
            colors=colors, pctdistance=0.85, wedgeprops={'width': 0.3})
    
    plt.title("Traffic Share by Content Pillar", fontsize=16, pad=20, fontweight='bold', color='#212878')
    plt.savefig(CHARTS_DIR / "content_share_of_voice.png", dpi=200)
    plt.close()

def main():
    print("🚀 Fetching Deep Content Category Analytics...")
    curr_start, curr_end, prev_start, prev_end = get_weekly_date_windows()
    
    gsc_service = get_gsc_service()
    ga4_client = get_ga4_client()
    
    # All Page Data
    gsc_data = fetch_gsc_data(gsc_service, curr_start, curr_end)
    ga4_data = fetch_ga4_data(ga4_client, curr_start, curr_end)
    
    if gsc_data.empty or ga4_data.empty:
        print("Insufficient data to generate full content report.")
        return

    # Aggregate by Category
    gsc_cat = gsc_data.groupby("category").agg({
        "clicks": "sum", 
        "impressions": "sum",
        "position": "mean"
    }).reset_index()
    
    ga4_cat = ga4_data.groupby("category").agg({
        "sessions": "sum", 
        "engagement_rate": "mean",
        "avg_duration": "mean"
    }).reset_index()
    
    # Merge
    content_perf = pd.merge(gsc_cat, ga4_cat, on="category", how="outer").fillna(0)
    
    # Save CSV
    content_perf.to_csv("content_category_performance.csv", index=False)
    
    # Generate fun visualizations
    generate_visualizations(content_perf)
    print("✅ Content ecosystem map and share of voice generated.")

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
