#!/usr/bin/env python3
"""
Test script to verify Google Sheets connection and permissions.
"""

import os
import sys
import gspread
from google_sheets_db import get_sheets_client

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw")

def test_connection():
    """Test the Google Sheets connection."""
    print("\n" + "="*80)
    print("GOOGLE SHEETS CONNECTION TEST")
    print("="*80)
    
    # Check if key file exists
    if not os.path.exists("gsc-key.json"):
        print("\n✗ ERROR: gsc-key.json not found")
        print("  This file is required for authentication.")
        return False
    
    print("\n✓ Service account key file found")
    
    # Check if GOOGLE_SHEET_ID is set
    if not GOOGLE_SHEET_ID:
        print("\n✗ ERROR: GOOGLE_SHEET_ID environment variable not set")
        print("  Set it with: export GOOGLE_SHEET_ID='your-sheet-id'")
        return False
    
    print(f"✓ Google Sheet ID configured: {GOOGLE_SHEET_ID}")
    
    # Try to authenticate
    print("\n→ Attempting to authenticate with Google Sheets API...")
    client = get_sheets_client()
    
    if not client:
        print("✗ ERROR: Failed to authenticate")
        return False
    
    print("✓ Successfully authenticated with Google Sheets API")
    
    # Try to open the spreadsheet
    print(f"\n→ Attempting to open spreadsheet: {GOOGLE_SHEET_ID}")
    try:
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        print(f"✓ Successfully opened spreadsheet: '{spreadsheet.title}'")
    except gspread.exceptions.SpreadsheetNotFound:
        print("\n✗ ERROR: Spreadsheet not found or no access")
        print("\nPOSSIBLE CAUSES:")
        print("  1. The service account doesn't have access to this sheet")
        print("  2. The sheet ID is incorrect")
        print("\nTO FIX:")
        print("  1. Run: python show_service_account_email.py")
        print("  2. Copy the service account email")
        print("  3. Open your Google Sheet")
        print("  4. Click 'Share' and add the service account email")
        print("  5. Grant 'Editor' permissions")
        return False
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        return False
    
    # Try to list worksheets
    print("\n→ Listing worksheets...")
    try:
        worksheets = spreadsheet.worksheets()
        print(f"✓ Found {len(worksheets)} worksheet(s):")
        for ws in worksheets:
            print(f"  - {ws.title} ({ws.row_count} rows × {ws.col_count} cols)")
    except Exception as e:
        print(f"✗ ERROR listing worksheets: {e}")
        return False
    
    # Check if monthly_kpis tab exists
    print("\n→ Checking for 'monthly_kpis' worksheet...")
    try:
        monthly_kpis_ws = spreadsheet.worksheet("monthly_kpis")
        print(f"✓ 'monthly_kpis' worksheet exists")
        print(f"  Rows: {monthly_kpis_ws.row_count}")
        print(f"  Columns: {monthly_kpis_ws.col_count}")
        
        # Try to read headers
        headers = monthly_kpis_ws.row_values(1)
        if headers:
            print(f"  Headers: {', '.join(headers[:5])}{'...' if len(headers) > 5 else ''}")
    except gspread.exceptions.WorksheetNotFound:
        print("⚠ 'monthly_kpis' worksheet not found (will be created on first run)")
    except Exception as e:
        print(f"⚠ Could not read 'monthly_kpis' worksheet: {e}")
    
    # Test write permissions
    print("\n→ Testing write permissions...")
    try:
        # Try to get or create a test worksheet
        try:
            test_ws = spreadsheet.worksheet("_connection_test")
        except gspread.exceptions.WorksheetNotFound:
            test_ws = spreadsheet.add_worksheet(title="_connection_test", rows="10", cols="5")
            print("✓ Created test worksheet '_connection_test'")
        
        # Try to write a test value
        test_ws.update_acell('A1', 'Connection Test')
        print("✓ Successfully wrote test data")
        
        # Try to read it back
        value = test_ws.acell('A1').value
        if value == 'Connection Test':
            print("✓ Successfully read test data")
        
        # Clean up test worksheet
        spreadsheet.del_worksheet(test_ws)
        print("✓ Cleaned up test worksheet")
        
    except Exception as e:
        print(f"✗ ERROR testing write permissions: {e}")
        print("\nThe service account may only have 'Viewer' permissions.")
        print("Please grant 'Editor' permissions to the service account.")
        return False
    
    # All tests passed
    print("\n" + "="*80)
    print("✓ ALL TESTS PASSED - Google Sheets is properly configured!")
    print("="*80)
    print("\nThe monthly dashboard will be able to log KPIs to this sheet.")
    print(f"Sheet URL: https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit")
    print("\n")
    
    return True


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
