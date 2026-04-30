#!/bin/bash
# Script to extract service account email from GitHub secrets

echo "================================================================================"
echo "EXTRACTING SERVICE ACCOUNT EMAIL FROM GITHUB SECRETS"
echo "================================================================================"
echo ""
echo "Fetching the service account email from your GitHub secrets..."
echo ""

# Get the secret and extract the email using jq
SERVICE_EMAIL=$(gh secret list | grep GSC_SERVICE_ACCOUNT_KEY > /dev/null && \
  gh api repos/Snymsood/CIM-SEO/actions/runs?per_page=1 --jq '.workflow_runs[0].id' | \
  xargs -I {} gh run view {} --log 2>/dev/null | \
  grep -o '"client_email"[[:space:]]*:[[:space:]]*"[^"]*"' | \
  head -1 | \
  sed 's/"client_email"[[:space:]]*:[[:space:]]*"\([^"]*\)"/\1/')

if [ -z "$SERVICE_EMAIL" ]; then
  echo "⚠️  Could not extract email from recent workflow logs."
  echo ""
  echo "ALTERNATIVE METHOD:"
  echo "================================================================================"
  echo ""
  echo "1. Go to your Google Cloud Console:"
  echo "   https://console.cloud.google.com/"
  echo ""
  echo "2. Select your project"
  echo ""
  echo "3. Go to: IAM & Admin → Service Accounts"
  echo ""
  echo "4. Find the service account used for SEO reporting"
  echo ""
  echo "5. Copy the email (looks like: name@project.iam.gserviceaccount.com)"
  echo ""
  echo "================================================================================"
  echo ""
  echo "OR run a test workflow to see it in the logs:"
  echo "   gh workflow run 'Test Google Sheets Connection'"
  echo "   sleep 30"
  echo "   gh run view --log | grep client_email"
  echo ""
else
  echo "✓ Found service account email!"
  echo ""
  echo "================================================================================"
  echo "SERVICE ACCOUNT EMAIL"
  echo "================================================================================"
  echo ""
  echo "  $SERVICE_EMAIL"
  echo ""
  echo "================================================================================"
  echo ""
  echo "NEXT STEPS:"
  echo "================================================================================"
  echo ""
  echo "1. Open your Google Sheet:"
  echo "   https://docs.google.com/spreadsheets/d/19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw/edit"
  echo ""
  echo "2. Click the 'Share' button (top right)"
  echo ""
  echo "3. Add this email: $SERVICE_EMAIL"
  echo ""
  echo "4. Set permission to 'Editor'"
  echo ""
  echo "5. Uncheck 'Notify people'"
  echo ""
  echo "6. Click 'Share'"
  echo ""
  echo "7. Test the connection:"
  echo "   gh workflow run 'Test Google Sheets Connection'"
  echo ""
  echo "================================================================================"
fi
