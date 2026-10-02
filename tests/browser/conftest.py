"""Local HTTP server serving tests/fixtures/forms over 127.0.0.1.

No internet access, no external sites: Playwright tests use file://-free
http://127.0.0.1 URLs served from this repository.
"""
import functools
import http.server
import threading
from pathlib import Path

import pytest

FORMS_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "forms"


@pytest.fixture(scope="session")
def form_server():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(FORMS_DIR)
    )
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture()
def engine():
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[2] / "services" / "browser-agent" / "app" / "engine.py"
    spec = importlib.util.spec_from_file_location("careerflow_browser_engine_fixture", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_browser_engine_fixture"] = module
    spec.loader.exec_module(module)
    return module.BrowserAutomationEngine()
