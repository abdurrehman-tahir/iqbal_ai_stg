#!/usr/bin/env python3
"""Prepare a CLI-friendly copy of the Postman collection.

Why:
- UI runs require manual file selection in form-data file fields.
- CLI/newman runs can use `src` path from iteration data (doc_path).

This script reads the primary collection and writes a CLI variant where each
`/api/rag/ingest` request has file `src` set to `{{doc_path}}`.
"""
from __future__ import annotations

import json
from pathlib import Path

SRC = Path("postman/IqbalAI-Staging-APIs.postman_collection.json")
DST = Path("postman/IqbalAI-Staging-APIs.cli.postman_collection.json")


def iter_requests(items):
    for item in items:
        if "item" in item:
            yield from iter_requests(item["item"])
        else:
            yield item


def main() -> None:
    data = json.loads(SRC.read_text())
    updated = 0

    for req_item in iter_requests(data.get("item", [])):
        req = req_item.get("request", {})
        url_raw = req.get("url", {}).get("raw", "")
        body = req.get("body", {})

        if not url_raw.endswith("/api/rag/ingest"):
            continue
        if body.get("mode") != "formdata":
            continue

        for part in body.get("formdata", []):
            if part.get("key") == "file" and part.get("type") == "file":
                part["src"] = "{{doc_path}}"
                updated += 1

        desc = (req.get("description") or "").strip()
        note = (
            "CLI variant: file src is bound to {{doc_path}} from iteration data. "
            "Ensure doc_path points to a readable local PDF path for the runner process."
        )
        req["description"] = f"{desc}\n\n{note}".strip()

    DST.write_text(json.dumps(data, indent=2))
    print(f"Wrote {DST} (updated ingest file parts: {updated})")


if __name__ == "__main__":
    main()
