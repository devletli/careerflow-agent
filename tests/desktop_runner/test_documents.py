"""Document staging: fixed names, server filename ignored, late cleanup."""

import http.server
import importlib.util
import sys
import threading
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "desktop_runner"


def _load(name):
    for module_name in ("desktop_runner", f"desktop_runner.{name}"):
        sys.modules.pop(module_name, None)
    sys.path.insert(0, str(PACKAGE_DIR.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            f"desktop_runner.{name}", PACKAGE_DIR / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"desktop_runner.{name}"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(PACKAGE_DIR.parent))
        except ValueError:
            pass


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = b"%PDF-1.4 fixture"

    def do_GET(self):
        if self.path.startswith("/api/v1/documents?"):
            body = (
                b'[{"id": "doc-cv-1", "type": "cv", "version": 1},'
                b' {"id": "doc-cl-1", "type": "cover_letter", "version": 3}]'
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/v1/documents/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="Candidate_Company_Role_CV_en.pdf"',
            )
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def api_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_pick_mirrors_desktop_context_selection():
    documents = _load("documents")
    picked = documents.pick_document_ids(
        [
            {"id": "cv-v2", "type": "cv", "version": 2},
            {"id": "cv-v1", "type": "cv", "version": 1},
            {"id": "cl", "type": "cover_letter", "version": 3},
        ]
    )
    assert picked == {"resume": "cv-v1", "cover_letter": "cl"}


def test_download_uses_fixed_names_not_server_filename(api_server, tmp_path):
    documents = _load("documents")
    prepared = documents.prepare_upload_files(api_server, "key", "app-1")
    try:
        assert set(prepared) == {"resume", "cover_letter"}
        assert prepared["resume"].name == "cv.pdf"
        assert prepared["cover_letter"].name == "cover_letter.pdf"
        assert prepared["resume"].read_bytes() == b"%PDF-1.4 fixture"
    finally:
        documents.cleanup_upload_files(prepared)
    assert not prepared["resume"].exists()
    assert not prepared["resume"].parent.exists()


@pytest.mark.asyncio
async def test_attach_routes_cover_vs_resume(api_server):
    from playwright.async_api import async_playwright

    documents = _load("documents")
    prepared = documents.prepare_upload_files(api_server, "key", "app-1")
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await (await browser.new_context()).new_page()
                await page.set_content(
                    "<html><body>"
                    "<input type='file' id='resume' name='resume'>"
                    "<input type='file' id='cover' name='cover_letter_upload'>"
                    "</body></html>"
                )
                attached = await documents.attach_files(page, prepared)
                assert sorted(attached) == ["cover_letter", "resume"]
            finally:
                await browser.close()
    finally:
        documents.cleanup_upload_files(prepared)


def test_cleanup_missing_files_tolerated(tmp_path):
    documents = _load("documents")
    ghost = tmp_path / "cv.pdf"
    documents.cleanup_upload_files({"resume": ghost})
