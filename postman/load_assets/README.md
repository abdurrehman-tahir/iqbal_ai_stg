Place test PDF files in this folder for runner-safe relative paths.

Recommended `doc_path` value in scenario data files:
- `postman/load_assets/10MB.pdf`

If your runner reports `PPERM: insecure file access outside working directory`, ensure:
1) The runner working directory includes this repo path, and
2) `doc_path` is relative (not absolute).
