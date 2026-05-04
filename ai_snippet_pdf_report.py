import os, json, html as _html, requests, pandas as pd, numpy as np
import matplotlib, base64, re
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime, timezone

REPORT_DIR = Path("reports")
CHARTS_DIR = Path("charts")
HTML_PATH  = REPORT_DIR / "ai_snippet_verification_report.html"
FINAL_PATH = REPORT_DIR / "ai_snippet_verification_report_final.html"
CSV_PATH   = REPORT_DIR / "ai_snippet_verification.csv"
MD_PATH    = REPORT_DIR / "ai_snippet_verification.md"

GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID   = os.getenv("MONDAY_ITEM_ID")
MONDAY_API_URL   = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"

C_NAVY="#212878"; C_TEAL="#2A9D8F"; C_CORAL="#E76F51"; C_SLATE="#6C757D"
C_GREEN="#059669"; C_RED="#DC2626"; C_AMBER="#D97706"; C_BORDER="#E2E8F0"


def read_inputs():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Missing {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    md_text = MD_PATH.read_text(encoding="utf-8") if MD_PATH.exists() else ""
    return df, md_text


def risk_label(v):
    v = str(v)
    if v.startswith("High"): return "High"
    if v.startswith("Medium"): return "Medium"
    if v.startswith("Low"): return "Low"
    return "Unknown"


def _style_ax(ax, title="", xlabel="", ylabel=""):
    ax.set_title(title, fontsize=10, fontweight="600", color="#1A1A1A", pad=8, loc="left")
    if xlabel: ax.set_xlabel(xlabel, fontsize=8, color="#64748B", labelpad=4)
    if ylabel: ax.set_ylabel(ylabel, fontsize=8, color="#64748B", labelpad=4)
    ax.tick_params(labelsize=8, colors="#64748B", length=0)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C_BORDER); ax.spines["bottom"].set_color(C_BORDER)
    ax.set_facecolor("#FAFAFA")


def _save(fig, fn):
    CHARTS_DIR.mkdir(exist_ok=True)
    p = CHARTS_DIR / fn
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


def plot_score_overview(df):
    labels = ["Access", "Summary", "CTA"]
    vals   = [df["access_score"].mean(), df["summary_score"].mean(), df["cta_score"].mean()]
    colors = [C_TEAL if v >= 3.5 else C_AMBER if v >= 2.5 else C_CORAL for v in vals]
    fig, ax = plt.subplots(figsize=(13, 4.8)); fig.patch.set_facecolor("white")
    bars = ax.bar(labels, vals, color=colors, width=0.45, zorder=2)
    ax.axhline(3.5, color=C_TEAL, linewidth=1.2, linestyle="--", alpha=0.7, label="Good (3.5)")
    ax.axhline(2.5, color=C_AMBER, linewidth=1.2, linestyle="--", alpha=0.7, label="Acceptable (2.5)")
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()*1.03, f"{v:.2f}/5",
                ha="center", va="bottom", fontsize=10, color="#374151", fontweight="600")
    ax.set_ylim(0, 6); ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Average AI Readiness Scores (out of 5)")
    fig.tight_layout(pad=2.0); return _save(fig, "ai_score_overview.png")


def plot_risk_distribution(df):
    df2 = df.copy(); df2["risk"] = df2["hallucination_flag"].apply(risk_label)
    counts = df2["risk"].value_counts()
    order  = ["High","Medium","Low","Unknown"]
    colors = {"High":C_RED,"Medium":C_AMBER,"Low":C_GREEN,"Unknown":C_SLATE}
    total  = len(df2)
    fig, ax = plt.subplots(figsize=(13, 4.8)); fig.patch.set_facecolor("white")
    left = 0
    for risk in order:
        val = counts.get(risk, 0)
        if val == 0: continue
        pct = val/total*100
        ax.barh(0, pct, left=left, color=colors[risk], height=0.55)
        if pct > 5:
            ax.text(left+pct/2, 0, f"{risk}\n{val} ({pct:.0f}%)",
                    ha="center", va="center", fontsize=9, color="white", fontweight="600")
        left += pct
    ax.set_xlim(0,100); ax.set_yticks([])
    _style_ax(ax, title="Hallucination Risk Distribution")
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    fig.tight_layout(pad=2.0); return _save(fig, "ai_risk_distribution.png")


def plot_page_scores(df):
    if df.empty:
        fig, ax = plt.subplots(figsize=(13,4.8)); fig.patch.set_facecolor("white")
        ax.text(0.5,0.5,"No data.",ha="center",va="center",fontsize=12,color="#94A3B8",transform=ax.transAxes)
        ax.set_axis_off(); return _save(fig, "ai_page_scores.png")
    labels = df["page_name"].tolist()
    x = np.arange(len(labels)); w = 0.25
    fig, ax = plt.subplots(figsize=(13, max(4.8, len(labels)*0.5))); fig.patch.set_facecolor("white")
    ax.barh(x-w, df["access_score"],  w, color=C_NAVY,  label="Access",  zorder=2)
    ax.barh(x,   df["summary_score"], w, color=C_TEAL,  label="Summary", zorder=2)
    ax.barh(x+w, df["cta_score"],     w, color=C_CORAL, label="CTA",     zorder=2)
    ax.set_yticks(x); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0,6); ax.axvline(3.5, color=C_AMBER, linewidth=1, linestyle="--", alpha=0.7, zorder=3)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Per-Page AI Readiness Scores", xlabel="Score (out of 5)")
    fig.tight_layout(pad=2.0); return _save(fig, "ai_page_scores.png")


def build_all_charts(df):
    return {"score_overview":plot_score_overview(df),
            "risk_distribution":plot_risk_distribution(df),
            "page_scores":plot_page_scores(df)}


def build_deterministic_bullets(df):
    bullets = []
    n = len(df)
    avg_a = df["access_score"].mean(); avg_s = df["summary_score"].mean(); avg_c = df["cta_score"].mean()
    bullets.append(f"{n} pages were audited for AI snippet readiness.")
    bullets.append(f"Average scores: Access {avg_a:.2f}/5, Summary Readiness {avg_s:.2f}/5, CTA Visibility {avg_c:.2f}/5.")
    df2 = df.copy(); df2["risk"] = df2["hallucination_flag"].apply(risk_label)
    high = int((df2["risk"]=="High").sum()); med = int((df2["risk"]=="Medium").sum()); low = int((df2["risk"]=="Low").sum())
    if high > 0: bullets.append(f"{high} page{'s' if high!=1 else ''} carry high hallucination risk.")
    if med  > 0: bullets.append(f"{med} page{'s' if med!=1 else ''} carry medium hallucination risk.")
    if low  > 0: bullets.append(f"{low} page{'s' if low!=1 else ''} have low hallucination risk.")
    poor_cta = df[df["cta_score"] <= 2]
    if not poor_cta.empty:
        bullets.append(f"{len(poor_cta)} page{'s' if len(poor_cta)!=1 else ''} scored 2 or below on CTA visibility.")
    return bullets


def build_ai_bullets(df, md_text):
    if not GROQ_API_KEY: return []
    compact = df[["page_name","access_score","summary_score","cta_score","hallucination_flag","recommendation"]].to_csv(index=False)
    prompt = ("You are writing bullet points for a corporate AI snippet readiness report.\n\n"
              "Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.\n"
              "Each bullet is one sentence. Maximum 6 bullets total.\n"
              "Focus on: urgent fixes, CTA gaps, hallucination risk patterns, recommended actions.\n"
              "Professional corporate tone. Do not invent data. Under 150 words total.\n\n"
              f"Page audit data:\n{compact}")
    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"},
            json={"model":"llama-3.3-70b-versatile","messages":[
                {"role":"system","content":"You write polished executive SEO briefs as bullet points only."},
                {"role":"user","content":prompt}],"temperature":0.2},timeout=60)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-*+").replace("**","").replace("__","").replace("*","").strip()
            if clean: bullets.append(clean)
        return bullets
    except Exception as e:
        print(f"  AI bullets failed: {e}", flush=True); return []


def embed_images_as_base64(html_content):
    def replace_src(match):
        src = match.group(1); img_path = Path(src)
        if img_path.exists():
            ext = img_path.suffix.lstrip(".").lower()
            mime = "image/png" if ext=="png" else f"image/{ext}"
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            return f'src="data:{mime};base64,{b64}"'
        return match.group(0)
    return re.sub(r'src="([^"]+\.(png|jpg|jpeg|svg|gif))"', replace_src, html_content)


def _img(path, alt="chart"):
    if not path: return ""
    return f'<img src="{_html.escape(str(path))}" alt="{_html.escape(alt)}" style="width:100%;display:block;border:2px solid #000;">'


def _cw(path, alt="chart"):
    if not path: return ""
    return f'<div style="width:100%;margin-bottom:24px;">{_img(path,alt)}</div>'


def _kpi_card(label, val):
    val_str = f"{val:.2f}" if isinstance(val, float) else str(val)
    return (f'<div style="background:#000;color:#fff;padding:24px 20px;border:2px solid #000;">'
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.15em;color:#999;margin-bottom:12px;">{_html.escape(label)}</div>'
            f'<div style="font-family:Playfair Display,Georgia,serif;font-size:36px;font-weight:700;color:#fff;line-height:1;">{_html.escape(val_str)}</div></div>')


def build_html(df, chart_paths, exec_bullets):
    REPORT_DIR.mkdir(exist_ok=True)
    df2 = df.copy(); df2["risk"] = df2["hallucination_flag"].apply(risk_label)
    avg_a=df["access_score"].mean(); avg_s=df["summary_score"].mean(); avg_c=df["cta_score"].mean()
    high=int((df2["risk"]=="High").sum())
    bullet_items = "".join(f"<li>{_html.escape(b)}</li>" for b in exec_bullets)
    kpi_grid = "".join([_kpi_card("Pages Audited",len(df)),_kpi_card("Avg Access",avg_a),
                         _kpi_card("Avg Summary",avg_s),_kpi_card("Avg CTA",avg_c),_kpi_card("High Risk",high)])
    risk_colors = {"High":C_RED,"Medium":C_AMBER,"Low":C_GREEN,"Unknown":C_SLATE}
    headers = ["Page","Access","Summary","CTA","Risk","Recommendation"]
    th = "".join(f"<th>{h}</th>" for h in headers)
    rows_html = []
    for _, row in df2.iterrows():
        risk = row["risk"]; rc = risk_colors.get(risk, C_SLATE)
        rows_html.append(
            f'<tr style="border-left:3px solid {rc};">'
            f'<td class="url-cell">{_html.escape(str(row.get("page_name",""))[:45])}</td>'
            f'<td style="white-space:nowrap;">{row.get("access_score",0):.1f}/5</td>'
            f'<td style="white-space:nowrap;">{row.get("summary_score",0):.1f}/5</td>'
            f'<td style="white-space:nowrap;">{row.get("cta_score",0):.1f}/5</td>'
            f'<td style="white-space:nowrap;font-weight:700;color:{rc};">{_html.escape(risk)}</td>'
            f'<td style="font-size:9px;">{_html.escape(str(row.get("recommendation",""))[:80])}</td></tr>')
    results_tbl = f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"
    today = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    doc = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        "<title>AI Snippet Verification Report</title>"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">"
        "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
        "<link href=\"https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500;700&display=swap\" rel=\"stylesheet\">"
        "<style>"
        "*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }"
        "html { background: #fff; }"
        "body { font-family: 'Source Serif 4', Georgia, serif; font-size: 14px; color: #000; max-width: 1200px; margin: 0 auto; padding: 0 40px 80px; }"
        ".site-header { background: #000; color: #fff; padding: 40px 48px; margin: 0 -40px 0; }"
        ".site-header__eyebrow { font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.2em; color: #999; margin-bottom: 12px; }"
        ".site-header__title { font-family: 'Playfair Display', Georgia, serif; font-size: clamp(32px,5vw,64px); font-weight: 900; line-height: 1; letter-spacing: -0.02em; color: #fff; margin-bottom: 16px; }"
        ".site-header__meta { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #666; }"
        ".section { padding: 40px 0; }"
        ".section-title { font-family: 'Playfair Display', Georgia, serif; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.15em; color: #000; margin-bottom: 24px; display: flex; align-items: center; gap: 16px; }"
        ".section-title::before { content: ''; display: inline-block; width: 8px; height: 8px; background: #000; flex-shrink: 0; }"
        ".kpi-grid { display: grid; grid-template-columns: repeat(5,1fr); gap: 2px; border: 2px solid #000; }"
        ".kpi-grid > div { border-right: 2px solid #000; } .kpi-grid > div:last-child { border-right: none; }"
        ".report-section { background: #fff; border: 2px solid #000; padding: 28px 32px; }"
        ".rule-thick { border: none; border-top: 4px solid #000; margin: 0; }"
        ".exec-bullets { margin: 0; padding: 0; list-style: none; }"
        ".exec-bullets li { font-family: 'Source Serif 4', Georgia, serif; font-size: 14px; color: #000; line-height: 1.7; padding: 10px 0 10px 20px; border-bottom: 1px solid #E5E5E5; position: relative; }"
        ".exec-bullets li::before { content: '\2014'; position: absolute; left: 0; color: #525252; font-family: 'JetBrains Mono', monospace; }"
        ".exec-bullets li:last-child { border-bottom: none; }"
        "table { font-family: 'JetBrains Mono', monospace; font-size: 10px; width: 100%; border-collapse: collapse; }"
        "th { font-family: 'JetBrains Mono', monospace; font-size: 8px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; padding: 10px 12px; text-align: left; background: #000; color: #fff; border: none; }"
        "td { padding: 9px 12px; border-bottom: 1px solid #E5E5E5; color: #000; }"
        "td.url-cell { max-width: 200px; overflow-wrap: break-word; word-break: break-word; font-family: 'Source Serif 4', Georgia, serif; font-size: 11px; }"
        "tr:hover td { background: #F5F5F5; }"
        "</style></head><body>"
        "<header class=\"site-header\">"
        "<div class=\"site-header__eyebrow\">CIM SEO &mdash; AI Visibility</div>"
        "<h1 class=\"site-header__title\">AI Snippet<br>Verification</h1>"
        f"<div class=\"site-header__meta\">Generated {today}</div></header>"
        "<hr class=\"rule-thick\">"
        "<div class=\"section\"><div class=\"section-title\">Executive Summary</div>"
        f"<ul class=\"exec-bullets\">{bullet_items}</ul></div>"
        "<hr class=\"rule-thick\">"
        "<div class=\"section\" style=\"padding-top:0;\">"
        f"<div class=\"kpi-grid\">{kpi_grid}</div></div>"
        "<hr class=\"rule-thick\">"
        "<div class=\"section\"><div class=\"section-title\">Score Overview</div>"
        f"<div class=\"report-section\">{_cw(chart_paths.get('score_overview'),'Score overview')}{_cw(chart_paths.get('risk_distribution'),'Risk distribution')}</div></div>"
        "<hr class=\"rule-thick\">"
        "<div class=\"section\"><div class=\"section-title\">Per-Page Scores</div>"
        f"<div class=\"report-section\">{_cw(chart_paths.get('page_scores'),'Per-page scores')}</div></div>"
        "<hr class=\"rule-thick\">"
        "<div class=\"section\"><div class=\"section-title\">Page-Level Results</div>"
        f"<div class=\"report-section\">{results_tbl}</div></div>"
        "<hr class=\"rule-thick\">"
        "<footer style=\"padding:32px 0;display:flex;justify-content:space-between;align-items:center;\">"
        "<span style=\"font-family:'Playfair Display',Georgia,serif;font-size:13px;font-weight:700;\">CIM SEO Intelligence</span>"
        f"<span style=\"font-family:'JetBrains Mono',monospace;font-size:9px;color:#525252;\">Generated {today}</span>"
        "</footer></body></html>")
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"  Saved {HTML_PATH}", flush=True)


def generate_self_contained():
    raw = HTML_PATH.read_text(encoding="utf-8")
    final = embed_images_as_base64(raw)
    FINAL_PATH.write_text(final, encoding="utf-8")
    print(f"  Saved {FINAL_PATH} ({len(final.encode())//1024} KB)", flush=True)


def upload_to_monday():
    api_token = MONDAY_API_TOKEN; item_id = MONDAY_ITEM_ID
    if not api_token or not item_id:
        print("  Monday upload skipped.", flush=True); return
    body_text = "AI Snippet Verification Report attached as self-contained HTML."
    update_query = 'mutation ($item_id: ID!, $body: String!) { create_update(item_id: $item_id, body: $body) { id } }'
    resp = requests.post(MONDAY_API_URL,
        headers={"Authorization":api_token,"Content-Type":"application/json"},
        json={"query":update_query,"variables":{"item_id":str(item_id),"body":body_text}},timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data: raise RuntimeError(f"Monday update failed: {data['errors']}")
    update_id = data["data"]["create_update"]["id"]
    file_query = 'mutation ($update_id: ID!, $file: File!) { add_file_to_update(update_id: $update_id, file: $file) { id } }'
    if not FINAL_PATH.exists():
        print("  Monday file attach skipped.", flush=True); return
    with open(FINAL_PATH, "rb") as f:
        file_resp = requests.post(MONDAY_FILE_API_URL,
            headers={"Authorization":api_token},
            data={"query":file_query,"variables":'{"update_id": "'+str(update_id)+'", "file": null}',
                  "map":'{"file": ["variables.file"]}'},
            files={"file":("ai-snippet-verification-report.html",f,"text/html")},timeout=120)
    file_resp.raise_for_status()
    file_data = file_resp.json()
    if "errors" in file_data: raise RuntimeError(f"Monday file attach failed: {file_data['errors']}")
    print("  Uploaded ai-snippet-verification-report.html to Monday.com.", flush=True)


def main():
    df, md_text = read_inputs()
    chart_paths = build_all_charts(df)
    exec_bullets = build_deterministic_bullets(df) + build_ai_bullets(df, md_text)
    build_html(df, chart_paths, exec_bullets)
    generate_self_contained()
    try:
        upload_to_monday()
    except Exception as e:
        print(f"  Monday upload failed: {e}", flush=True)


if __name__ == "__main__":
    main()
