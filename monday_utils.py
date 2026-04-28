import os
import json
import requests

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"


def upload_pdf_to_monday(pdf_path, body_text, pdf_filename, api_token=None, item_id=None):
    """Upload a PDF to a Monday.com item as an update attachment.

    Args:
        pdf_path:     Local path to the PDF file.
        body_text:    Text body for the Monday.com update.
        pdf_filename: Filename shown in the Monday.com attachment.
        api_token:    Monday.com API token. Defaults to MONDAY_API_TOKEN env var.
        item_id:      Monday.com item ID. Defaults to MONDAY_ITEM_ID env var.
    """
    if api_token is None:
        api_token = os.getenv("MONDAY_API_TOKEN")
    if item_id is None:
        item_id = os.getenv("MONDAY_ITEM_ID")

    if not api_token or not item_id:
        print("Skipping monday file upload: MONDAY_API_TOKEN or MONDAY_ITEM_ID not configured.")
        return

    # Step 1 — create an update on the item
    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) {
        id
      }
    }
    """
    update_response = requests.post(
        MONDAY_API_URL,
        headers={"Authorization": api_token, "Content-Type": "application/json"},
        json={"query": update_query, "variables": {"item_id": str(item_id), "body": body_text}},
        timeout=60,
    )
    update_response.raise_for_status()
    update_data = update_response.json()

    if "errors" in update_data:
        raise RuntimeError(f"Monday update creation failed: {update_data['errors']}")

    update_id = update_data["data"]["create_update"]["id"]

    # Step 2 — attach the PDF file to that update
    file_query = """
    mutation ($update_id: ID!, $file: File!) {
      add_file_to_update(update_id: $update_id, file: $file) {
        id
      }
    }
    """
    with open(pdf_path, "rb") as f:
        response = requests.post(
            MONDAY_FILE_API_URL,
            headers={"Authorization": api_token},
            data={
                "query": file_query,
                "variables": json.dumps({"update_id": str(update_id), "file": None}),
                "map": json.dumps({"pdf": ["variables.file"]}),
            },
            files={"pdf": (pdf_filename, f, "application/pdf")},
            timeout=120,
        )

    print("Monday file upload status:", response.status_code)
    if response.status_code != 200:
        print("Monday file upload response:", response.text)
    response.raise_for_status()
    resp_data = response.json()
    if "errors" in resp_data:
        raise RuntimeError(f"Monday file upload failed: {resp_data['errors']}")
    print(f"Uploaded '{pdf_filename}' to Monday.com update successfully.")
