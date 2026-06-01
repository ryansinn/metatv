"""Characterization test for P1-1: parse_provider_urls() helper.

T1-1 from REFACTOR_PLAN. Pins semantics of the new canonical helper so all
6 call sites can be safely replaced. Tests each variant the old inline code handled.
"""

import pytest
import json

from metatv.core.repositories.provider import parse_provider_urls


_VALID_URL_LIST = [
    {"url": "http://server1.com", "priority": 1, "is_active": True},
    {"url": "http://server2.com", "priority": 2, "is_active": False},
]


def test_list_input_returned_unchanged():
    result = parse_provider_urls(_VALID_URL_LIST)
    assert result == _VALID_URL_LIST


def test_json_string_decoded():
    raw = json.dumps(_VALID_URL_LIST)
    result = parse_provider_urls(raw)
    assert result == _VALID_URL_LIST


def test_none_returns_empty_list():
    assert parse_provider_urls(None) == []


def test_empty_string_returns_empty_list():
    assert parse_provider_urls("") == []


def test_malformed_json_returns_empty_list():
    assert parse_provider_urls("not valid json {{{") == []


def test_list_with_non_dict_items_filtered():
    raw = [{"url": "http://ok.com"}, "not-a-dict", 42, None]
    result = parse_provider_urls(raw)
    assert result == [{"url": "http://ok.com"}]


def test_empty_list_returns_empty_list():
    assert parse_provider_urls([]) == []


def test_json_string_with_non_dict_items_filtered():
    raw = json.dumps([{"url": "http://ok.com"}, "bad"])
    result = parse_provider_urls(raw)
    assert result == [{"url": "http://ok.com"}]
