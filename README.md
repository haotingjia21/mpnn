# ProteinMPNN mini-service
Build a locally deployable web app that exposes a ProteinMPNN design API with a minimal
browser UI

## Set up

1. Create env:
```bash
conda env create -f environment.yml
conda activate mpnn
pip install -e ".[dev]"
```

2. Start Docker locally 
```
open -a Docker # for mac docker desktop
```

3. Run
```bash
docker compose up --build
```

or
```bash
docker build -t mpnn:dev .
docker run --rm -p 8000:8000 \
  -v "$PWD/runs:/data/runs" \
  -e CONTAINER_IMAGE=mpnn:dev \
  mpnn:dev
```

- API: `http://localhost:8000/health`, `http://localhost:8000/design`
- UI: `http://localhost:8000/`

## Sample requests


A. UI\
Open UI from http://localhost:8000/ \
Select a file from `examples/` \
Click 'design'


B. client.py
```bash
python scripts/client.py health
python scripts/client.py design examples/complexes/cifs/3HTN.cif --chains A --nseq 2 --model v_48_020
python scripts/client.py design examples/complexes/pdbs/4YOW.pdb # use default
```
C. CLI
```bash
curl -X GET http://localhost:8000/health
curl -X POST http://localhost:8000/design \
  -F "structure=@examples/monomers/pdbs/5L33.pdb" \
  -F 'payload={
    "chains": "A",
    "num_sequences": 5,
    "model_name": "v_48_020"
  }'

# use default chains or num_sequences if not given
curl -X POST http://localhost:8000/design \
  -F "structure=@examples/monomers/pdbs/5L33.pdb" \
  -F 'payload={
    "chains":"",
    "model_name": "v_48_020"
  }'  
```

## REST API
### `GET /health`
```{ "status": "ok" }```

### `POST /design` (multipart: JSON payload + pdb/cif)

- **File field**: `structure` (`.pdb`, `.cif`)
- **Form field**: `payload` (JSON string)

Payload:
```json
{
  "chains": "A",             // e.g. "A"/["A","B"]/empty(each chain results)
  "num_sequences": 5,        // default 5, accept int 1 - 10
  "model_name": "v_48_020"   // accpet 4 models
}
```

### Response JSON
```json
{ // N designed seqs for each chain requested
  "designed_sequences": [
    {
      "chain": "A", 
      "rank": 1,
      "sequence": "MIDEEEKKALDFVKALEEANPELMKEVIEPDTEMNVNGKKYKGEEIVDYVKELKKKGVKYKLLSYKKEGDKYVFTMERSYNGKTYIETITIKVENGKVKEVEIKRE"
    },
    // ...
  ],
  "metadata": {
    "model_version": "v_48_020",
    "runtime_ms": 4449
  },
  "original_sequences": {
    "A": "HMPEEEKAARLFIEALEKGDPELMRKVISPDTRMEDNGREFTGDEVVEYVKEIQKRGEQWHLRRYTKEGNSWRFEVQVDNNGQTEQWEVQIEVRNGRIKRVTITHV"
  }
}

```

## Unit tests
```
pytest
```
Input validation, concurrency and integration test.

## Output artifacts
- Specify job path in `config.json`
- Each request generates an `id/` dir
- For this project, `model_outputs/` and `responses/` are sufficient for minimal version.
- The rest are for future cloud database and offline mode forward compatibility.

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
  responses/
    response.json
  metadata/
    checksums.sha256
    run_metadata.json
  formatted_outputs/ # placeholder for post-processed res
```

## Notes

- The container includes `/app/config.json` by default.
  For custom settings, mount a file to `/app/config.json`.

## Concurrency limit (reject-when-busy)

Current version for sync mode only. When jobs limit reached, reject new requests.

## Configuration

Runtime settings are loaded from a JSON config file (`config.json`).

`model_defaults` defines the deployment-wide defaults for ProteinMPNN. Per-request
payload fields (e.g. `num_sequences`) override these defaults for that job,
and the resolved values are recorded into `runs/jobs/<id>/inputs/manifest.json`.

For reproducibility, `metadata/run_metadata.json` records `model_git_sha` (the
ProteinMPNN commit hash) by running `git rev-parse HEAD` in the ProteinMPNN
checkout inside the container.