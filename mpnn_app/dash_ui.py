from __future__ import annotations

import base64
import json
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional, Sequence, Set, Union

import requests
from dash import Dash, Input, Output, State, dcc, html
from flask import request as flask_request


S_BODY = {"fontFamily": "system-ui, sans-serif", "margin": "16px", "maxWidth": "980px"}
S_ROW = {"display": "flex", "gap": "10px", "alignItems": "center", "flexWrap": "wrap"}
S_ERR = {"color": "#b00020"}
S_MONO = {
    "fontFamily": "ui-monospace, Menlo, Consolas, monospace",
    "whiteSpace": "pre-wrap",
    "wordBreak": "break-word",
    "lineHeight": "1.35",
}
S_BOX = {"border": "1px solid #ddd", "borderRadius": "10px", "padding": "10px", "marginTop": "10px"}
S_DIFF = {"background": "#ffe8a3", "borderRadius": "3px"}


def _is_structure_filename(name: Optional[str]) -> bool:
    return bool(name) and name.lower().endswith((".pdb", ".cif", ".mmcif"))


def _highlight_by_positions(seq: str, diff_positions: Sequence[int]) -> html.Div:
    """Highlight 1-indexed positions from diff_positions."""
    diffs: Set[int] = set(int(p) for p in diff_positions if isinstance(p, int) or str(p).isdigit())
    children: List[Union[str, html.Span]] = []
    for i, ch in enumerate(seq, start=1):
        if i in diffs:
            children.append(html.Span(ch, style=S_DIFF))
        else:
            children.append(ch)
    return html.Div(children, style=S_MONO)


def _render_results(data: Dict) -> html.Div:
    original: Dict[str, str] = data.get("original_sequences", {}) or {}
    designs: List[Dict] = data.get("designed_sequences", []) or []

    by_chain: DefaultDict[str, List[Dict]] = defaultdict(list)
    for d in designs:
        by_chain[str(d.get("chain", ""))].append(d)

    chain_order = list(original.keys())
    for c in by_chain.keys():
        if c not in chain_order:
            chain_order.append(c)

    blocks: List[html.Div] = []

    blocks.append(
        html.Div(
            [html.Span("Legend: "), html.Span("different from original", style=S_DIFF)],
            style={"marginTop": "8px"},
        )
    )

    for chain in chain_order:
        orig_seq = original.get(chain, "")
        chain_designs = sorted(by_chain.get(chain, []), key=lambda x: int(x.get("rank", 0) or 0))

        rows: List[html.Div] = []
        rows.append(html.Div(f"Chain {chain}", style={"fontWeight": "700", "marginBottom": "6px"}))

        if orig_seq:
            rows.append(html.Div("Original", style={"fontWeight": "600"}))
            rows.append(html.Pre(orig_seq, style={**S_MONO, "margin": "0 0 10px 0"}))

        for d in chain_designs:
            rank = d.get("rank", "")
            seq = d.get("sequence", "") or ""
            diffs = d.get("diff_positions", []) or []
            rows.append(html.Div(f"Designed (rank {rank})", style={"fontWeight": "600"}))
            rows.append(_highlight_by_positions(seq, diffs))
            rows.append(html.Div(style={"height": "8px"}))

        if not orig_seq and not chain_designs:
            rows.append(html.Div("No sequences returned.", style=S_ERR))

        blocks.append(html.Div(rows, style=S_BOX))

    return html.Div(blocks)


def create_dash_server():
    dash_app = Dash(__name__, url_base_pathname="/")
    dash_app.title = "mpnn"

    dash_app.layout = html.Div(
        [
            html.H3("ProteinMPNN mini-service"),
            html.Div(
                [
                    dcc.Upload(
                        id="upload",
                        children=html.Button("Upload PDB/CIF"),
                        multiple=False,
                        accept=".pdb,.cif,.mmcif",
                    ),
                    html.Div(id="file_name", style={"minWidth": "260px"}),
                    dcc.Input(
                        id="chains_text",
                        type="text",
                        placeholder='chains (e.g. A or "A B")',
                        value="",
                        style={"width": "200px"},
                    ),
                    dcc.Input(id="nseq", type="number", value=5, min=1, max=200, style={"width": "90px"}),
                    html.Button("Design", id="go"),
                ],
                style=S_ROW,
            ),
            html.Div(id="runflag", style={"margin": "10px 0"}),
            html.Div(id="status", style={"margin": "10px 0"}),
            dcc.Loading(html.Div(id="out"), type="default"),
        ],
        style=S_BODY,
    )

    @dash_app.callback(Output("file_name", "children"), Input("upload", "filename"), prevent_initial_call=False)
    def _show_filename(filename: Optional[str]):
        if not filename:
            return ""
        if not _is_structure_filename(filename):
            return html.Span(f"file: {filename} (must be .pdb/.cif/.mmcif)", style=S_ERR)
        return f"file: {filename}"

    @dash_app.callback(
        Output("status", "children"),
        Output("out", "children"),
        Input("go", "n_clicks"),
        State("upload", "contents"),
        State("upload", "filename"),
        State("chains_text", "value"),
        State("nseq", "value"),
        prevent_initial_call=True,
        running=[
            (Output("go", "disabled"), True, False),
            (Output("runflag", "children"), "running…", ""),
        ],
    )
    def _on_design(_n_clicks, contents, filename, chains_text, nseq):
        if not contents or not filename:
            return html.Span("upload a structure file", style=S_ERR), ""
        if not _is_structure_filename(filename):
            return html.Span("only .pdb/.cif/.mmcif is supported", style=S_ERR), ""

        try:
            b64 = contents.split(",", 1)[1]
            blob = base64.b64decode(b64)
        except Exception:
            return html.Span("bad upload", style=S_ERR), ""

        payload: Dict = {"num_sequences": int(nseq) if nseq is not None else 5}
        if (chains_text or "").strip():
            payload["chains"] = chains_text

        base = flask_request.host_url.rstrip("/")
        url = f"{base}/design"

        try:
            r = requests.post(
                url,
                files={"structure": (filename, blob, "application/octet-stream")},
                data={"payload": json.dumps(payload)},
                timeout=600,
            )
        except Exception as e:
            return html.Span(f"request failed: {e}", style=S_ERR), ""

        if r.ok:
            data = r.json()
            m = data.get("metadata", {}) or {}
            status = f"ok ({m.get('runtime_ms','?')} ms, {m.get('model_version','?')})"
            return status, _render_results(data)

        try:
            err = r.json()
        except Exception:
            err = {"detail": r.text}

        detail = err.get("detail", err)
        stderr = ""
        stdout = ""
        if isinstance(detail, dict):
            stderr = detail.get("stderr", "")
            stdout = detail.get("stdout", "")

        log_block = html.Div(
            [
                html.Div(f"failed (HTTP {r.status_code})", style=S_ERR),
                html.Div("error:", style={"fontWeight": "600", "marginTop": "8px"}),
                html.Pre(
                    json.dumps(detail, indent=2) if not isinstance(detail, str) else detail,
                    style=S_MONO,
                ),
                html.Div("stderr:", style={"fontWeight": "600", "marginTop": "8px"}) if stderr else "",
                html.Pre(stderr, style=S_MONO) if stderr else "",
                html.Div("stdout:", style={"fontWeight": "600", "marginTop": "8px"}) if stdout else "",
                html.Pre(stdout, style=S_MONO) if stdout else "",
            ],
            style=S_BOX,
        )
        return html.Span(f"failed (HTTP {r.status_code})", style=S_ERR), log_block

    return dash_app, dash_app.server
