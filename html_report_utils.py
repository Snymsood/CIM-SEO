"""html_report_utils.py
Shared Minimalist Monochrome HTML utilities for all CIM SEO report scripts.
"""
import base64, re, os, requests
from pathlib import Path
from datetime import date

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"


def mm_page_css():
    """Full Minimalist Monochrome CSS for browser-rendered HTML reports."""
    return """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html {
    background: #fff;
    background-image: repeating-linear-gradient(0deg,transparent,transparent 1px,#000 1px,#000 2px);
    background-size: 100% 4px;
    background-attachment: fixed;
}
html::before {
    content: '';
    position: fixed;
    inset: 0;
    background: rgba(255,255,255,0.97);
    pointer-events: none;
    z-index: 0;
}
body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
    opacity: 0.018;
    pointer-events: none;
    z-index: 9999;
}
body {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 14px;
    color: #000;
    background: transparent;
    line-height: 1.625;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 40px 80px;
    position: relative;
    z-index: 1;
}
.site-header {
    background: #000;
    color: #fff;
    padding: 40px 48px;
    margin: 0 -40px 0;
    position: relative;
    overflow: hidden;
}
.site-header::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image: repeating-linear-gradient(90deg,transparent,transparent 1px,#fff 1px,#fff 2px);
    background-size: 4px 100%;
    opacity: 0.03;
    pointer-events: none;
}
.site-header__eyebrow {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: #999;
    margin-bottom: 12px;
}
.site-header__title {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: clamp(28px, 4vw, 56px);
    font-weight: 900;
    line-height: 1;
    letter-spacing: -0.02em;
    color: #fff;
    margin-bottom: 16px;
}
.site-header__meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #666;
    letter-spacing: 0.05em;
    display: flex;
    align-items: center;
    gap: 16px;
}
.site-header__meta::before {
    content: '';
    display: inline-block;
    width: 24px;
    height: 2px;
    background: #fff;
    flex-shrink: 0;
}
.section { padding: 40px 0; }
.section-title {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #000;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}
.section-title::before {
    content: '';
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #000;
    flex-shrink: 0;
}
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2px;
    border: 2px solid #000;
}
.kpi-grid > div { border-right: 2px solid #000; }
.kpi-grid > div:last-child { border-right: none; }
.kpi-card {
    background: #000;
    color: #fff;
    padding: 24px 20px;
    position: relative;
    overflow: hidden;
}
.kpi-card::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image: repeating-linear-gradient(90deg,transparent,transparent 1px,#fff 1px,#fff 2px);
    background-size: 4px 100%;
    opacity: 0.03;
    pointer-events: none;
}
.kpi-card__label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #999;
    margin-bottom: 12px;
}
.kpi-card__value {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 36px;
    font-weight: 700;
    color: #fff;
    line-height: 1;
    margin-bottom: 10px;
}
.kpi-card__prev {
    font-family: 'JetBrains Mono', monospace;
    font-size: 9px;
    color: #999;
    margin-bottom: 8px;
}
.report-section {
    background: #fff;
    border: 2px solid #000;
    padding: 28px 32px;
}
.col-header {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 13px;
    font-weight: 700;
    color: #000;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 28px;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid #000;
}
.col-header:first-child { margin-top: 0; }
.rule-thick { border: none; border-top: 4px solid #000; margin: 0; }
.exec-bullets { margin: 0; padding: 0; list-style: none; }
.exec-bullets li {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 14px;
    color: #000;
    line-height: 1.7;
    padding: 10px 0 10px 20px;
    border-bottom: 1px solid #E5E5E5;
    position: relative;
}
.exec-bullets li::before { content: '—'; position: absolute; left: 0; color: #525252; font-family: 'JetBrains Mono', monospace; }
.exec-bullets li:last-child { border-bottom: none; }
.panel-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #525252;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.panel-label::after { content: ''; flex: 1; height: 1px; background: #E5E5E5; }
.chg { font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 0; display: inline-block; border: 1px solid #000; }
.chg.pos { background: #000; color: #fff; }
.chg.neg { background: #fff; color: #000; }
.chg.neu { background: #fff; color: #525252; border-color: #E5E5E5; }
.badge { font-family: 'JetBrains Mono', monospace; font-size: 8px; font-weight: 700; padding: 2px 6px; border-radius: 0; display: inline-block; white-space: nowrap; border: 1px solid #000; text-transform: uppercase; letter-spacing: 0.05em; }
.badge-top3 { background: #000; color: #fff; }
.badge-p1   { background: #fff; color: #000; }
.badge-p2   { background: #fff; color: #525252; border-color: #525252; }
.badge-p3   { background: #fff; color: #E5E5E5; border-color: #E5E5E5; }
.chart-wrap { width: 100%; margin-bottom: 24px; }
.chart-wrap img { width: 100%; display: block; border: 2px solid #000; border-radius: 0; }
.chart-row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
.chart-row-2 img { width: 100%; display: block; border: 2px solid #000; border-radius: 0; }
.nl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 0; }
.section-label { font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: #525252; margin-bottom: 8px; }
table { font-family: 'JetBrains Mono', monospace; font-size: 10px; width: 100%; border-collapse: collapse; }
th { font-family: 'JetBrains Mono', monospace; font-size: 8px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; padding: 10px 12px; text-align: left; background: #000; color: #fff; border: none; }
td { padding: 9px 12px; border-bottom: 1px solid #E5E5E5; color: #000; }
td.url-cell { font-family: 'Source Serif 4', Georgia, serif; font-size: 11px; color: #000; max-width: 220px; overflow-wrap: break-word; word-break: break-word; }
tr:hover td { background: #F5F5F5; }
footer { padding: 32px 0; display: flex; justify-content: space-between; align-items: center; }
footer .brand { font-family: 'Playfair Display', Georgia, serif; font-size: 13px; font-weight: 700; letter-spacing: 0.05em; }
footer .datestamp { font-family: 'JetBrains Mono', monospace; font-size: 9px; color: #525252; text-transform: uppercase; letter-spacing: 0.12em; }
@media (max-width: 768px) {
    body { padding: 0 20px 60px; }
    .site-header { padding: 28px 24px; margin: 0 -20px 0; }
    .kpi-grid { grid-template-columns: 1fr 1fr; }
    .chart-row-2 { grid-template-columns: 1fr; }
    .nl-grid { grid-template-columns: 1fr; }
}
"""


FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700'
    '&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,400'
    '&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
)


def mm_html_shell(title, eyebrow, headline, meta_line, body_content):
    """Return a complete Minimalist Monochrome HTML document."""
    today = date.today().strftime("%B %d, %Y")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{FONT_LINK}
<style>{mm_page_css()}</style>
</head>
<body>
<header class="site-header">
  <div class="site-header__eyebrow">{eyebrow}</div>
  <h1 class="site-header__title">{headline}</h1>
  <div class="site-header__meta">{meta_line}</div>
</header>
<hr class="rule-thick">
{body_content}
<hr class="rule-thick">
<footer>
  <span class="brand">CIM SEO Intelligence</span>
  <span class="datestamp">Generated {today}</span>
</footer>
</body>
</html>"""


def mm_kpi_card(label, curr_val, prev_val, is_pct=False, decimals=0, lower_better=False):
    """Return an inverted KPI card div."""
    from pdf_report_formatter import format_num, format_pct_change
    curr_str  = format_num(curr_val, decimals, as_percent=is_pct)
    prev_str  = format_num(prev_val, decimals, as_percent=is_pct)
    delta_str = format_pct_change(curr_val, prev_val)
    if delta_str == "-":
        delta_html = '<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">—</span>'
    else:
        is_pos = delta_str.startswith("+")
        good   = (is_pos and not lower_better) or (not is_pos and lower_better)
        d_bg, d_color, d_border = ("#000","#fff","1px solid #000") if good else ("#fff","#000","1px solid #000")
        delta_html = (
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;'
            f'padding:2px 8px;background:{d_bg};color:{d_color};border:{d_border};">{delta_str}</span>'
        )
    import html as _html
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-card__label">{_html.escape(label)}</div>'
        f'<div class="kpi-card__value">{_html.escape(curr_str)}</div>'
        f'<div class="kpi-card__prev">prev {_html.escape(prev_str)}</div>'
        f'{delta_html}'
        f'</div>'
    )


def mm_kpi_grid(*cards):
    """Wrap KPI cards in the inverted grid."""
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def mm_section(title, content):
    """Wrap content in a section with title and thick rule."""
    return (
        f'<div class="section">'
        f'<div class="section-title">{title}</div>'
        f'{content}'
        f'</div>'
        f'<hr class="rule-thick">'
    )


def mm_report_section(content):
    return f'<div class="report-section">{content}</div>'


def mm_col_header(text):
    return f'<div class="col-header">{text}</div>'


def mm_chart_wrap(path, alt="chart"):
    if not path:
        return ""
    import html as _html
    return f'<div class="chart-wrap"><img src="{_html.escape(str(path))}" alt="{_html.escape(alt)}"></div>'


def mm_chart_row_2(path_a, alt_a, path_b, alt_b):
    import html as _html
    a = f'<div><img src="{_html.escape(str(path_a))}" alt="{_html.escape(alt_a)}" style="width:100%;display:block;border:2px solid #000;"></div>' if path_a else "<div></div>"
    b = f'<div><img src="{_html.escape(str(path_b))}" alt="{_html.escape(alt_b)}" style="width:100%;display:block;border:2px solid #000;"></div>' if path_b else "<div></div>"
    if not path_a and not path_b:
        return ""
    return f'<div class="chart-row-2">{a}{b}</div>'


def mm_exec_bullets(bullets):
    """Render a list of bullet strings as the exec summary panel."""
    import html as _html
    items = "".join(f"<li>{_html.escape(b)}</li>" for b in bullets)
    return f'<ul class="exec-bullets">{items}</ul>'


def mm_ai_block(text):
    """Render AI/commentary text as styled paragraphs."""
    import html as _html
    paras = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*+•·▪▸").replace("**","").replace("__","").replace("*","").strip()
        if line:
            paras.append(f'<p style="font-family:\'Source Serif 4\',Georgia,serif;font-size:13px;color:#000;line-height:1.7;margin-bottom:10px;">{_html.escape(line)}</p>')
    return "".join(paras) if paras else ""


def embed_images_as_base64(html_content):
    """Replace all local img src= paths with inline base64 data URIs."""
    def replace_src(match):
        src = match.group(1)
        img_path = Path(src)
        if img_path.exists():
            ext  = img_path.suffix.lstrip(".").lower()
            mime = "image/png" if ext == "png" else f"image/{ext}"
            b64  = base64.b64encode(img_path.read_bytes()).decode()
            return f'src="data:{mime};base64,{b64}"'
        return match.group(0)
    return re.sub(r'src="([^"]+\.(png|jpg|jpeg|svg|gif))"', replace_src, html_content)


def generate_self_contained_html(html_path, output_path):
    """Read html_path, embed all chart images as base64, write output_path."""
    raw   = Path(html_path).read_text(encoding="utf-8")
    final = embed_images_as_base64(raw)
    Path(output_path).write_text(final, encoding="utf-8")
    size_kb = len(final.encode()) // 1024
    print(f"Saved {output_path} ({size_kb} KB, self-contained)")


def upload_html_to_monday(html_path, html_filename, body_text=None, api_token=None, item_id=None):
    """Post a text update to Monday.com and attach the self-contained HTML file."""
    if api_token is None:
        api_token = os.getenv("MONDAY_API_TOKEN")
    if item_id is None:
        item_id = os.getenv("MONDAY_ITEM_ID")
    if not api_token or not item_id:
        print("Monday upload skipped: MONDAY_API_TOKEN or MONDAY_ITEM_ID not configured.")
        return
    if body_text is None:
        body_text = f"Report attached as self-contained HTML. Open in any browser — all charts are embedded inline."

    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) { id }
    }
    """
    resp = requests.post(
        MONDAY_API_URL,
        headers={"Authorization": api_token, "Content-Type": "application/json"},
        json={"query": update_query, "variables": {"item_id": str(item_id), "body": body_text}},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday update creation failed: {data['errors']}")
    update_id = data["data"]["create_update"]["id"]

    file_query = """
    mutation ($update_id: ID!, $file: File!) {
      add_file_to_update(update_id: $update_id, file: $file) { id }
    }
    """
    html_file = Path(html_path)
    if not html_file.exists():
        print(f"Monday file attach skipped: {html_path} not found.")
        return
    with open(html_file, "rb") as f:
        file_resp = requests.post(
            MONDAY_FILE_API_URL,
            headers={"Authorization": api_token},
            data={
                "query": file_query,
                "variables": '{"update_id": "' + str(update_id) + '", "file": null}',
                "map": '{"file": ["variables.file"]}',
            },
            files={"file": (html_filename, f, "text/html")},
            timeout=120,
        )
    file_resp.raise_for_status()
    file_data = file_resp.json()
    if "errors" in file_data:
        raise RuntimeError(f"Monday file attach failed: {file_data['errors']}")
    print(f"Uploaded {html_filename} to Monday.com successfully.")

