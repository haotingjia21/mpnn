# ProteinMPNN Mini-Service (Mock) — Ultra minimal

Single file app + tiny example + curl request.

## Run

```bash
pip install fastapi uvicorn[standard]
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open:
- UI: http://localhost:8000/
- Health: http://localhost:8000/health

## Request

```bash
bash requests/design.curl.sh
```

### Notes

- `POST /design` accepts `multipart/form-data` with:
  - `structure` (PDB/CIF file)
  - `chains` (optional): `A` or `A,B` or `["A","B"]`
  - `num_sequences` (optional, default 5)
  - optional `payload` (JSON string) if you prefer “JSON + file”
- Diff highlighting is done in the browser (works when original sequences can be parsed from PDB).
