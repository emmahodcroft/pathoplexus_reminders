# Pathoplexus Reminder Bot

Sends weekly Slack reminders for upcoming deadlines — funding reports, annual GA, 
annual reports, and EB/SAB/officer term renewals.

Runs every Monday at 08:00 UTC via GitHub Actions. Can also be triggered manually.

---

## Setup

### 1. Add the Slack webhook secret

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

- Name: `SLACK_WEBHOOK_URL`
- Value: your Slack incoming webhook URL

To create a webhook: https://api.slack.com/messaging/webhooks

### 2. That's it

The workflow file is already in `.github/workflows/weekly_reminders.yml`.  
Push to `main` and the bot will run every Monday.

To test immediately: **Actions → Weekly Reminders → Run workflow**.  
Set `dry_run = true` to print output to the console without posting to Slack.

---

## Editing reminders

All configuration lives in **`reminders.yaml`**. Edit it directly and push — 
the next run will pick up the changes.

### Adding a new funder

Under `funding_reports > items`, copy an existing entry and update:
- `name`
- `annual_deadline_dates` (list of `MM-DD` strings)
- `remind_before_days`
- `what_to_do`

### Adding a new category

Add a new top-level key under `categories`. If you're in a hurry and don't need 
custom formatting, just give each item a `deadline: YYYY-MM-DD` field and 
`remind_before_days` — the bot's generic fallback handler will take care of it.

For a fully custom handler (custom message format, sub-deadlines, etc.), 
add a function in `reminder_bot.py` and register it in `CATEGORY_HANDLERS`.

### Updating a term renewal

When an EB/SAB member or officer is re-elected, add or update the `renewal_date` 
field for that person in `reminders.yaml`:

```yaml
- name: "Emma Hodcroft"
  start_date: "2024-08-12"
  renewal_date: "2026-08-12"   # ← add this when re-elected
```

The bot uses `renewal_date` instead of `start_date` when calculating term expiry.

---

## Reminder logic summary

| Category | How deadline is calculated | Alert window |
|---|---|---|
| Funding reports | Fixed `MM-DD` each year, auto-recurs | 30 / 14 / 7 days before |
| Annual GA | Fixed `MM-DD` each year (Apr 30) | 60 / 30 days before |
| GA sub-deadlines | Relative to GA date (agenda etc.) | Within 14 days |
| Annual reports | Relative to GA date (−30 days) | 90 / 60 days before GA |
| EB terms | 2 years from start/renewal date | 60 days before expiry |
| SAB terms | 2 years from start/renewal date | 30 days before expiry |
| Other roles | 2 years from start/renewal date | 60 days before expiry |
| Generic (new) | `deadline: YYYY-MM-DD` field | As set in item |

If nothing is due within alert windows, the bot posts an all-clear message.

---

## Files

```
reminders.yaml              ← edit this to manage all reminders
reminder_bot.py             ← bot logic (edit to add custom handlers)
.github/workflows/
  weekly_reminders.yml      ← GitHub Actions schedule
```
