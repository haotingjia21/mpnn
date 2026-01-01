from __future__ import annotations

import base64
import json
from typing import List, Optional, Union

import requests
from dash import Dash, Input, Output, State, dcc, html
from flask import request as flask_request


S_BODY = {"fontFamily": "system-ui, sans-serif", "margin": "16px", "maxWidth": "920px"}
S_ROW = {"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}
S_ERR = {"color": "#b00020"}
S_MONO = {
    "fontFamily": "ui-monospace, Menlo, Consolas, monospace",
    "whiteSpace": "pre-wrap",
    "wordBreak": "break-word",
}
S_DIFF = {"background": "#ffe8a3"}


def _is_pdb_filename(name: Optional[str]) -> bool:
    return bool(name) and name.lower().endswith(".pdb")


def _seq_with_diff(orig: str, seq: str) -> html.Div:
    if not orig:
        return html.Div(seq, style=S_MONO)
    L = min(len(orig), len(seq))
    children: List[Union[str, html.Span]] = []
    for i in range(L):
        ch = seq[i]
        children.append(ch if orig[i] == ch else html.Span(ch, style=S_DIFF))
    if len(seq) > L:
        children.append(html.Span(seq[L:], style=S_DIFF))
    return html.Div(children, style=S_MONO)


def _render_table(original: dict, designs: list) -> html.Table:
    header = html.Thead(html.Tr([html.Th("chain"), html.Th("rank"), html.Th("sequence")]))
    rows = []
    for d in designs:
        chain = d.get("chain", "")
        orig = (original or {}).get(chain, "")
        rows.append(html.Tr([html.Td(chain), html.Td(str(d.get("rank", ""))), html.Td(_seq_with_diff(orig, d.get("sequence", "")))]))
    return html.Table([header, html.Tbody(rows)], style={"borderCollapse": "collapse", "width": "100%"})


def create_dash_server():
    dash_app = Dash(__name__, url_base_pathname="/")
    dash_app.title = "mpnn"

    dash_app.layout = html.Div(
        [
            html.H3("mpnn"),
            html.Div(
                [
                    dcc.Upload(
                        id="upload",
                        children=html.Button("upload .pdb"),
                        multiple=False,
                        accept=".pdb",
                    ),
                    html.Div(id="file_name", style={"minWidth": "260px"}),
                    dcc.Dropdown(
                        id="chains",
                        options=[
                            {"label": "none", "value": ""},
                            {"label": "A", "value": "A"},
                            {"label": "B", "value": "B"},
                            {"label": "AB", "value": "AB"},
                        ],
                        value="",
                        clearable=False,
                        style={"width": "120px"},
                    ),
                    dcc.Input(id="nseq", type="number", value=5, min=1, max=200, style={"width": "80px"}),
                    html.Button("design", id="go"),
                ],
                style=S_ROW,
            ),
            html.Div(id="runflag", style={"margin": "10px 0"}),
            html.Div(id="status", style={"margin": "10px 0"}),
            dcc.Loading(html.Div(id="out"), type="default"),
        ],
        style=S_BODY,
    )

    @dash_app.callback(
        Output("file_name", "children"),
        Input("upload", "filename"),
        prevent_initial_call=False,
    )
    def _show_filename(filename: Optional[str]):
        if not filename:
            return ""
        if not _is_pdb_filename(filename):
            return html.Span(f"file: {filename} (must be .pdb)", style=S_ERR)
        return f"file: {filename}"

    @dash_app.callback(
        Output("status", "children"),
        Output("out", "children"),
        Input("go", "n_clicks"),
        State("upload", "contents"),
        State("upload", "filename"),
        State("chains", "value"),
        State("nseq", "value"),
        prevent_initial_call=True,
        running=[
            (Output("go", "disabled"), True, False),
            (Output("runflag", "children"), "running…", ""),
        ],
    )
    def _on_design(_n_clicks, contents, filename, chains_value, nseq):
        if not contents or not filename:
            return html.Span("upload a .pdb", style=S_ERR), ""
        if not _is_pdb_filename(filename):
            return html.Span("only .pdb is supported", style=S_ERR), ""

        try:
            b64 = contents.split(",", 1)[1]
            blob = base64.b64decode(b64)
        except Exception:
            return html.Span("bad upload", style=S_ERR), ""

        # dropdown -> payload JSON
        payload: dict = {"num_sequences": int(nseq) if nseq is not None else 5}
        if chains_value == "A":
            payload["chains"] = "A"
        elif chains_value == "B":
            payload["chains"] = "B"
        elif chains_value == "AB":
            payload["chains"] = ["A", "B"]

        base = flask_request.host_url.rstrip("/")  # e.g. http://127.0.0.1:8000
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

        # success
        if r.ok:
            data = r.json()
            status = f"ok ({data['metadata']['runtime_ms']} ms, {data['metadata']['model_version']})"
            original = data.get("original_sequences", {})
            designs = data.get("designed_sequences", [])
            table = _render_table(original, designs)
            return status, html.Div(table, style={"border": "1px solid #ddd"})

        # failure: print logs from API response
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
        msg = f"failed (HTTP {r.status_code})"

        log_block = html.Div(
            [
                html.Div("error:", style={"fontWeight": "600"}),
                html.Pre(json.dumps(detail, indent=2) if not isinstance(detail, str) else detail, style=S_MONO),
                html.Div("stderr:", style={"fontWeight": "600", "marginTop": "8px"}) if stderr else "",
                html.Pre(stderr, style=S_MONO) if stderr else "",
                html.Div("stdout:", style={"fontWeight": "600", "marginTop": "8px"}) if stdout else "",
                html.Pre(stdout, style=S_MONO) if stdout else "",
            ]
        )
        return html.Span(msg, style=S_ERR), log_block

    return dash_app, dash_app.server
