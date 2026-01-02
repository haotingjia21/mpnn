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
payload fields (e.g. `num_seq_per_target`) override these defaults for that job,
and the resolved values are recorded into `runs/jobs/<id>/inputs/manifest.json`.

For reproducibility, `metadata/versions.json` records `model_git_sha` (the
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
python scripts/client.py design examples/toy.pdb --chains A --nseq 5 --model v_48_020
python scripts/client.py design examples/PDB_monomers/pdbs/5L33.pdb
```

## Tests
```bash
pip install -e ".[mpnn]"
pytest
```

Tests stub the core execution so they don’t require a real ProteinMPNN run.


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
Matches HW format (metadata + original + designed sequences). `seed` is fixed to `0`.

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
    versions.json
```

## Notes

- The container includes `/app/config.json` by default.
  For custom settings, mount a file to `/app/config.json`.

