"""Batch listing: durumlara göre id toplama (API sayfalı zarf, tek tek id yok)."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load():
    for module_name in ("dr_batch",):
        sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location("dr_batch", PACKAGE_DIR / "desktop_runner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["dr_batch"] = module
    spec.loader.exec_module(module)
    return module


class _Resp:
    def __init__(self, payload):
        self._buf = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self._buf.read()


def test_batch_lists_per_status_with_cursor_and_limit():
    dr = _load()
    pages = {
        ("BLOCKED", None): {"items": [{"id": "a1"}, {"id": "a2"}], "next_cursor": "c1"},
        ("BLOCKED", "c1"): {"items": [{"id": "a3"}], "next_cursor": None},
        ("FAILED", None): {"items": [{"id": "b1"}], "next_cursor": None},
    }

    def _fake_urlopen(request, timeout=None):
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(request.full_url).query)
        key = (q["status"][0], q.get("cursor", [None])[0])
        return _Resp(pages[key])

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        assert dr.list_application_ids(["BLOCKED", "FAILED"], 10) == ["a1", "a2", "a3", "b1"]
    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        assert dr.list_application_ids(["BLOCKED"], 2) == ["a1", "a2"]
