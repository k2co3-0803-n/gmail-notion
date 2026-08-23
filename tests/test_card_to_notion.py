import base64
from datetime import date

from card_to_notion import SUBJECT, collect_usages, parse_usage


def encoded(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def message(message_id="m1", timestamp="1787351396000"):
    return {
        "id": message_id,
        "internalDate": timestamp,
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": SUBJECT}],
            "parts": [{
                "mimeType": "text/plain",
                "body": {"data": encoded("◇利用日  ：2026/08/22 00:29:56\n◇利用先　：INTER IKEA SYSTEMS BV HFB\n◇利用金額：1,344円")},
            }],
        },
    }


def test_parse_usage_uses_internal_date_and_extracts_fields():
    usage = parse_usage(message())
    assert usage.received_at.date() == date(2026, 8, 22)
    assert usage.merchant == "INTER IKEA SYSTEMS BV HFB"
    assert usage.amount == 1344


class Execute:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class Messages:
    def __init__(self, messages): self.data = {m["id"]: m for m in messages}
    def list(self, **kwargs): return Execute({"messages": [{"id": key} for key in self.data]})
    def get(self, **kwargs): return Execute(self.data[kwargs["id"]])


class Users:
    def __init__(self, messages): self._messages = Messages(messages)
    def messages(self): return self._messages


class Service:
    def __init__(self, messages): self._users = Users(messages)
    def users(self): return self._users


def test_collects_messages_not_threads_and_filters_by_internal_date():
    same_day = message("m1")
    next_day = message("m2", "1787437796000")
    wrong_subject = message("m3")
    wrong_subject["payload"]["headers"][0]["value"] = "別の件名"
    usages = collect_usages(Service([same_day, next_day, wrong_subject]), date(2026, 8, 22))
    assert [usage.message_id for usage in usages] == ["m1"]

