#!/usr/bin/env python3
"""
Helper script to show the service account email from gsc-key.json
This email needs to be granted access to your Google Sheet.
"""

import json
import os

KEY_FILE = "gsc-key.json"

if os.path.exists(KEY_FILE):
    with open(KEY_FILE, 'r') as f:
        key_data = json.load(f)
        email = key_data.get('client_email', 'Not found')
        print("\n" + "="*80)
        print("SERVICE ACCOUNT EMAIL")
        print("="*80)
        print(f"\n{email}\n")
        print("="*80)
        print("\nTO FIX GOOGLE SHEETS ACCESS:")
        print("="*80)
        print("1. Open your Google Sheet")
        print("2. Click 'Share' button (top right)")
        print(f"3. Add this email: {email}")
        print("4. Give it 'Editor' permissions")
        print("5. Click 'Send' (uncheck 'Notify people')")
        print("\nThen your monthly dashboard will be able to log KPIs to Google Sheets!")
        print("="*80)
else:
    print(f"\nError: {KEY_FILE} not found in current directory.")
    print("This file should be present when running locally with credentials.")
