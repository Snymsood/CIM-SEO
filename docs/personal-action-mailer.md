# Google-native delivery for the personal action report

GitHub Actions generates `weekly_personal_action_report.html`, `.txt`, and
`.json` after the weekly intelligence run. Gmail SMTP has closed the connection
during authentication from the hosted GitHub runner on both ports 465 and 587.
The [Google Apps Script web app](https://developers.google.com/apps-script/guides/web)
in this repo sends the saved report through
[MailApp](https://developers.google.com/apps-script/reference/mail/mail-app)
over HTTPS. It uses the Gmail account that deploys the script and requires no
paid email API.

## One-time setup in the sending Google account

1. Open [Google Apps Script](https://script.google.com/) while signed in as the
   Gmail account that should send the report. Create a **New project**.
2. Replace its `Code.gs` contents with
   [`google_apps_script/personal_action_mailer.gs`](../google_apps_script/personal_action_mailer.gs)
   and save the project.
3. In **Project Settings → Script properties**, add:
   - `REPORT_TO`: the personal recipient address already configured in the
     GitHub `SEO_ACTION_REPORT_TO` secret
   - `WEBHOOK_TOKEN`: a long random value, at least 32 characters. A password
     manager can generate it. Keep a copy for the matching GitHub secret.
4. Choose **Deploy → New deployment → Web app**. Set **Execute as: Me** and
   **Who has access: Anyone**. Authorize MailApp when Google prompts you, then
   copy the deployment URL ending in `/exec`.
5. In GitHub repository **Settings → Secrets and variables → Actions**, create
   two repository secrets:
   - `SEO_ACTION_APPS_SCRIPT_URL`: the `/exec` URL
   - `SEO_ACTION_APPS_SCRIPT_TOKEN`: exactly the same `WEBHOOK_TOKEN` value

The repository variable `SEO_ACTION_DELIVERY_MODE` is set to
`google_apps_script` so scheduled runs will use this route. Until both secrets
are present, delivery fails immediately with a configuration error; it does
not attempt Gmail SMTP again.

The endpoint accepts only a matching random token, sends only to the fixed
`REPORT_TO` address, validates the report shape, and records the completed
reporting week to suppress repeat sends. The GitHub sender checks for a JSON
confirmation before marking delivery successful. The token and personal email
address are not committed to source control.

After configuring both secrets, dispatch `weekly-seo-intelligence.yml` with
`delivery_only=true` and `source_run_id=39890793845` to send the already
generated October 12–18 report without publishing another Monday update. The
scheduled Monday run uses this HTTPS route whenever both Apps Script secrets
are present. If either is missing, the workflow fails visibly rather than
silently claiming email delivery.

[Apps Script mail quotas](https://developers.google.com/apps-script/guides/services/quotas)
currently allow far more than this one-recipient weekly report; quotas can
change, and a quota failure is returned to the workflow as a delivery failure.
