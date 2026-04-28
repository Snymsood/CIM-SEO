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
    @page {
        size: A4;
        margin: 18mm 15mm;
        @bottom-right {
            content: "Page " counter(page);
            color: #94A3B8;
            font-size: 10px;
        }
    }
    body {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #1E293B;
        background: #FFFFFF;
        line-height: 1.5;
        font-size: 11px;
    }
    h1 {
        font-size: 24px;
        color: #0F172A;
        margin-bottom: 6px;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .muted {
        color: #64748B;
        font-size: 11px;
        margin-bottom: 20px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    h2 {
        font-size: 15px;
        color: #0F172A;
        margin-top: 28px;
        margin-bottom: 10px;
        border-bottom: 1px solid #E2E8F0;
        padding-bottom: 4px;
    }
    .panel {
        background: #F8FAFC;
        border-radius: 6px;
        padding: 14px;
        margin-bottom: 20px;
        border: 1px solid #E2E8F0;
    }
    .panel h2 {
        margin-top: 0;
        border: none;
        padding: 0;
    }
    .grid {
        display: block;
        margin-bottom: 20px;
    }
    .card {
        display: inline-block;
        width: 22%;
        margin-right: 2%;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 14px;
        vertical-align: top;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .label {
        font-size: 9px;
        text-transform: uppercase;
        color: #64748B;
        font-weight: 600;
        margin-bottom: 6px;
    }
    .value {
        font-size: 20px;
        font-weight: 700;
        color: #0F172A;
        margin-bottom: 4px;
    }
    .sub {
        font-size: 10px;
        color: #64748B;
    }
    .delta {
        font-weight: 600;
        margin-top: 4px;
        font-size: 11px;
    }
    .delta.pos { color: #10B981; }
    .delta.neg { color: #EF4444; }
    .delta.neu { color: #64748B; }
    
    table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 20px;
        font-size: 10px;
    }
    th, td {
        text-align: left;
        padding: 8px 10px;
        border-bottom: 1px solid #E2E8F0;
    }
    th {
        background: #F1F5F9;
        color: #475569;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 9px;
    }
    tr:nth-child(even) td {
        background: #F8FAFC;
    }
    .ai-block {
        white-space: pre-wrap;
        color: #334155;
    }
    .break-before {
        page-break-before: always;
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
                except:
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
