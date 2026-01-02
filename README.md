# ProteinMPNN mini-service (REST + UI) with K8s/Kubeflow-friendly core

This repo is a **minimal wrapper** around **dauparas/ProteinMPNN** that provides:

- **Core runner (`mpnn.run_design`)**: stateless, file-contract execution (good for Kubeflow/Kubernetes batch steps)
- **Service (`mpnn.api:app`)**: FastAPI `POST /design` + `GET /health`
- **UI**: a small Dash UI mounted at `/` that calls the same `/design` endpoint

## REST API

### `POST /design` (multipart: JSON + file)

- **File field**: `structure` (`.pdb`, `.cif`, `.mmcif`)
- **Form field**: `payload` (JSON string)

Payload (HW):
```json
{
  "chains": "A",             // optional; also supports ["A","B"]; omitted/empty => ALL chains
  "num_sequences": 5,        // default 5 (also accepts "Num_sequences")
  "model_name": "v_48_020"   // UI dropdown; passed to ProteinMPNN --model_name
}
```

**Default chains behavior**
- If `chains` is omitted/empty: **design ALL chains** found in the structure.
- A `chain_id.jsonl` is **always** written (even for “all chains”) so artifacts are consistent.

### Response JSON
Matches HW format (metadata + original + designed sequences). `seed` is fixed to `0`.

## Output artifacts (per request / job)

The service creates a job directory under `MPNN_JOBS_DIR` (default `runs/jobs`):

```
runs/jobs/<id>/
  input/
    <original_uploaded_filename>
    <stem>.pdb                # ensured for helper scripts (converted from CIF if needed)
  output/
    run.log
    parsed_pdbs.jsonl
    chain_id.jsonl            # always present
    response.json             # same JSON returned by /design
    seqs/
      <stem>_res.fa
```

## Run with Docker (recommended)

Build:
```bash
docker build -t mpnn .
```

Run (mount outputs):
```bash
docker run --rm -p 8000:8000 \
  -v "$PWD/runs:/data/runs" \
  -e MPNN_JOBS_DIR=/data/runs/jobs \
  mpnn
```

- API: `http://localhost:8000/health`, `http://localhost:8000/design`
- UI: `http://localhost:8000/`

## Kubeflow / batch usage (CLI)

The core is path-based (no server needed). This is the shape Kubeflow components like.

Example (inside the same container image):
```bash
python -m mpnn.cli \
  --structure /mnt/inputs/struct.pdb \
  --payload /mnt/inputs/payload.json \
  --job_dir /mnt/outputs/job
```

Artifacts will be written under `/mnt/outputs/job/output/`.

## Environment variables

- `PROTEIN_MPNN_DIR` (default: `/opt/ProteinMPNN`) — where ProteinMPNN is cloned in the container
- `MPNN_TIMEOUT_SEC` (default: `600`)
- `MPNN_JOBS_DIR` (default: `runs/jobs`) — service job base directory

## Tests

```bash
pip install -e ".[mpnn]"
pytest
```

Tests stub the core execution so they don’t require a real ProteinMPNN run.
