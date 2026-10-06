"""CV/cover-letter download + file-input attach (stdlib + playwright only).

Documents are fetched from the API (GET /api/v1/documents/{id}/file) into
temporary files with FIXED names (cv.pdf / cover_letter.pdf): the filename
coming from the API is never used. Temporary files are deleted only AFTER
the browser is closed, because Chromium reads the file at submit time.
"""
from __future__ import annotations

import json
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.async_api import Page

FIXED_FILENAMES = {
    "resume": "cv.pdf",
    "cover_letter": "cover_letter.pdf",
}


def _request(api_base: str, api_key: str, path: str):
    request = urllib.request.Request(
        f"{api_base}{path}", headers={"X-API-Key": api_key}
    )
    return request


def list_application_documents(
    api_base: str, api_key: str, application_id: str
) -> list[dict]:
    """Resolve document rows for one application (id, type, version)."""
    query = urllib.parse.urlencode({"application_id": application_id, "limit": 100})
    with urllib.request.urlopen(
        _request(api_base, api_key, f"/api/v1/documents?{query}"), timeout=15
    ) as response:
        return json.load(response)


def pick_document_ids(documents: list[dict]) -> dict[str, str]:
    """Mirror the desktop-context selection: cv v1 + latest cover letter."""
    picked: dict[str, str] = {}
    for row in documents:
        doc_type = row.get("type")
        if doc_type == "cv" and "resume" not in picked and row.get("version") == 1:
            picked["resume"] = row["id"]
        elif doc_type == "cover_letter" and "cover_letter" not in picked:
            picked["cover_letter"] = row["id"]
    return picked


def download_document(
    api_base: str, api_key: str, document_id: str, dest: Path
) -> Path:
    """Download one document to an exact path (server filename ignored)."""
    with urllib.request.urlopen(
        _request(api_base, api_key, f"/api/v1/documents/{document_id}/file?download=1"),
        timeout=30,
    ) as response:
        dest.write_bytes(response.read())
    return dest


def prepare_upload_files(
    api_base: str, api_key: str, application_id: str
) -> dict[str, Path]:
    """Download resume/cover letter to fixed-name temp files. Caller cleans up."""
    workdir = Path(tempfile.mkdtemp(prefix="careerflow-docs-"))
    prepared: dict[str, Path] = {}
    try:
        picked = pick_document_ids(
            list_application_documents(api_base, api_key, application_id)
        )
    except Exception:
        return prepared
    for slot, document_id in picked.items():
        dest = workdir / FIXED_FILENAMES[slot]
        try:
            download_document(api_base, api_key, document_id, dest)
            prepared[slot] = dest
        except Exception:
            continue
    return prepared


def _slot_for_file_input(field_key: str) -> str:
    if "cover" in field_key or "letter" in field_key:
        return "cover_letter"
    return "resume"


async def attach_files(page: Page, prepared: dict[str, Path]) -> list[str]:
    """Set file inputs from prepared temp files. Returns attached slots."""
    attached: list[str] = []

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    for index in range(await page.locator("input[type='file']").count()):
        field = page.locator("input[type='file']").nth(index)
        try:
            # Gizli input'lar da baglanir (set_input_files gorunurluk
            # istemez; gercek Lever/Greenhouse girdileri gizlidir).
            if not await field.is_enabled():
                continue
            field_key = normalized(
                " ".join(
                    filter(
                        None,
                        [
                            await field.get_attribute("name"),
                            await field.get_attribute("id"),
                            await field.get_attribute("accept"),
                        ],
                    )
                )
            )
            slot = _slot_for_file_input(field_key)
            path = prepared.get(slot)
            if path is not None and path.is_file():
                await field.set_input_files(str(path))
                attached.append(slot)
        except Exception:
            continue
    return attached


def cleanup_upload_files(prepared: dict[str, Path]) -> None:
    """Delete temp files AND their parent temp dir. Call after browser close."""
    parents = set()
    for path in prepared.values():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        parents.add(path.parent)
    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            continue
