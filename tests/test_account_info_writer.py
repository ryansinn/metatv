"""One writer for fetched account info (ledger D69), with the editors' semantics."""

from __future__ import annotations

from datetime import datetime

from metatv.core.database import ProviderDB
from metatv.core.repositories.provider import apply_account_info, parse_account_timestamp


def _row(db, **kw) -> None:
    with db.session_scope() as s:
        s.add(ProviderDB(id="p", name="P", type="xtream", url="http://p", username="u", password="p",
                         is_active=True, **kw))


def test_a_full_answer_is_written(db):
    _row(db)
    with db.session_scope() as s:
        apply_account_info(s.get(ProviderDB, "p"), {
            "status": "Active", "active_cons": "0", "max_connections": 1,
            "exp_date": "1790000000", "created_at": 1700000000})
    with db.session_scope() as s:
        row = s.get(ProviderDB, "p")
        assert (row.account_status, row.max_connections) == ("Active", 1)
        assert row.account_exp_date == datetime.fromtimestamp(1790000000)
        assert row.account_created_at == datetime.fromtimestamp(1700000000)


def test_no_expiry_clears_an_old_one(db):
    """Xtream sends a null expiry for an unlimited account. Keeping the old date
    (what the catalogue load did) leaves a renewed source looking expired — and
    an expired source is hidden."""
    _row(db, account_exp_date=datetime(2026, 1, 1))
    with db.session_scope() as s:
        apply_account_info(s.get(ProviderDB, "p"), {"status": "Active", "exp_date": None})
    with db.session_scope() as s:
        assert s.get(ProviderDB, "p").account_exp_date is None


def test_a_junk_timestamp_does_not_lose_the_rest(db):
    """The load used int() bare: junk raised and its catch-all dropped the whole write."""
    _row(db)
    with db.session_scope() as s:
        apply_account_info(s.get(ProviderDB, "p"), {"status": "Active", "max_connections": 3,
                                                    "exp_date": "never"})
    with db.session_scope() as s:
        row = s.get(ProviderDB, "p")
        assert (row.account_status, row.max_connections, row.account_exp_date) == ("Active", 3, None)


def test_timestamp_parsing():
    assert parse_account_timestamp(None) is None
    assert parse_account_timestamp("") is None
    assert parse_account_timestamp("junk") is None
    assert parse_account_timestamp(10**20) is None
    assert parse_account_timestamp("1700000000") == datetime.fromtimestamp(1700000000)
