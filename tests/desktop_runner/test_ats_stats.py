"""Faz 1: ats_stats host sayimi + ATS sonek eslesmesi."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ats_stats.py"


def _load():
    sys.modules.pop("careerflow_ats_stats", None)
    spec = importlib.util.spec_from_file_location("careerflow_ats_stats", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_ats_stats"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://job-boards.greenhouse.io/acme", "greenhouse"),
    ("https://jobs.lever.co/acme/abc", "lever"),
    ("https://acme.workable.com/j/123", "workable"),
    ("https://jobs.ashbyhq.com/acme/1", "ashby"),
    ("https://acme.smartrecruiters.com/j/1", "smartrecruiters"),
    ("https://BOARDS.GREENHOUSE.IO/acme", "greenhouse"),
    ("https://evilgreenhouse.io/acme", None),
    ("https://greenhouse.io.evil.com/acme", None),
    ("https://acme.example.com/apply", None),
    ("not a url", None),
    ("", None),
])
def test_ats_from_url_table(url, expected):
    assert _load().ats_from_url(url) == expected


def test_host_of_strips_port_and_case():
    mod = _load()
    assert mod.host_of("https://Example.COM:8443/a") == "example.com"
    assert mod.host_of("not a url") == ""
    assert mod.host_of("") == ""


def test_summarize_counts_and_orders():
    mod = _load()
    urls = [
        "https://boards.greenhouse.io/a/1",
        "https://boards.greenhouse.io/a/2",
        "https://jobs.lever.co/a/1",
        "https://acme.example.com/apply",
        "not a url",
        "",
    ]
    rows = mod.summarize(urls)
    assert rows[0] == ("boards.greenhouse.io", 2, "greenhouse")
    assert ("jobs.lever.co", 1, "lever") in rows
    assert ("acme.example.com", 1, "unknown") in rows
    assert all("not a url" not in row[0] for row in rows)


def test_load_urls_from_file_skips_blanks_and_comments(tmp_path):
    mod = _load()
    path = tmp_path / "urls.txt"
    path.write_text(
        "# yorum\nhttps://boards.greenhouse.io/a/1\n\n  \nhttps://x.example/y\n",
        encoding="utf-8",
    )
    assert mod.load_urls_from_file(str(path)) == [
        "https://boards.greenhouse.io/a/1", "https://x.example/y",
    ]


def test_print_table_reports_unknown_share(capsys):
    mod = _load()
    mod.print_table(mod.summarize([
        "https://boards.greenhouse.io/a/1", "https://x.example/apply",
    ]), top=10)
    out = capsys.readouterr().out
    assert "boards.greenhouse.io" in out
    assert "bilinmeyen ATS: 1" in out
