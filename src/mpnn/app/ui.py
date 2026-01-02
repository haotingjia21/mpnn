import base64
import json
from collections import defaultdict

import requests
from dash import Dash, Input, Output, State, dcc, html
from flask import request as flask_request

MODEL_OPTIONS = [
    {"label": "v_48_002", "value": "v_48_002"},
    {"label": "v_48_010", "value": "v_48_010"},
    {"label": "v_48_020 (default)", "value": "v_48_020"},
    {"label": "v_48_030", "value": "v_48_030"},
]

S_MONO = {"fontFamily": "ui-monospace, Menlo, Consolas, monospace", "whiteSpace": "pre-wrap"}
S_DIFF = {"background": "#ffe8a3", "borderRadius": "3px"}
S_BOX = {"border": "1px solid #ddd", "borderRadius": "10px", "padding": "10px", "marginTop": "10px"}


def highlight(seq: str, original: str):
    children = []
    for i, ch in enumerate(seq):
        if i >= len(original) or ch != original[i]:
            children.append(html.Span(ch, style=S_DIFF))
        else:
            children.append(ch)
    return html.Pre(children, style={**S_MONO, "margin": 0})


def render_results(data: dict):
    original = data.get("original_sequences") or {}
    designs = data.get("designed_sequences") or []

    by_chain = defaultdict(list)
    for d in designs:
        by_chain[str(d.get("chain", ""))].append(d)

    chain_order = list(original.keys())
    for c in by_chain.keys():
        if c not in chain_order:
            chain_order.append(c)

    blocks = []
    for chain in chain_order:
        orig_seq = original.get(chain, "") or ""
        chain_designs = sorted(by_chain.get(chain, []), key=lambda x: int(x.get("rank", 0) or 0))

        children = [html.Div(f"Chain {chain}", style={"fontWeight": "700"})]
        if orig_seq:
            children += [
                html.Div("Original", style={"marginTop": "6px", "fontWeight": "600"}),
                html.Pre(orig_seq, style={**S_MONO, "margin": 0}),
            ]

        for d in chain_designs:
            rank = d.get("rank", "")
            seq = d.get("sequence", "") or ""
            children += [
                html.Div(f"Designed (rank {rank})", style={"marginTop": "10px", "fontWeight": "600"}),
                highlight(seq, orig_seq),
            ]

        if not orig_seq and not chain_designs:
            children.append(html.Div("No sequences returned."))

        blocks.append(html.Div(children, style=S_BOX))

    return html.Div(blocks)


def create_dash_server():
    app = Dash(__name__)
    app.title = "mpnn"

    app.layout = html.Div(
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
                    html.Div(id="file_name", style={"minWidth": "240px"}),
                    dcc.Input(
                        id="chains_text",
                        type="text",
                        placeholder='chains (optional, e.g. "A B" or "A,B")',
                        value="",
                        style={"width": "320px"},
                    ),
                    dcc.Dropdown(
                        id="model_name",
                        options=MODEL_OPTIONS,
                        value="v_48_020",
                        clearable=False,
                        style={"width": "210px"},
                    ),
                    dcc.Input(id="nseq", type="number", value=5, min=1, max=200, style={"width": "90px"}),
                    html.Button("Design", id="go"),
                ],
                style={"display": "flex", "gap": "10px", "alignItems": "center", "flexWrap": "wrap"},
            ),
            html.Div(id="status", style={"marginTop": "10px"}),
            dcc.Loading(html.Div(id="out"), type="default"),
        ],
        style={"fontFamily": "system-ui, sans-serif", "margin": "16px", "maxWidth": "980px"},
    )

    @app.callback(Output("file_name", "children"), Input("upload", "filename"))
    def show_filename(filename):
        if not filename:
            return ""
        return f"file: {filename}"

    @app.callback(
        Output("status", "children"),
        Output("out", "children"),
        Input("go", "n_clicks"),
        State("upload", "contents"),
        State("upload", "filename"),
        State("chains_text", "value"),
        State("model_name", "value"),
        State("nseq", "value"),
        prevent_initial_call=True,
    )
    def on_design(_n_clicks, contents, filename, chains_text, model_name, nseq):
        if not contents or not filename:
            return "upload a structure file", ""

        b64 = contents.split(",", 1)[1]
        blob = base64.b64decode(b64)

        payload = {"num_sequences": int(nseq or 5), "model_name": model_name}
        if (chains_text or "").strip():
            payload["chains"] = chains_text  # server normalizes

        url = f"{flask_request.host_url.rstrip('/')}/design"

        try:
            r = requests.post(
                url,
                files={"structure": (filename, blob, "application/octet-stream")},
                data={"payload": json.dumps(payload)},
                timeout=600,
            )
        except Exception as e:
            return f"request failed: {e}", ""

        if r.ok:
            data = r.json()
            m = data.get("metadata") or {}

            # Keep status minimal: no seed notes, no legend text.
            status = f"ok ({m.get('runtime_ms','?')} ms, model={m.get('model_version','?')})"
            return status, render_results(data)

        # minimal error display
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        return f"failed (HTTP {r.status_code})", html.Pre(str(detail), style=S_MONO)

    return app, app.server
