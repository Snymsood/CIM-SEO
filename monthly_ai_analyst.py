#!/usr/bin/env python3
"""
Monthly AI Analyst

Generates executive summary bullets for the monthly dashboard:
- Deterministic bullets: Hard facts computed from data
- AI bullets: Insights and recommendations from Groq API
- Unified output: Combined bullet list for dashboard

Uses Groq API with llama-3.3-70b-versatile for AI analysis.
"""

import os
import pandas as pd
from openai import OpenAI

from pdf_report_formatter import format_pct_change

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ══════════════════════════════════════════════════════════════════════════════
# DETERMINISTIC BULLETS
# ══════════════════════════════════════════════════════════════════════════════

def build_deterministic_bullets(data, kpis, date_range):
    """
    Build deterministic bullets from hard data facts.
    These are always present even if AI fails.
    
    Args:
        data: Dict of DataFrames with all monthly data
        kpis: Dict of KPI values (current, previous)
        date_range: Dict with date information
    
    Returns:
        list: Deterministic bullet points
    """
    bullets = []
    
    current_month = date_range["current_start"].strftime("%B %Y")
    previous_month = date_range["previous_start"].strftime("%B %Y")
    
    # Sessions
    s_curr = kpis["sessions"]["curr"]
    s_prev = kpis["sessions"]["prev"]
    if s_curr > 0:
        chg = s_curr - s_prev
        pct = format_pct_change(s_curr, s_prev)
        direction = "increased" if chg > 0 else "decreased" if chg < 0 else "remained flat"
        bullets.append(
            f"Sessions {direction} to {s_curr:,.0f} in {current_month} "
            f"({pct} vs {previous_month})."
        )
    
    # Clicks
    c_curr = kpis["clicks"]["curr"]
    c_prev = kpis["clicks"]["prev"]
    if c_curr > 0:
        chg = c_curr - c_prev
        pct = format_pct_change(c_curr, c_prev)
        direction = "increased" if chg > 0 else "decreased" if chg < 0 else "remained flat"
        bullets.append(
            f"GSC clicks {direction} to {c_curr:,.0f} "
            f"({pct} month-over-month)."
        )
    
    # Impressions
    i_curr = kpis["impressions"]["curr"]
    i_prev = kpis["impressions"]["prev"]
    if i_curr > 0:
        chg = i_curr - i_prev
        pct = format_pct_change(i_curr, i_prev)
        bullets.append(
            f"Search impressions reached {i_curr:,.0f} ({pct} MoM)."
        )
    
    # Average position
    p_curr = kpis["avg_position"]["curr"]
    p_prev = kpis["avg_position"]["prev"]
    if p_curr > 0 and p_prev > 0:
        chg = p_curr - p_prev
        if abs(chg) >= 0.5:
            direction = "improved" if chg < 0 else "declined"
            bullets.append(
                f"Average search position {direction} to {p_curr:.1f} "
                f"(from {p_prev:.1f} previous month)."
            )
    
    # Engagement rate
    e_curr = kpis.get("engagement_rate", {}).get("curr", 0)
    e_prev = kpis.get("engagement_rate", {}).get("prev", 0)
    if e_curr > 0:
        pct = format_pct_change(e_curr, e_prev)
        bullets.append(
            f"Engagement rate: {e_curr:.1%} ({pct} MoM)."
        )
    
    # Top query movers
    gsc_queries = data.get("gsc_queries", pd.DataFrame())
    if not gsc_queries.empty and "position_change" in gsc_queries.columns:
        gsc_queries["position_change"] = pd.to_numeric(
            gsc_queries["position_change"], errors="coerce"
        ).fillna(0)
        
        improved = len(gsc_queries[gsc_queries["position_change"] < -1])
        declined = len(gsc_queries[gsc_queries["position_change"] > 1])
        
        if improved > 0 or declined > 0:
            bullets.append(
                f"Query rankings: {improved} queries improved position, "
                f"{declined} declined."
            )
    
    # Top channel
    ga4_channels = data.get("ga4_channels_current", pd.DataFrame())
    if not ga4_channels.empty and "sessions" in ga4_channels.columns:
        ga4_channels["sessions"] = pd.to_numeric(
            ga4_channels["sessions"], errors="coerce"
        ).fillna(0)
        top_channel = ga4_channels.nlargest(1, "sessions")
        if not top_channel.empty:
            channel_name = top_channel.iloc[0]["channel"]
            channel_sessions = top_channel.iloc[0]["sessions"]
            total_sessions = ga4_channels["sessions"].sum()
            pct = (channel_sessions / total_sessions * 100) if total_sessions > 0 else 0
            bullets.append(
                f"Top traffic source: {channel_name} "
                f"({channel_sessions:,.0f} sessions, {pct:.1f}% of total)."
            )
    
    # Device split
    ga4_devices = data.get("ga4_devices", pd.DataFrame())
    if not ga4_devices.empty and "sessions" in ga4_devices.columns:
        ga4_devices["sessions"] = pd.to_numeric(
            ga4_devices["sessions"], errors="coerce"
        ).fillna(0)
        total = ga4_devices["sessions"].sum()
        if total > 0:
            mobile_row = ga4_devices[ga4_devices["device"] == "mobile"]
            if not mobile_row.empty:
                mobile_sessions = mobile_row.iloc[0]["sessions"]
                mobile_pct = (mobile_sessions / total * 100)
                bullets.append(
                    f"Mobile traffic: {mobile_pct:.1f}% of total sessions "
                    f"({mobile_sessions:,.0f} sessions)."
                )
    
    return bullets


# ══════════════════════════════════════════════════════════════════════════════
# AI BULLETS
# ══════════════════════════════════════════════════════════════════════════════

def build_ai_bullets(data, kpis, date_range):
    """
    Build AI-generated insights using Groq API.
    Returns empty list on failure (graceful degradation).
    
    Args:
        data: Dict of DataFrames with all monthly data
        kpis: Dict of KPI values (current, previous)
        date_range: Dict with date information
    
    Returns:
        list: AI-generated bullet points
    """
    if not GROQ_API_KEY:
        print("⚠ GROQ_API_KEY not set - skipping AI analysis")
        return []
    
    current_month = date_range["current_start"].strftime("%B %Y")
    previous_month = date_range["previous_start"].strftime("%B %Y")
    
    # Build context from data
    def _csv_snippet(df, max_rows=10):
        """Convert DataFrame to CSV snippet for AI context."""
        if df.empty:
            return "No data available"
        return df.head(max_rows).to_csv(index=False)
    
    # KPI summary
    kpi_summary = f"""
Sessions: {kpis['sessions']['curr']:,.0f} ({format_pct_change(kpis['sessions']['curr'], kpis['sessions']['prev'])})
Active Users: {kpis['users']['curr']:,.0f} ({format_pct_change(kpis['users']['curr'], kpis['users']['prev'])})
Engagement Rate: {kpis.get('engagement_rate', {}).get('curr', 0):.1%} ({format_pct_change(kpis.get('engagement_rate', {}).get('curr', 0), kpis.get('engagement_rate', {}).get('prev', 0))})
GSC Clicks: {kpis['clicks']['curr']:,.0f} ({format_pct_change(kpis['clicks']['curr'], kpis['clicks']['prev'])})
GSC Impressions: {kpis['impressions']['curr']:,.0f} ({format_pct_change(kpis['impressions']['curr'], kpis['impressions']['prev'])})
Average Position: {kpis['avg_position']['curr']:.1f} (prev: {kpis['avg_position']['prev']:.1f})
CTR: {kpis.get('ctr', {}).get('curr', 0):.2%} ({format_pct_change(kpis.get('ctr', {}).get('curr', 0), kpis.get('ctr', {}).get('prev', 0))})
"""
    
    # Top queries
    gsc_queries = data.get("gsc_queries", pd.DataFrame())
    queries_context = _csv_snippet(gsc_queries)
    
    # Top pages
    gsc_pages = data.get("gsc_pages", pd.DataFrame())
    pages_context = _csv_snippet(gsc_pages)
    
    # Channels
    ga4_channels = data.get("ga4_channels_current", pd.DataFrame())
    channels_context = _csv_snippet(ga4_channels)
    
    # Build prompt
    prompt = f"""
You are writing a concise executive summary for a monthly SEO report comparing {current_month} to {previous_month}.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 8 bullets total.
Do not invent data. Do not mention AI, models, or automation.
Focus on cross-channel insights, strategic opportunities, and actionable recommendations.
Write as if this is part of a manually produced executive report.

KPI Summary:
{kpi_summary}

Top Search Queries (GSC):
{queries_context}

Top Landing Pages (GSC):
{pages_context}

Traffic Channels (GA4):
{channels_context}

Provide insights on:
1. Cross-channel correlations (e.g., high impressions but low sessions)
2. Strategic opportunities (e.g., queries with high impressions but low CTR)
3. Performance trends (e.g., which channels are growing/declining)
4. Risks or concerns (e.g., declining engagement, position drops)
5. Actionable recommendations (e.g., optimize for specific queries, improve CTR)
"""
    
    try:
        print("🤖 Generating AI insights...")
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You write polished monthly executive SEO briefs as bullet points only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        
        raw = response.choices[0].message.content.strip()
        
        # Clean up markdown and formatting
        bullets = []
        for line in raw.splitlines():
            # Remove leading markers
            clean = line.strip().lstrip("-*+•·▪▸0123456789.")
            # Remove markdown formatting
            clean = clean.replace("**", "").replace("__", "").replace("*", "")
            clean = clean.strip()
            
            if clean and len(clean) > 10:  # Ignore very short lines
                bullets.append(clean)
        
        print(f"✓ Generated {len(bullets)} AI insights")
        return bullets[:8]  # Max 8 bullets
        
    except Exception as e:
        print(f"⚠ AI analysis failed: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED BULLETS
# ══════════════════════════════════════════════════════════════════════════════

def build_unified_bullets(data, kpis, date_range):
    """
    Build unified executive summary combining deterministic and AI bullets.
    
    Args:
        data: Dict of DataFrames with all monthly data
        kpis: Dict of KPI values (current, previous)
        date_range: Dict with date information
    
    Returns:
        list: Combined bullet points (deterministic first, then AI)
    """
    print("=" * 80)
    print("MONTHLY AI ANALYSIS - STARTING")
    print("=" * 80)
    
    print("\n[1/3] Building deterministic bullets...")
    deterministic = build_deterministic_bullets(data, kpis, date_range)
    print(f"✓ Generated {len(deterministic)} deterministic bullets")
    
    print("\n[2/3] Building AI bullets...")
    ai = build_ai_bullets(data, kpis, date_range)
    if ai:
        print(f"✓ Generated {len(ai)} AI bullets")
    else:
        print("⚠ No AI bullets generated (API unavailable or failed)")
    
    print("\n[3/3] Combining bullets...")
    unified = deterministic + ai
    print(f"✓ Total: {len(unified)} bullets")
    
    print("\n" + "=" * 80)
    print("MONTHLY AI ANALYSIS - COMPLETE")
    print("=" * 80)
    
    return unified


if __name__ == "__main__":
    # Test with sample data
    print("This script should be called from monthly_master_report.py")
    print("For testing, run: python monthly_master_report.py")
