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


@pytest.fixture
def notion_client(monkeypatch):
    monkeypatch.setenv("NOTION_DATABASE_ID", "database")
    monkeypatch.setenv("NOTION_TOKEN", "test-token")
    monkeypatch.delenv("NOTION_DATA_SOURCE_ID", raising=False)
    monkeypatch.delenv("NOTION_DATE_PROPERTY", raising=False)
    monkeypatch.delenv("NOTION_AMOUNT_PROPERTY", raising=False)
    return NotionClient()


@pytest.mark.parametrize("existing", [True, False])
def test_upsert_uses_explicit_data_source(notion_client, monkeypatch, existing):
    client = notion_client
    client.data_source_id = "selected"
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if url.endswith("/query"):
            return {"results": [{"id": "page"}] if existing else [], "has_more": False}
        return {}

    monkeypatch.setattr(client, "_request", request)
    assert client.session.headers["Notion-Version"] == "2025-09-03"
    assert client.upsert_total(date(2026, 9, 12), 1344) == ("updated" if existing else "created")
    assert calls[0][0:2] == ("POST", "https://api.notion.com/v1/data_sources/selected/query")
    assert calls[0][2]["filter"] == {"property": "日付", "title": {"equals": "2026/9/12"}}
    method, url, body = calls[1]
    assert body["properties"]["Money I spent"] == {"number": 1344}
    if existing:
        assert (method, url) == ("PATCH", "https://api.notion.com/v1/pages/page")
    else:
        assert body["parent"] == {"type": "data_source_id", "data_source_id": "selected"}


@pytest.mark.parametrize("matching", [[], ["a"], ["a", "b"]])
def test_discovery_requires_unique_matching_schema(notion_client, monkeypatch, matching):
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        assert method == "GET"  # Ambiguous discovery must never write or query pages.
        if url.endswith("/databases/database"):
            return {"data_sources": [{"id": "a", "name": "Expenses"}, {"id": "b", "name": "Other"}]}
        source_id = url.rsplit("/", 1)[1]
        return {"properties": {
            "日付": {"type": "title"},
            "Money I spent": {"type": "number" if source_id in matching else "formula"},
        }}

    monkeypatch.setattr(notion_client, "_request", request)
    if len(matching) == 1:
        assert notion_client.resolve_data_source_id() == "a"
        assert notion_client.resolve_data_source_id() == "a"
        assert len(calls) == 3
    else:
        with pytest.raises(RuntimeError, match="NOTION_DATA_SOURCE_ID"):
            notion_client.upsert_total(date(2026, 9, 12), 1344)


def test_empty_database_does_not_write(notion_client, monkeypatch):
    monkeypatch.setattr(notion_client, "_request", lambda *args, **kwargs: {"data_sources": []})
    with pytest.raises(RuntimeError, match="一覧: なし"):
        notion_client.resolve_data_source_id()


def test_query_pagination(notion_client, monkeypatch):
    notion_client.data_source_id = "selected"
    payloads = []

    def request(method, url, **kwargs):
        payloads.append(dict(kwargs["json"]))
        if len(payloads) == 1:
            return {"results": [], "has_more": True, "next_cursor": "cursor"}
        return {"results": [{"id": "page"}], "has_more": False}

    monkeypatch.setattr(notion_client, "_request", request)
    assert notion_client.find_page(date(2026, 9, 12)) == "page"
    assert payloads[1]["start_cursor"] == "cursor"
