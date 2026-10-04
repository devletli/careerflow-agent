"""Uctan uca duman testi (gercek siteye gitmez).

Kullanim:  python scripts/smoke.py [API_KEY]
API_KEY verilmezse .env dosyasindan okunur.
Cikis kodu: tum kontroller PASS ise 0, aksi halde 1.
"""

import sys

import httpx

BASE = "http://127.0.0.1:8000"


def _api_key(argv_key: str) -> str:
    if argv_key:
        return argv_key
    try:
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("API_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)  # noqa: T201 - CLI raporu
    return ok


def main() -> int:
    key = _api_key(sys.argv[1] if len(sys.argv) > 1 else "")
    headers = {"X-API-Key": key} if key else {}
    ok = True
    with httpx.Client(base_url=BASE, headers=headers, timeout=10) as c:
        ok = check("health", c.get("/health").status_code == 200) and ok
        st = c.get("/api/v1/status")
        ok = check("status", st.status_code == 200, st.text[:200]) and ok
        for path in ("jobs", "applications", "events"):
            r = c.get(f"/api/v1/{path}")
            ok = check(path, r.status_code == 200) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
