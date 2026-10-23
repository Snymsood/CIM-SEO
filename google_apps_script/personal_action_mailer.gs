/**
 * CIM SEO personal action report receiver.
 * Deploy as a web app: execute as me; access anyone. A random token in Script
 * Properties authenticates GitHub; recipient is fixed in Script Properties.
 * Required Script Properties: WEBHOOK_TOKEN, REPORT_TO.
 */
function doPost(e) {
  const output = (value) => ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
  let payload;
  try {
    payload = JSON.parse(e.postData.contents || '{}');
  } catch (_) {
    return output({ok: false, error: 'invalid_json'});
  }

  const properties = PropertiesService.getScriptProperties();
  const expectedToken = properties.getProperty('WEBHOOK_TOKEN');
  const recipient = properties.getProperty('REPORT_TO');
  if (!expectedToken || !payload.token || payload.token !== expectedToken) {
    return output({ok: false, error: 'unauthorized'});
  }
  if (!recipient || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient)) {
    return output({ok: false, error: 'recipient_not_configured'});
  }

  const periodId = String(payload.period_id || '');
  const htmlBody = String(payload.html_body || '');
  const body = String(payload.text_body || '');
  const actionCount = Number(payload.action_count);
  if (!/^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}$/.test(periodId) ||
      !Number.isInteger(actionCount) || actionCount < 1 || actionCount > 5 ||
      body.length < 50 || body.length > 50000 ||
      htmlBody.length < 50 || htmlBody.length > 150000) {
    return output({ok: false, error: 'invalid_report'});
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const key = 'SENT_' + periodId;
    if (properties.getProperty(key)) {
      return output({ok: true, duplicate: true, period_id: periodId});
    }
    if (MailApp.getRemainingDailyQuota() < 1) {
      return output({ok: false, error: 'mail_quota_exhausted'});
    }
    MailApp.sendEmail({
      to: recipient,
      subject: 'Your ' + actionCount + ' SEO priorities | week ending ' + periodId.slice(-10),
      body: body,
      htmlBody: htmlBody,
      name: 'CIM SEO Weekly Actions'
    });
    properties.setProperty(key, new Date().toISOString());
    return output({ok: true, period_id: periodId});
  } catch (error) {
    return output({ok: false, error: 'send_failed'});
  } finally {
    lock.releaseLock();
  }
}
