# ProteinMPNN Mini-Service (Mock) — Minimal UI + API

This is a minimal scaffold that matches the take-home API/UI shape, but uses a mock sequence designer.

## Run

```bash
pip install fastapi uvicorn[standard]
uvicorn mpnn_app.api:app --reload --host 0.0.0.0 --port 8000
```

Open:
- UI: http://localhost:8000/
- Health: http://localhost:8000/health
- API docs: http://localhost:8000/docs

## API

`POST /design` (multipart/form-data)

Fields:
- `structure` (file): `.pdb` or `.cif`
- `chains` (optional): `"A"` or `"A,B"` or `["A","B"]`
- `num_sequences` (optional, default 5)

Example:
```bash
bash requests/design.curl.sh
```

## Notes

- Diff highlighting works when the upload is a PDB and the original sequence can be parsed.
- CIF is accepted, but the mock does not attempt full mmCIF sequence extraction.
