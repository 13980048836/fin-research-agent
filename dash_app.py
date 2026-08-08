"""Plotly Dash frontend for the LangGraph finance research API."""
from __future__ import annotations

import os

import plotly.graph_objects as go
import requests
from dash import Dash, Input, Output, State, dcc, html


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")

app = Dash(__name__, title="Finance Research")
server = app.server

app.layout = html.Main(
    [
        html.Section(
            [
                html.Div(
                    [
                        html.H1("Finance Research Console"),
                        dcc.Textarea(
                            id="query",
                            value="请分析这份财报中的主要经营风险和利润变化原因",
                            style={"width": "100%", "height": "112px", "resize": "vertical"},
                        ),
                        html.Div(
                            [
                                dcc.Dropdown(
                                    id="mode",
                                    options=[
                                        {"label": "Auto", "value": "auto"},
                                        {"label": "Hybrid", "value": "hybrid"},
                                        {"label": "RAG", "value": "rag"},
                                        {"label": "SQL", "value": "sql"},
                                    ],
                                    value="auto",
                                    clearable=False,
                                    style={"width": "180px"},
                                ),
                                html.Button("Analyze", id="submit", n_clicks=0),
                            ],
                            className="toolbar",
                        ),
                    ],
                    className="panel",
                ),
                html.Div(
                    [
                        html.H2("Answer"),
                        dcc.Markdown(id="answer"),
                    ],
                    className="panel",
                ),
            ],
            className="workspace",
        ),
        html.Section(
            [
                html.Div([html.H2("Latency"), dcc.Graph(id="latency")], className="panel"),
                html.Div([html.H2("Citations"), html.Pre(id="citations")], className="panel"),
            ],
            className="workspace lower",
        ),
    ],
    style={
        "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
        "background": "#f7f8fa",
        "minHeight": "100vh",
        "padding": "24px",
        "color": "#20242c",
    },
)

app.index_string = """
<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
      .workspace { display: grid; grid-template-columns: 420px 1fr; gap: 16px; max-width: 1280px; margin: 0 auto 16px; }
      .workspace.lower { grid-template-columns: 1fr 1fr; }
      .panel { background: #fff; border: 1px solid #dde2ea; border-radius: 8px; padding: 18px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
      .toolbar { display: flex; gap: 10px; align-items: center; margin-top: 12px; }
      h1 { font-size: 24px; margin: 0 0 14px; }
      h2 { font-size: 16px; margin: 0 0 12px; }
      button { height: 38px; padding: 0 18px; border: 0; border-radius: 6px; background: #1d4ed8; color: #fff; font-weight: 600; cursor: pointer; }
      textarea { border: 1px solid #cfd7e3; border-radius: 6px; padding: 10px; font-size: 14px; }
      pre { white-space: pre-wrap; word-break: break-word; }
      @media (max-width: 900px) { .workspace, .workspace.lower { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
  </body>
</html>
"""


@app.callback(
    Output("answer", "children"),
    Output("latency", "figure"),
    Output("citations", "children"),
    Input("submit", "n_clicks"),
    State("query", "value"),
    State("mode", "value"),
    prevent_initial_call=True,
)
def analyze(n_clicks, query, mode):
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/v2/analyze",
            json={"query": query, "mode": mode, "user_id": "dash"},
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()["data"]
    except Exception as exc:
        return f"Request failed: {exc}", go.Figure(), ""

    latency = payload.get("latency", {})
    figure = go.Figure(
        data=[
            go.Bar(
                x=list(latency.keys()),
                y=[round(float(value), 4) for value in latency.values()],
                marker_color="#2563eb",
            )
        ]
    )
    figure.update_layout(
        margin={"l": 32, "r": 12, "t": 12, "b": 42},
        yaxis_title="seconds",
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    return payload.get("answer", ""), figure, "\n".join(
        f"{item.get('source')} page {item.get('page')} score {item.get('score')}"
        for item in payload.get("citations", [])
    )


if __name__ == "__main__":
    app.run(host=os.getenv("DASH_HOST", "0.0.0.0"), port=int(os.getenv("DASH_PORT", "8050")), debug=False)
