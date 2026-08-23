"""Aggregate SMBC debit notification emails and upsert the daily total to Notion."""

from __future__ import annotations

import argparse
import base64
import html
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.header import decode_header, make_header
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SUBJECT = "ご利用のお知らせ【三井住友カード】"
TIMEZONE = ZoneInfo("Europe/Amsterdam")
NOTION_VERSION = "2022-06-28"


@dataclass(frozen=True)
class Usage:
    message_id: str
    received_at: datetime
    merchant: str
    amount: int


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def decode_b64url(data: str) -> str:
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    for encoding in ("utf-8", "iso-2022-jp", "shift_jis"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _plain_parts(part: dict[str, Any]) -> list[str]:
    results: list[str] = []
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if data and mime in {"text/plain", "text/html"}:
        text = decode_b64url(data)
        if mime == "text/html":
            text = re.sub(r"<[^>]+>", " ", html.unescape(text))
        results.append(text)
    for child in part.get("parts", []):
        results.extend(_plain_parts(child))
    return results


def message_body(payload: dict[str, Any]) -> str:
    parts = _plain_parts(payload)
    if not parts and payload.get("body", {}).get("data"):
        parts = [decode_b64url(payload["body"]["data"])]
    return "\n".join(parts)


def header(payload: dict[str, Any], name: str) -> str:
    for item in payload.get("headers", []):
        if item.get("name", "").lower() == name.lower():
            return str(make_header(decode_header(item.get("value", ""))))
    return ""


def parse_usage(message: dict[str, Any]) -> Usage:
    body = message_body(message["payload"])
    merchant_match = re.search(r"◇\s*利用先[\s\u3000]*[:：]\s*(.+)", body)
    amount_match = re.search(r"◇\s*利用金額[\s\u3000]*[:：]\s*([0-9,]+)\s*円", body)
    if not merchant_match or not amount_match:
        raise ValueError("利用先または利用金額を本文から抽出できません")
    received_at = datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc).astimezone(TIMEZONE)
    return Usage(
        message_id=message["id"],
        received_at=received_at,
        merchant=merchant_match.group(1).strip(),
        amount=int(amount_match.group(1).replace(",", "")),
    )


def gmail_service():
    credentials = Credentials(
        token=None,
        refresh_token=required_env("GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=required_env("GMAIL_CLIENT_ID"),
        client_secret=required_env("GMAIL_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def list_candidate_ids(service: Any) -> Iterable[str]:
    page_token = None
    query = f'subject:"{SUBJECT}" newer_than:2d'
    while True:
        response = service.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=500
        ).execute()
        yield from (item["id"] for item in response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break


def collect_usages(service: Any, target_date: date) -> list[Usage]:
    usages: list[Usage] = []
    for message_id in list_candidate_ids(service):
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        if header(message["payload"], "Subject") != SUBJECT:
            continue
        received_date = datetime.fromtimestamp(
            int(message["internalDate"]) / 1000, timezone.utc
        ).astimezone(TIMEZONE).date()
        if received_date != target_date:
            continue
        usages.append(parse_usage(message))
    return usages


class NotionClient:
    def __init__(self) -> None:
        self.database_id = required_env("NOTION_DATABASE_ID")
        self.date_property = os.getenv("NOTION_DATE_PROPERTY", "日付")
        self.amount_property = os.getenv("NOTION_AMOUNT_PROPERTY", "Money I spent")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {required_env('NOTION_TOKEN')}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, url, timeout=30, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise requests.HTTPError(
                f"{exc}; Notion response: {response.text}", response=response
            ) from exc
        return response.json()

    def _date_filter(self, target_date: date) -> dict[str, Any]:
        value = f"{target_date.year}/{target_date.month}/{target_date.day}"
        return {"title": {"equals": value}}

    def _date_value(self, target_date: date) -> dict[str, Any]:
        value = f"{target_date.year}/{target_date.month}/{target_date.day}"
        return {"title": [{"text": {"content": value}}]}

    def find_page(self, target_date: date) -> str | None:
        url = f"https://api.notion.com/v1/databases/{self.database_id}/query"
        payload: dict[str, Any] = {
            "filter": {
                "property": self.date_property,
                **self._date_filter(target_date),
            },
            "page_size": 100,
        }
        while True:
            result = self._request("POST", url, json=payload)
            if result.get("results"):
                return result["results"][0]["id"]
            if not result.get("has_more"):
                return None
            payload["start_cursor"] = result["next_cursor"]

    def upsert_total(self, target_date: date, total: int) -> str:
        page_id = self.find_page(target_date)
        properties = {
            self.date_property: self._date_value(target_date),
            self.amount_property: {"number": total},
        }
        if page_id:
            self._request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", json={"properties": properties})
            return "updated"
        self._request("POST", "https://api.notion.com/v1/pages", json={
            "parent": {"database_id": self.database_id},
            "properties": properties,
        })
        return "created"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="集計日 (YYYY-MM-DD)。省略時はAmsterdamの当日")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target_date = date.fromisoformat(args.date) if args.date else datetime.now(TIMEZONE).date()
    usages = collect_usages(gmail_service(), target_date)
    total = sum(item.amount for item in usages)
    action = NotionClient().upsert_total(target_date, total)
    print(f"date={target_date} messages={len(usages)} total_jpy={total} notion={action}")
    for item in usages:
        print(f"  {item.received_at.isoformat()} {item.merchant} {item.amount} JPY")


if __name__ == "__main__":
    main()
