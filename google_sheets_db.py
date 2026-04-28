import os
import gspread
import pandas as pd
from datetime import date

KEY_FILE = "gsc-key.json"
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

def get_sheets_client():
    if not os.path.exists(KEY_FILE):
        print("Warning: Google Service Account key file not found. Cannot connect to Google Sheets.")
        return None
    try:
        return gspread.service_account(filename=KEY_FILE)
    except Exception as e:
        print(f"Error authenticating with Google Sheets: {e}")
        return None

def append_to_sheet(df, tab_name):
    """
    Appends a Pandas DataFrame to a specific tab in the Google Sheet.
    If the tab does not exist, it will be created.
    A 'date_added' column is automatically prefixed to track historical data.
    """
    if df.empty:
        print(f"DataFrame is empty. Skipping upload to '{tab_name}'.")
        return

    if not GOOGLE_SHEET_ID:
        print("GOOGLE_SHEET_ID is not configured. Skipping upload.")
        return

    client = get_sheets_client()
    if not client:
        return

    try:
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    except Exception as e:
        print(f"Error opening spreadsheet ID {GOOGLE_SHEET_ID}: {e}")
        return

    # Try to open worksheet, create if it doesn't exist
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"Tab '{tab_name}' not found. Creating it...")
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows="1000", cols=str(len(df.columns) + 1))
        # Add headers for the new sheet
        headers = ["date_added"] + list(df.columns)
        worksheet.append_row(headers)

    # Prepare data
    upload_df = df.copy()
    upload_df.insert(0, "date_added", date.today().isoformat())
    
    # Convert NaNs and complex types to string for JSON serialization
    upload_df = upload_df.fillna("")
    data_to_upload = upload_df.values.tolist()

    try:
        worksheet.append_rows(data_to_upload)
        print(f"Successfully appended {len(data_to_upload)} rows to '{tab_name}' tab.")
    except Exception as e:
        print(f"Failed to append rows to '{tab_name}': {e}")
