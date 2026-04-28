import pandas as pd
import html
import math

def safe_pct_change(current, previous):
    try:
        if pd.isna(current) or pd.isna(previous):
            return None
        current = float(current)
        previous = float(previous)
        if previous == 0:
            return None
        return ((current - previous) / previous)
    except (ValueError, TypeError):
        return None

def format_pct_change(current, previous):
    pct = safe_pct_change(current, previous)
    if pct is None or pct == 0 or math.isclose(pct, 0.0, abs_tol=1e-5):
        return "-"
    return f"{pct:+.1%}"

def format_delta(value, decimals=0):
    try:
        if pd.isna(value):
            return "-"
        val = float(value)
        if val == 0 or math.isclose(val, 0.0, abs_tol=1e-5):
            return "-"
        if val > 0:
            return f"+{val:.{decimals}f}"
        return f"{val:.{decimals}f}"
    except (ValueError, TypeError):
        return "-"

def format_num(value, decimals=0, as_percent=False):
    try:
        if pd.isna(value):
            return "-"
        val = float(value)
        if val == 0 and not as_percent:
            return "-"
        if as_percent:
            return f"{val:.2%}"
        if decimals == 0:
            return f"{val:,.0f}"
        return f"{val:,.{decimals}f}"
    except (ValueError, TypeError):
        return "-"

def get_pdf_css():
    return """
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
    
    @page {
        size: A4;
        margin: 15mm;
        @bottom-right {
            content: "Page " counter(page);
            color: #64748B;
            font-size: 9px;
            font-family: 'Poppins', sans-serif;
        }
    }
    body {
        font-family: 'Poppins', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #1A1A1A;
        background: #FFFFFF;
        line-height: 1.6;
        font-size: 11px;
        margin: 0;
        padding: 0;
    }
    .header-bar {
        background: #212878;
        color: #FFFFFF;
        padding: 20px 25px;
        margin: -15mm -15mm 20px -15mm;
        border-bottom: 4px solid #000000;
    }
    .header-bar h1 {
        margin: 0;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: #FFFFFF;
    }
    .header-bar .subtitle {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 1px;
        opacity: 0.9;
        margin-top: 4px;
    }
    h1 {
        font-size: 24px;
        color: #212878;
        margin-bottom: 10px;
        font-weight: 700;
    }
    h2 {
        font-size: 16px;
        color: #212878;
        margin-top: 30px;
        margin-bottom: 12px;
        font-weight: 600;
        border-left: 4px solid #212878;
        padding-left: 10px;
    }
    .muted {
        color: #64748B;
        font-size: 10px;
        margin-bottom: 20px;
        font-weight: 500;
    }
    .panel {
        background: #F8FAFC;
        border-radius: 4px;
        padding: 16px;
        margin-bottom: 24px;
        border: 1px solid #E2E8F0;
        border-top: 3px solid #212878;
    }
    .panel h2 {
        margin-top: 0;
        border-left: none;
        padding-left: 0;
        color: #1A1A1A;
        font-size: 14px;
        margin-bottom: 8px;
    }
    .grid {
        display: block;
        margin-bottom: 24px;
        width: 100%;
        clear: both;
    }
    .card {
        display: inline-block;
        width: 22%;
        margin-right: 2.5%;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 4px;
        padding: 16px;
        vertical-align: top;
        box-shadow: 0 2px 4px rgba(33, 40, 120, 0.05);
        border-bottom: 3px solid #E2E8F0;
        transition: border-color 0.3s;
    }
    .card:last-child { margin-right: 0; }
    .label {
        font-size: 9px;
        text-transform: uppercase;
        color: #64748B;
        font-weight: 600;
        margin-bottom: 8px;
        letter-spacing: 0.5px;
    }
    .value {
        font-size: 22px;
        font-weight: 700;
        color: #212878;
        margin-bottom: 6px;
    }
    .sub {
        font-size: 10px;
        color: #94A3B8;
        margin-bottom: 4px;
    }
    .delta {
        font-weight: 600;
        font-size: 11px;
        padding: 2px 6px;
        border-radius: 3px;
        display: inline-block;
    }
    .delta.pos { background: #ECFDF5; color: #059669; }
    .delta.neg { background: #FEF2F2; color: #DC2626; }
    .delta.neu { background: #F8FAFC; color: #64748B; }
    
    table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 24px;
        font-size: 10px;
    }
    th, td {
        text-align: left;
        padding: 10px 12px;
        border-bottom: 1px solid #E2E8F0;
    }
    th {
        background: #212878;
        color: #FFFFFF;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 9px;
        letter-spacing: 0.5px;
    }
    tr:nth-child(even) td {
        background: #F8FAFC;
    }
    tr:hover td {
        background: #F1F5F9;
    }
    .ai-block {
        white-space: pre-wrap;
        color: #1E293B;
        font-size: 11px;
        line-height: 1.7;
    }
    .break-before {
        page-break-before: always;
    }
    .chart-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 4px;
        padding: 16px;
        margin-bottom: 24px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    """

def html_table_from_df(df, columns, rename_map=None):
    if df.empty:
        return "<p class='muted'>No data available to display.</p>"
        
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        lower_col = col.lower()
        if "rate" in lower_col or "ctr" in lower_col:
            work[col] = work[col].apply(lambda x: format_num(x, as_percent=True))
        elif "change" in lower_col or "δ" in lower_col or "delta" in lower_col:
            decimals = 2 if "position" in lower_col or "ctr" in lower_col or "score" in lower_col else 0
            work[col] = work[col].apply(lambda x: format_delta(x, decimals))
        elif "position" in lower_col:
            work[col] = work[col].apply(lambda x: format_num(x, 2))
        else:
            # Try to format as numeric
            def convert_numeric(x):
                try:
                    f = float(x)
                    if pd.isna(f): return "-"
                    if f == 0: return "-"
                    return format_num(f, 0)
                except Exception:
                    val_str = str(x)
                    if val_str == "nan" or val_str == "None": return "-"
                    if len(val_str) > 60: return val_str[:57] + "..."
                    return val_str
            work[col] = work[col].apply(convert_numeric)

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    body_rows = []
    for row in work.values.tolist():
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"

def build_card(title, current, previous, is_pct=False, decimals=0):
    if is_pct:
        curr_str = format_num(current, as_percent=True)
        prev_str = format_num(previous, as_percent=True)
        delta_str = format_pct_change(current, previous)
    else:
        curr_str = format_num(current, decimals)
        prev_str = format_num(previous, decimals)
        # Use simple delta for non-percentages if we want, or percent change
        delta_str = format_pct_change(current, previous)
        
    if delta_str == "-":
        curr_str = curr_str if curr_str != "-" else "N/A"
        prev_str = prev_str if prev_str != "-" else "N/A"
        delta_str = ""

    delta_class = "neu"
    if delta_str.startswith("+"):
        delta_class = "pos"
    elif delta_str.startswith("-") and delta_str != "-":
        delta_class = "neg"

    return f"""
    <div class="card">
        <div class="label">{html.escape(title)}</div>
        <div class="value">{html.escape(curr_str)}</div>
        <div class="sub">Prev: {html.escape(prev_str)}</div>
        <div class="delta {delta_class}">{html.escape(delta_str)}</div>
    </div>
    """
