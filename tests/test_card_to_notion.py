import base64
from datetime import date, datetime

import pytest

from card_to_notion import NotionClient, SUBJECT, collect_usages, parse_usage


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


def test_notion_title_date_filter_and_value():
    client = object.__new__(NotionClient)
    target = date(2026, 8, 22)

    assert client._date_filter(target) == {"title": {"equals": "2026/8/22"}}
    assert client._date_value(target) == {
        "title": [{"text": {"content": "2026/8/22"}}]
    }


@pytest.mark.parametrize("day,start,end", [
    (date(2020, 1, 15), "2020-01-14T23:00:00+00:00", "2020-01-15T23:00:00+00:00"),
    (date(2026, 3, 29), "2026-03-28T23:00:00+00:00", "2026-03-29T22:00:00+00:00"),
    (date(2026, 10, 25), "2026-10-24T22:00:00+00:00", "2026-10-25T23:00:00+00:00"),
])
def test_historical_search_and_dst_boundaries(day, start, end):
    start_ms = int(datetime.fromisoformat(start).timestamp()) * 1000
    end_ms = int(datetime.fromisoformat(end).timestamp()) * 1000

    class SearchingMessages(Messages):
        def list(self, **kwargs):
            query = kwargs["q"]
            assert "newer_than" not in query
            after = int(query.split("after:")[1].split()[0]) * 1000
            before = int(query.split("before:")[1].split()[0]) * 1000
            assert after == start_ms - 1000
            assert before == end_ms
            return Execute({"messages": [
                {"id": m["id"]} for m in self.data.values()
                if after < int(m["internalDate"]) < before
            ]})

    service = Service([])
    service._users._messages = SearchingMessages([
        message("previous", str(start_ms - 1)),
        message("midnight", str(start_ms)),
        message("last", str(end_ms - 1)),
        message("next", str(end_ms)),
    ])
    usages = collect_usages(service, day)
    assert [u.message_id for u in usages] == ["midnight", "last"]
    assert sum(u.amount for u in usages) == 2688
