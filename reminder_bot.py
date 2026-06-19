#!/usr/bin/env python3
"""
Pathoplexus Reminder Bot
========================
Reads reminders.yaml, calculates upcoming deadlines, and posts to Slack.
Runs weekly via GitHub Actions.

Requirements: pip install pyyaml requests python-dateutil
"""

import os
import sys
import yaml
import requests
import json
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
YAML_PATH = os.environ.get("REMINDERS_YAML", "reminders.yaml")
# How far ahead to look (days). Items due within this window get a reminder.
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "90"))
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def today() -> date:
    return date.today()


def next_annual_date(month_day: str, from_date: Optional[date] = None) -> date:
    """Given 'MM-DD', return the next upcoming date with that month/day."""
    ref = from_date or today()
    year = ref.year
    mm, dd = map(int, month_day.split("-"))
    candidate = date(year, mm, dd)
    if candidate <= ref:
        candidate = date(year + 1, mm, dd)
    return candidate


def term_expiry(start_str: str, renewal_str: Optional[str], term_years: int) -> date:
    """Calculate when a term expires, using renewal_date if present."""
    base_str = renewal_str if renewal_str else start_str
    base = date.fromisoformat(base_str)
    return base + relativedelta(years=term_years)


def days_until(target: date) -> int:
    return (target - today()).days


# ---------------------------------------------------------------------------
# Slack posting
# ---------------------------------------------------------------------------

def post_to_slack(blocks: list):
    """Post a message to Slack via webhook."""
    if DRY_RUN:
        print("DRY RUN — would post to Slack:")
        print(json.dumps({"blocks": blocks}, indent=2))
        return

    if not SLACK_WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL not set.", file=sys.stderr)
        sys.exit(1)

    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json={"blocks": blocks},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"ERROR: Slack returned {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)


def header_block(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": text}}


def section_block(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def divider_block() -> dict:
    return {"type": "divider"}


def urgency_emoji(days: int) -> str:
    if days <= 7:
        return "🔴"
    elif days <= 14:
        return "🟠"
    elif days <= 30:
        return "🟡"
    else:
        return "🟢"


def format_date(d: date) -> str:
    return d.strftime("%-d %B %Y")


# ---------------------------------------------------------------------------
# Reminder builders
# ---------------------------------------------------------------------------

def check_funding_reports(cat_data: dict) -> list[dict]:
    """Build reminder messages for funding report items."""
    messages = []
    for item in cat_data.get("items", []):
        name = item["name"]
        deadlines_md = item.get("annual_deadline_dates", [])
        remind_days = item.get("remind_before_days", [30, 14, 7])
        what_to_do = item.get("what_to_do", "")

        for md in deadlines_md:
            deadline = next_annual_date(md)
            d_until = days_until(deadline)
            if any(d_until <= r for r in remind_days) and d_until >= 0:
                emoji = urgency_emoji(d_until)
                blocks = [
                    header_block(f"{emoji} Funding Report Due: {name}"),
                    section_block(
                        f"*Deadline:* {format_date(deadline)} — *{d_until} days away*\n\n"
                        f"{item.get('description', '').strip()}"
                    ),
                ]
                if what_to_do:
                    blocks.append(section_block(f"*What needs to be done:*\n{what_to_do.strip()}"))
                messages.append(blocks)

    return messages


def check_annual_ga(cat_data: dict) -> list[dict]:
    """Build reminder messages for the annual GA and its sub-deadlines."""
    messages = []
    for item in cat_data.get("items", []):
        annual_deadline_date = item.get("annual_deadline_date")
        if not annual_deadline_date:
            continue

        ga_deadline = next_annual_date(annual_deadline_date)
        remind_days = item.get("remind_before_days", [60, 30])
        d_until_ga = days_until(ga_deadline)

        # Main GA reminder
        if any(d_until_ga <= r for r in remind_days) and d_until_ga >= 0:
            emoji = urgency_emoji(d_until_ga)
            blocks = [
                header_block(f"{emoji} Annual General Assembly"),
                section_block(
                    f"*GA Deadline:* {format_date(ga_deadline)} — *{d_until_ga} days away*\n\n"
                    f"{cat_data.get('description', '').strip()}"
                ),
            ]
            what_to_do = item.get("what_to_do", "")
            if what_to_do:
                blocks.append(section_block(f"*What needs to be done:*\n{what_to_do.strip()}"))
            messages.append(blocks)

        # Sub-deadline reminders (agenda etc.)
        for sub in item.get("sub_deadlines", []):
            sub_date = ga_deadline + timedelta(days=sub["offset_days"])
            d_until_sub = days_until(sub_date)
            # Alert if within 14 days of sub-deadline
            if 0 <= d_until_sub <= 14:
                emoji = urgency_emoji(d_until_sub)
                blocks = [
                    header_block(f"{emoji} GA Sub-deadline: {sub['label']}"),
                    section_block(
                        f"*Due:* {format_date(sub_date)} — *{d_until_sub} days away*\n"
                        f"_(GA itself is {format_date(ga_deadline)})_"
                    ),
                ]
                what_to_do = sub.get("what_to_do", "")
                if what_to_do:
                    blocks.append(section_block(f"*What needs to be done:*\n{what_to_do.strip()}"))
                messages.append(blocks)

    return messages


def check_annual_reports(cat_data: dict, all_categories: dict) -> list[dict]:
    """Build reminder messages for annual reports (relative to GA date)."""
    messages = []
    for item in cat_data.get("items", []):
        # Resolve the GA deadline
        relative_to = item.get("relative_to", "")
        ga_deadline = None
        if relative_to:
            cat_key, item_name = relative_to.split("/", 1)
            ref_cat = all_categories.get(cat_key, {})
            for ref_item in ref_cat.get("items", []):
                if ref_item["name"] == item_name:
                    ga_deadline = next_annual_date(ref_item["annual_deadline_date"])
                    break

        if not ga_deadline:
            continue

        offset = item.get("offset_days", -30)
        effective_deadline = ga_deadline + timedelta(days=offset)
        remind_days = item.get("remind_before_days", [90, 60])
        d_until = days_until(effective_deadline)

        if any(d_until <= r for r in remind_days) and d_until >= 0:
            emoji = urgency_emoji(d_until)
            blocks = [
                header_block(f"{emoji} Annual Reports"),
                section_block(
                    f"*Reports needed by:* {format_date(effective_deadline)} — *{d_until} days away*\n"
                    f"_(Must be ready before GA on {format_date(ga_deadline)})_\n\n"
                    f"{cat_data.get('description', '').strip()}"
                ),
            ]
            what_to_do = item.get("what_to_do", "")
            if what_to_do:
                blocks.append(section_block(f"*What needs to be done:*\n{what_to_do.strip()}"))
            messages.append(blocks)

    return messages


def check_person_terms(cat_data: dict, category_label: str) -> list[dict]:
    """
    Build reminder messages for EB/SAB/other person term renewals.
    Members expiring on the same date are grouped into a single message.
    Members with item-level what_to_do overrides always get their own message.
    """
    term_years = cat_data.get("term_years", 2)
    remind_days = cat_data.get("remind_before_days", [60])
    what_to_do_template = cat_data.get("what_to_do_template", "")

    # Collect all members that are within the alert window
    # group_key: expiry date (for grouping), or None if item has custom what_to_do
    from collections import defaultdict
    grouped: dict[date, list[dict]] = defaultdict(list)   # expiry_date → [member info]
    individual: list[dict] = []                            # members needing their own message

    for item in cat_data.get("items", []):
        name = item["name"]
        start_str = item.get("start_date")
        renewal_str = item.get("renewal_date")
        role = item.get("role", "")

        if not start_str:
            continue

        expiry = term_expiry(start_str, renewal_str, term_years)
        d_until = days_until(expiry)

        if not (any(d_until <= r for r in remind_days) and d_until >= 0):
            continue

        entry = {
            "name": name,
            "role": role,
            "expiry": expiry,
            "d_until": d_until,
            "effective_from": renewal_str or start_str,
            "what_to_do_override": item.get("what_to_do", ""),
        }

        if entry["what_to_do_override"]:
            individual.append(entry)
        else:
            grouped[expiry].append(entry)

    messages = []

    # One message per expiry-date group
    for expiry, members in sorted(grouped.items()):
        d_until = members[0]["d_until"]  # same for all in group
        emoji = urgency_emoji(d_until)

        if len(members) == 1:
            m = members[0]
            display_name = f"{m['name']} ({m['role']})" if m["role"] else m["name"]
            title = f"{emoji} {category_label} Term Expiring: {display_name}"
            detail = (
                f"*Term expires:* {format_date(expiry)} — *{d_until} days away*\n"
                f"_2-year term from {m['effective_from']}_"
            )
        else:
            names_str = ", ".join(
                f"{m['name']} ({m['role']})" if m["role"] else m["name"]
                for m in members
            )
            title = f"{emoji} {category_label} Terms Expiring: {len(members)} members"
            detail = (
                f"*Term expires:* {format_date(expiry)} — *{d_until} days away*\n"
                f"*Members:* {names_str}"
            )

        blocks = [
            header_block(title),
            section_block(detail),
        ]

        # Use template what_to_do, substituting {name} with a list when grouped
        if what_to_do_template:
            if len(members) == 1:
                what_to_do = what_to_do_template.replace("{name}", members[0]["name"])
            else:
                names_list = "\n".join(f"  - {m['name']}" for m in members)
                what_to_do = what_to_do_template.replace(
                    "{name}", f"each of the following members:\n{names_list}\n "
                )
            blocks.append(section_block(f"*What needs to be done:*\n{what_to_do.strip()}"))

        messages.append(blocks)

    # Individual messages for members with custom what_to_do
    for m in individual:
        emoji = urgency_emoji(m["d_until"])
        display_name = f"{m['name']} ({m['role']})" if m["role"] else m["name"]
        blocks = [
            header_block(f"{emoji} {category_label} Term Expiring: {display_name}"),
            section_block(
                f"*Term expires:* {format_date(m['expiry'])} — *{m['d_until']} days away*\n"
                f"_2-year term from {m['effective_from']}_"
            ),
            section_block(f"*What needs to be done:*\n{m['what_to_do_override'].strip()}"),
        ]
        messages.append(blocks)

    return messages


def check_generic_category(cat_key: str, cat_data: dict) -> list[dict]:
    """
    Fallback for categories with no custom handler.
    Looks for items with a 'deadline' field (YYYY-MM-DD) and remind_before_days.
    """
    messages = []
    label = cat_data.get("label", cat_key.replace("_", " ").title())

    for item in cat_data.get("items", []):
        deadline_str = item.get("deadline")
        if not deadline_str:
            continue
        deadline = date.fromisoformat(deadline_str)
        remind_days = item.get("remind_before_days", [30, 14])
        d_until = days_until(deadline)

        if any(d_until <= r for r in remind_days) and 0 <= d_until:
            emoji = urgency_emoji(d_until)
            blocks = [
                header_block(f"{emoji} {label}: {item.get('name', 'Upcoming deadline')}"),
                section_block(
                    f"*Deadline:* {format_date(deadline)} — *{d_until} days away*\n\n"
                    f"{item.get('description', cat_data.get('description', '')).strip()}"
                ),
            ]
            what_to_do = item.get("what_to_do", "")
            if what_to_do:
                blocks.append(section_block(f"*What needs to be done:*\n{what_to_do.strip()}"))
            messages.append(blocks)

    return messages


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CATEGORY_HANDLERS = {
    "funding_reports": check_funding_reports,
    "annual_ga": check_annual_ga,
    # annual_reports and person terms handled separately due to extra args
}

PERSON_TERM_CATEGORIES = {"eb_terms", "sab_terms", "other_roles"}


def main():
    with open(YAML_PATH) as f:
        config = yaml.safe_load(f)

    categories = config.get("categories", {})
    all_messages = []

    for cat_key, cat_data in categories.items():
        if cat_key in CATEGORY_HANDLERS:
            all_messages.extend(CATEGORY_HANDLERS[cat_key](cat_data))

        elif cat_key == "annual_reports":
            all_messages.extend(check_annual_reports(cat_data, categories))

        elif cat_key in PERSON_TERM_CATEGORIES:
            label = cat_data.get("label", cat_key.replace("_", " ").title())
            all_messages.extend(check_person_terms(cat_data, label))

        else:
            # Generic fallback for any new categories
            all_messages.extend(check_generic_category(cat_key, cat_data))

    if not all_messages:
        post_to_slack([
            header_block("✅ Pathoplexus Weekly Reminders"),
            section_block(
                f"_Check run: {format_date(today())}_\n\n"
                "No upcoming deadlines within the alert window. Nothing to action this week."
            ),
        ])
        print("No reminders to send — posted all-clear.")
        return

    # Post each reminder as a separate message
    print(f"Sending {len(all_messages)} reminder(s)...")
    for i, blocks in enumerate(all_messages):
        # Add a small header on first message only
        if i == 0:
            blocks = [
                section_block(f"*Pathoplexus Reminders — {format_date(today())}*"),
                divider_block(),
            ] + blocks
        post_to_slack(blocks)
        print(f"  Posted: {blocks[0].get('text', {}).get('text', '(message)')[:60]}")

    print("Done.")


if __name__ == "__main__":
    main()
