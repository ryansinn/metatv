"""ProviderRepository.reports_one_connection — the D61 probe-skip rule, on a real DB."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("limit, status, expected", [
    (1, "Active", True),
    (2, "Active", False),
    (0, "Active", False),       # 0 = unlimited on Xtream
    (1, None, False),           # 1 only by column default: the account poll never ran
])
def test_only_a_polled_limit_of_one_counts(db, limit, status, expected):
    from metatv.core.database import ProviderDB
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope() as s:
        s.add(ProviderDB(id="p", name="P", type="xtream", url="http://p", username="u", password="p",
                         is_active=True, max_connections=limit, account_status=status))
    with db.session_scope() as s:
        assert RepositoryFactory(s).providers.reports_one_connection("p") is expected


def test_an_unknown_source_does_not_count(db):
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope() as s:
        assert RepositoryFactory(s).providers.reports_one_connection("missing") is False
