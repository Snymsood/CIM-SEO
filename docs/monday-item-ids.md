# Monday.com Item IDs

This repo posts each report to a specific Monday.com item. The value needed is the item ID, also called a pulse ID in Monday URLs. It is not the board ID.

## How to find an item ID

### From the browser URL

1. Open the Monday board that stores the CIM SEO report items.
2. Open the item that should receive a report update.
3. Copy the URL from the browser.
4. Use the number after `/pulses/` as the item ID.

Examples:

```text
https://example.monday.com/boards/123456789/pulses/987654321
```

The board ID is `123456789`; the item ID is `987654321`.

Some Monday URLs include the item as a query parameter instead. If the URL contains `itemId=987654321`, use that number.

### From the Monday API

Use the board ID from the board URL and query item names with IDs:

```graphql
query {
  boards(ids: 123456789) {
    items_page(limit: 100) {
      items {
        id
        name
      }
    }
  }
}
```

Create one item per standalone report under the same board, then save each item ID as a GitHub secret.

## Required report item secrets

| Secret | Monday item should receive |
| --- | --- |
| `MONDAY_GSC_ITEM_ID` | GSC weekly report |
| `MONDAY_GA4_WEEKLY_ITEM_ID` | GA4 weekly report |
| `MONDAY_SITE_SPEED_ITEM_ID` | Site speed monitoring report |
| `MONDAY_GSC_KEYWORD_ITEM_ID` | Keyword ranking report |
| `MONDAY_GSC_LANDING_ITEM_ID` | Critical landing pages report |
| `MONDAY_BROKEN_LINK_ITEM_ID` | Broken link audit |
| `MONDAY_INTERNAL_LINK_ITEM_ID` | Internal linking audit |
| `MONDAY_CONTENT_AUDIT_ITEM_ID` | Content audit schedule report |
| `MONDAY_INTELLIGENCE_ITEM_ID` | Weekly SEO intelligence/action queue |
| `MONDAY_EVENT_REPORT_ITEM_ID` | GA4 custom event report |
| `MONDAY_CONTENT_CATEGORY_ITEM_ID` | Content category performance report |
| `MONDAY_AI_SNIPPET_ITEM_ID` | AI snippet verification report |
| `MONDAY_MASTER_ITEM_ID` | Weekly master orchestrator summary |
| `MONDAY_MONTHLY_ITEM_ID` | Monthly master dashboard summary |

`MONDAY_ITEM_ID` is the legacy GSC weekly item secret. `MONDAY_GSC_ITEM_ID` is preferred; the workflows fall back to `MONDAY_ITEM_ID` while migrating.

## Set the secrets

Use the GitHub CLI from this repo:

```bash
gh secret set MONDAY_GSC_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_GA4_WEEKLY_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_SITE_SPEED_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_GSC_KEYWORD_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_GSC_LANDING_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_BROKEN_LINK_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_INTERNAL_LINK_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_CONTENT_AUDIT_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_INTELLIGENCE_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_EVENT_REPORT_ITEM_ID -b"ITEM_ID"
gh secret set MONDAY_CONTENT_CATEGORY_ITEM_ID -b"ITEM_ID"
```

Optional model override:

```bash
gh variable set GROQ_MODEL -b"openai/gpt-oss-120b"
```

