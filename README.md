# ProteinMPNN mini-service

This repo is a minimal wrapper around dauparas/ProteinMPNN that provides:

- **Service (`mpnn.app.api:create_app`)**: FastAPI `POST /design` + `GET /health`
- **Core runner (`mpnn.run_design`)**: stateless, file-contract execution
- **UI**: a small Dash UI mounted at `/` that calls the same `/design` endpoint

## Set up

Create env:
```bash
conda env create -f environment.yml
conda activate mpnn
pip install -e ".[dev]"
```

## Configuration

Runtime settings are loaded from a JSON config file (`config.json`).

`model_defaults` defines the deployment-wide defaults for ProteinMPNN. Per-request
payload fields (e.g. `num_sequences`) override these defaults for that job,
and the resolved values are recorded into `runs/jobs/<id>/inputs/manifest.json`.

For reproducibility, `metadata/run_metadata.json` records `model_git_sha` (the
ProteinMPNN commit hash) by running `git rev-parse HEAD` in the ProteinMPNN
checkout inside the container.

## Run
Run (docker compose). This is the easiest way to ensure runtime metadata like
`CONTAINER_IMAGE` is set.

```bash
docker compose up --build
```

Run (plain Docker). Outputs are written under the configured `jobs_dir`.

```bash
docker build -t mpnn:dev .
docker run --rm -p 8000:8000 \
  -v "$PWD/runs:/data/runs" \
  -e CONTAINER_IMAGE=mpnn:dev \
  mpnn:dev
```

To override config, mount a file:
```bash
docker run --rm -p 8000:8000 \
  -v "$PWD/runs:/data/runs" \
  -v "$PWD/config.json:/app/config.json:ro" \
  -e CONTAINER_IMAGE=mpnn:dev \
  mpnn:dev
```

- API: `http://localhost:8000/health`, `http://localhost:8000/design`
- UI: `http://localhost:8000/`

## Sample requests

Run sample requests against a running service:

```bash
python scripts/client.py health
python scripts/client.py design examples/complexes/cifs/3HTN.cif --chains A --nseq 2 --model v_48_020
python scripts/client.py design examples/complexes/pdbs/4YOW.pdb # use default
```

```bash
curl -X GET http://localhost:8000/health
curl -X POST http://localhost:8000/design \
  -F "structure=@examples/monomers/pdbs/5L33.pdb" \
  -F 'payload={
    "chains": "A",
    "num_sequences": 5,
    "model_name": "v_48_020"
  }'
```

## REST API
### `POST /design` (multipart: JSON payload + pdb/cif)

- **File field**: `structure` (`.pdb`, `.cif`)
- **Form field**: `payload` (JSON string)

Payload:
```json
{
  "chains": "A",             // e.g. "A"/["A","B"]/empty(each chain results)
  "num_sequences": 5,        // default 5
  "model_name": "v_48_020"   // UI dropdown; passed to ProteinMPNN --model_name
}
```

### Response JSON
Matches HW format (metadata + original + designed sequences). The service does not return a `seed` field in the API response.

## Output artifacts (per request / job)

The service creates a job directory under `jobs_dir` from `config.json`:

```
runs/jobs/<id>/
  inputs/
    <original_uploaded_filename>
    manifest.json
  artifacts/
    <base_name>.pdb
    parsed_pdbs.jsonl
    chain_ids.jsonl
  logs/
    run.log
  model_outputs/
    seqs/
      <base_name>_res.fa
  formatted_outputs/
  responses/
    response.json
  metadata/
    checksums.sha256
    run_metadata.json
```

## Notes

- The container includes `/app/config.json` by default.
  For custom settings, mount a file to `/app/config.json`.

## Concurrency limit (reject-when-busy)

The service can optionally reject `/design` requests when it is already running too many jobs.

- Configure the default per-process limit in `config.json` via `max_concurrent_jobs` (<= 0 means unlimited).
- Override at runtime with the environment variable `MPNN_MAX_CONCURRENT_JOBS`.

When the limit is reached, the API returns **503 Service Unavailable** with `Retry-After: 1`.
