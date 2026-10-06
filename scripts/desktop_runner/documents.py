"""CV/cover-letter download + file-input attach (stdlib + playwright only).

Documents are fetched from the API (GET /api/v1/documents/{id}/file) into
temporary files with FIXED names (cv.pdf / cover_letter.pdf): the filename
coming from the API is never used. Temporary files are deleted only AFTER
the browser is closed, because Chromium reads the file at submit time.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.async_api import Page

logger = logging.getLogger("desktop-runner")

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
    query = urllib.parse.urlencode({"application_id": application_id, "limit": 50})
    with urllib.request.urlopen(
        _request(api_base, api_key, f"/api/v1/documents?{query}"), timeout=15
    ) as response:
        data = json.load(response)
        # API v2 returns paginated envelope {items: [...]}; v1 returned array.
        return data.get("items", data) if isinstance(data, dict) else data


def pick_document_ids(documents: list[dict]) -> dict[str, str]:
    """Mirror the desktop-context selection: latest cv + latest cover letter."""
    picked: dict[str, str] = {}
    # Pick latest CV (highest version)
    cv_rows = [r for r in documents if r.get("type") == "cv"]
    if cv_rows:
        latest_cv = max(cv_rows, key=lambda r: r.get("version", 0))
        picked["resume"] = latest_cv["id"]
    # Pick latest cover letter (highest version)
    cl_rows = [r for r in documents if r.get("type") == "cover_letter"]
    if cl_rows:
        latest_cl = max(cl_rows, key=lambda r: r.get("version", 0))
        picked["cover_letter"] = latest_cl["id"]
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
    except Exception as exc:
        logger.warning("Failed to list documents for %s: %s", application_id, exc)
        return prepared
    for slot, document_id in picked.items():
        dest = workdir / FIXED_FILENAMES[slot]
        try:
            download_document(api_base, api_key, document_id, dest)
            if dest.is_file() and dest.stat().st_size > 0:
                prepared[slot] = dest
                logger.info("Prepared %s -> %s (%d bytes)", slot, dest, dest.stat().st_size)
            else:
                logger.warning("Downloaded %s is empty, skipping", slot)
                dest.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Failed to download %s (%s): %s", slot, document_id, exc)
            continue
    return prepared


def _slot_for_file_input(field_key: str, accept: str = "") -> str:
    """Determine which document slot this file input expects.

    Heuristics:
    - If field key mentions cover/letter -> cover_letter
    - If accept includes image/video/audio (typical for resume/CV uploads
      that also accept headshots/videos) -> resume
    - If field key mentions resume/cv -> resume
    - Default: first unseen slot (resume first, then cover_letter)
    """
    fk = (field_key or "").lower()
    acc = (accept or "").lower()

    if "cover" in fk or "letter" in fk:
        return "cover_letter"
    if "resume" in fk or "cv" in fk:
        return "resume"
    # Ashby resume field has image/video/audio in accept
    if "image" in acc or "video" in acc or "audio" in acc:
        return "resume"
    # Default fallback: alternate
    return "resume"


async def attach_files(page: Page, prepared: dict[str, Path]) -> list[str]:
    """Set file inputs from prepared temp files. Returns attached slots."""
    attached: list[str] = []
    used_slots: set[str] = set()

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    for index in range(await page.locator("input[type='file']").count()):
        field = page.locator("input[type='file']").nth(index)
        try:
            if not await field.is_enabled():
                continue
            # Get label text for better field key (Ashby puts field name in label)
            label_text = None
            try:
                label_text = await field.evaluate(
                    "(el) => (el.labels ? Array.from(el.labels).map(l => l.innerText).join(' ') : '')"
                )
            except Exception:
                pass
            accept = await field.get_attribute("accept") or ""
            field_key = normalized(
                " ".join(
                    filter(
                        None,
                        [
                            await field.get_attribute("name"),
                            await field.get_attribute("id"),
                            await field.get_attribute("autocomplete"),
                            await field.get_attribute("placeholder"),
                            await field.get_attribute("aria-label"),
                            label_text,
                            accept,
                        ],
                    )
                )
            )
            slot = _slot_for_file_input(field_key, accept)
            # If slot already used, try the other one
            if slot in used_slots:
                other = "cover_letter" if slot == "resume" else "resume"
                if other in prepared and other not in used_slots:
                    slot = other
            path = prepared.get(slot)
            if path is not None and path.is_file():
                await field.set_input_files(str(path))
                attached.append(slot)
                used_slots.add(slot)
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
