"""Gorev 5: tek alembic head (dallanmis migration zinciri yakalama)."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def test_single_alembic_head():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "db" / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"birden fazla head: {heads}"
