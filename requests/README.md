# health
bash requests/health.curl.sh

PDB_PATH='examples/PDB_homooligomers/pdbs/4GYT.pdb'
PDB_PATH='examples/PDB_complexes/pdbs/3HTN.pdb'
PDB_PATH='examples/PDB_monomers/pdbs/5L33.pdb'

# design with AB
bash requests/design.curl.sh $PDB_PATH requests/payload.ab.json

# design with A only
bash requests/design.curl.sh $PDB_PATH requests/payload.a.json

# design with no chains specified
bash requests/design.curl.sh $PDB_PATH requests/payload.none.json
