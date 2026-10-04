"""Oneri onay adimi (kullanici hukum verir; ajan fact uydurmaz).

Kullanim:
    python scripts/review_facts.py fact_proposals_github.jsonl [onayli.jsonl]

Her oneri icin sorulur:
- kabul (e/h)
- `role`: owner | ai_assisted. `ai_assisted` secilirse uretici projeyi
  "mimariyi tasarladim ve AI destekli gelistirme ile hayata gecirdim"
  gibi durust bir ifadeyle yazar; "tamamen elle yazdim" anlamindaki
  ifadeler grounding kapisinda reddedilir.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

VALID_ROLES = ("owner", "ai_assisted")
VALID_ROLE_FIT = ("consultant", "engineer")


def prompt_role(proposal: dict, input_fn: Callable[[str], str] = input) -> str:
    """Kullanicidan proje rolunu sorar (owner | ai_assisted)."""
    title = proposal.get("title") or "?"
    current = proposal.get("role") or "owner"
    while True:
        answer = (input_fn(f"[{title}] rol (owner/ai_assisted) [{current}]: ") or "").strip().lower()
        if not answer:
            return current if current in VALID_ROLES else "owner"
        if answer in VALID_ROLES:
            return answer
        print(f"gecersiz rol: {answer!r} (owner | ai_assisted)")  # noqa: T201 - CLI


def prompt_role_fit(proposal: dict, input_fn: Callable[[str], str] = input) -> list[str]:
    """Fact hangi ilan turune uyar (consultant | engineer | both)?"""
    title = proposal.get("title") or "?"
    current = proposal.get("role_fit") or ["consultant", "engineer"]
    default = "both" if set(current) == set(VALID_ROLE_FIT) else ",".join(current)
    while True:
        answer = (input_fn(f"[{title}] role_fit (consultant/engineer/both) [{default}]: ") or "").strip().lower()
        if not answer:
            return list(current)
        if answer == "both":
            return ["consultant", "engineer"]
        parts = [p.strip() for p in answer.split(",") if p.strip()]
        if parts and all(p in VALID_ROLE_FIT for p in parts):
            return parts
        print(f"gecersiz role_fit: {answer!r}")  # noqa: T201 - CLI


def review_proposals(
    proposals: list[dict],
    input_fn: Callable[[str], str] = input,
) -> list[dict]:
    """Onaylanan onerileri role/role_fit alaniyla dondurur (reddedilenler atilir)."""
    approved: list[dict] = []
    for proposal in proposals:
        title = proposal.get("title") or "?"
        print(f"--- {title} ({proposal.get('source')}/{proposal.get('repo') or proposal.get('source_doc')})")  # noqa: T201 - CLI
        print(f"    {proposal.get('text', '')[:200]}")  # noqa: T201 - CLI
        if proposal.get("conflict"):
            print("    TARIH CAKISMASI (CV kazanir, otomatik secilmez):")  # noqa: T201 - CLI
            for variant in proposal["conflict"]:
                print(f"      - {variant.get('period')} <- {variant.get('source')}")  # noqa: T201 - CLI
        answer = (input_fn("    kabul? (e/h) [e]: ") or "").strip().lower()
        if answer in {"h", "hayir", "n", "no"}:
            continue
        approved.append({
            **proposal,
            "role": prompt_role(proposal, input_fn),
            "role_fit": prompt_role_fit(proposal, input_fn),
        })
    return approved


def load_proposals(path: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: Optional[list[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("kullanim: python scripts/review_facts.py <oneriler.jsonl> [onayli.jsonl]")  # noqa: T201 - CLI
        return 2
    src, out = args[0], (args[1] if len(args) > 1 else "facts_approved.jsonl")
    approved = review_proposals(load_proposals(src))
    with Path(out).open("w", encoding="utf-8") as f:
        for proposal in approved:
            f.write(json.dumps(proposal, ensure_ascii=False) + "\n")
    print(f"{len(approved)} onayli oneri -> {out}")  # noqa: T201 - CLI
    return 0


if __name__ == "__main__":
    sys.exit(main())
