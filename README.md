# ProteinMPNN Mini-Service

## Run

```bash
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

PDB_PATH='examples/PDB_complexes/pdbs/3HTN.pdb'
PDB_PATH='examples/PDB_monomers/pdbs/5L33.pdb'

python software/ProteinMPNN/protein_mpnn_run.py \
  --pdb_path $PDB_PATH \
  --pdb_path_chains "" \
  --out_folder runs/ \
  --num_seq_per_target 5

  --sampling_temp "0.1" \
  --seed 0 \
  --batch_size 1 \
  --model_name v_48_020

