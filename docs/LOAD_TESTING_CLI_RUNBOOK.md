# IqbalAI Load Testing CLI Runbook (Data File + Local PDF)

This runbook explains how to run the load scenarios with **one JSON data file** while still sending a local PDF to ingest endpoints.

## Why this exists
The UI runner allows one iteration data file, but file pickers are handled separately. In CLI mode, we can bind ingest file upload to a path field in the data file.

Backend ingest requires multipart with a real file named `file`; if file is missing or filename is empty, backend returns errors like `No file provided` / `No file selected`.

---

## Files
- Base collection (UI-safe):
  - `postman/IqbalAI-Staging-APIs.postman_collection.json`
- CLI collection (path-bound file upload):
  - `postman/IqbalAI-Staging-APIs.cli.postman_collection.json`
- Generator script:
  - `scripts/prepare_cli_collection.py`

The CLI collection sets each `/api/rag/ingest` form-data file part to:
- `file.src = "{{doc_path}}"`

---

## Data file requirement
Your iteration data JSON must include `doc_path` for scenarios that ingest PDFs:

```json
[
  {
    "case_id": "T2-001",
    "useremail": "teacher01@staging.local",
    "password": "Passw0rd!1",
    "doc_path": "postman/load_assets/10MB.pdf",
    "messages": ["Summarize", "Finalize lesson"]
  }
]
```

### Important
- Use a local path visible to the runner process.
- Prefer a path relative to runner working directory (example: `postman/load_assets/10MB.pdf`).
- The file must exist and be readable.
- Keep `.pdf` extension (backend validates PDF extension).

> **Important (Desktop Runner security):** If you see `PPERM: insecure file access outside working directory`, your file path is outside the runner's allowed working directory. Use a relative path like `postman/load_assets/10MB.pdf` and place the PDF under the configured working directory, or change the runner working directory in settings.

---

## Execution flow (tool-agnostic)

```text
[data file JSON]
  + doc_path
        ↓
[CLI test runner]
        ↓
[collection request /api/rag/ingest]
  multipart file.src -> {{doc_path}}
        ↓
[backend request.files['file']]
        ↓
[ingest success/poll/chat...]
```

---

## Recommended command pattern
1. Regenerate CLI collection variant:
   - `python scripts/prepare_cli_collection.py`
2. Run scenario folder with matching data file using your CLI runner.
3. Export run report JSON for downstream processing.

---

## Troubleshooting

### Error: `No file selected`
- `doc_path` missing in data case
- path not absolute or file not found from runner context
- runner cannot access path due to permissions

### Error: `Only PDF files are supported`
- path points to non-PDF
- filename lacks `.pdf` extension

### Ingest starts but poll fails
- check async/sync mode behavior in environment
- ensure `task_id` captured for async mode

---

## Recommendation
Use:
- UI-safe collection for manual runs (manual file picker)
- CLI collection for automated runs (file path via `doc_path`)

This keeps both workflows stable without forcing one mode’s constraints onto the other.
