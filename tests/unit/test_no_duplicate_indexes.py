"""Gorev 5: modelte yinelenen indeks tanimi olmasin (DB'siz, offline)."""
from collections import defaultdict

from shared.db.models import Base


def test_no_duplicate_indexes():
    seen = defaultdict(list)
    for table in Base.metadata.sorted_tables:
        for ix in table.indexes:
            key = (table.name, tuple(c.name for c in ix.columns), bool(ix.unique))
            seen[key].append(ix.name)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dups, f"yinelenen indeksler: {dups}"
