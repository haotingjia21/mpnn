from __future__ import annotations

import json
from pathlib import Path


def _minimal_pdb_bytes() -> bytes:
    # Minimal single-chain PDB that Bio.PDB can parse (chain A).
    return (
        "ATOM      1  N   ALA A   1      11.104  13.207  10.000  1.00 20.00           N\n"
        "ATOM      2  CA  ALA A   1      12.560  13.207  10.000  1.00 20.00           C\n"
        "ATOM      3  C   ALA A   1      13.000  14.600  10.000  1.00 20.00           C\n"
        "ATOM      4  O   ALA A   1      12.500  15.600  10.000  1.00 20.00           O\n"
        "TER\nEND\n"
    ).encode("utf-8")


def test_design_integration_mock_model_writes_artifacts(client, tmp_path: Path, monkeypatch):
    # Patch the subprocess execution layer so we don't need real ProteinMPNN.
    import mpnn.runner.io as rio
    import mpnn.runner.metadata as rmeta
    import mpnn.runner.design as rdesign
    monkeypatch.setattr(rmeta, "get_repo_git_sha", lambda _p: "deadbeef")
    monkeypatch.setattr(rdesign, "get_repo_git_sha", lambda _p: "deadbeef")

    def fake_run_cmd(cmd, *, timeout_sec: int):
        cmd_str = " ".join(str(x) for x in cmd)

        # helper_scripts/parse_multiple_chains.py
        if "parse_multiple_chains.py" in cmd_str:
            out_path = Path(cmd[cmd.index("--output_path") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps({"seq_chain_A": "AAAA"}) + "\n", encoding="utf-8")
            return 0, "", "", 5

        # helper_scripts/assign_fixed_chains.py
        if "assign_fixed_chains.py" in cmd_str:
            out_path = Path(cmd[cmd.index("--output_path") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps({"fixed_chains": []}) + "\n", encoding="utf-8")
            return 0, "", "", 5

        # protein_mpnn_run.py
        if "protein_mpnn_run.py" in cmd_str:
            out_folder = Path(cmd[cmd.index("--out_folder") + 1])
            n = int(cmd[cmd.index("--num_seq_per_target") + 1])
            seqs_dir = out_folder / "seqs"
            seqs_dir.mkdir(parents=True, exist_ok=True)

            fasta = [">original\nAAAA\n"]
            for i in range(1, n + 1):
                fasta.append(f">design_{i}\nCCCC\n")

            (seqs_dir / "mock.fa").write_text("".join(fasta), encoding="utf-8")
            return 0, "", "", 50

        raise AssertionError(f"Unexpected command: {cmd_str}")

    monkeypatch.setattr(rio, "run_cmd", fake_run_cmd)

    r = client.post(
        "/design",
        files={"structure": ("mini.pdb", _minimal_pdb_bytes(), "chemical/x-pdb")},
        data={"payload": json.dumps({"chains": "A", "num_sequences": 2})},
    )
    assert r.status_code == 200
    data = r.json()
    assert "metadata" in data
    assert "designed_sequences" in data
    assert "original_sequences" in data

    # Confirm the job workspace was created and key artifacts exist.
    runs = tmp_path / "runs"
    jobs = [p for p in runs.iterdir() if p.is_dir()]
    assert len(jobs) == 1
    job = jobs[0]

    assert (job / "inputs" / "mini.pdb").exists()
    assert (job / "inputs" / "manifest.json").exists()

    assert (job / "artifacts" / "parsed_pdbs.jsonl").exists()
    assert (job / "artifacts" / "chain_ids.jsonl").exists()

    seqs_dir = job / "model_outputs" / "seqs"
    assert any(seqs_dir.glob("*_res.fa"))

    assert (job / "responses" / "response.json").exists()
    assert (job / "metadata" / "checksums.sha256").exists()
    assert (job / "metadata" / "run_metadata.json").exists()
