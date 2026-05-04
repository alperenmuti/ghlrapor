"""
Gemini cevabındaki ```chart``` spec bloklarını Plotly figürlerine çevirir.

Felsefe: LLM sayıları uydurmasın. Spec verir, biz dataframe'den hesaplarız.
"""
from __future__ import annotations

import json
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

CHART_RE = re.compile(r"```chart\s*\n(.*?)```", re.DOTALL)


def extract_chart_specs(text: str) -> tuple[str, list[dict]]:
    """Markdown text'inden chart bloklarını ayıklar; geri kalan metni döner."""
    specs: list[dict] = []
    for m in CHART_RE.finditer(text):
        try:
            specs.append(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            continue
    return CHART_RE.sub("", text).strip(), specs


def _apply_filter(df: pd.DataFrame, filt: dict | None) -> pd.DataFrame:
    if not filt:
        return df
    out = df
    for k, v in filt.items():
        if k not in out.columns:
            continue
        if isinstance(v, list):
            out = out[out[k].isin(v)]
        else:
            out = out[out[k] == v]
    return out


def render_chart(spec: dict, df: pd.DataFrame):
    """Hatalıysa None döner; çağıran tarafta None kontrolü yapılır."""
    chart_type = (spec.get("type") or "bar").lower()
    title = spec.get("title", "")
    df = _apply_filter(df, spec.get("filter"))
    if df.empty:
        return None

    try:
        if chart_type == "pie":
            col = spec["groupby"]
            if col not in df.columns:
                return None
            counts = (
                df[col].fillna("(boş)").value_counts().head(int(spec.get("top", 12))).reset_index()
            )
            counts.columns = [col, "count"]
            return px.pie(
                counts, names=col, values="count", title=title, hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )

        if chart_type in ("bar", "horizontal_bar", "hbar"):
            col = spec["groupby"]
            if col not in df.columns:
                return None
            agg = (spec.get("agg") or "count").lower()
            top = int(spec.get("top", 15))
            if agg == "count":
                data = df[col].fillna("(boş)").value_counts().head(top).reset_index()
                data.columns = [col, "value"]
                value_label = "lead sayısı"
            else:
                value_col = spec.get("value_col", "monetary_value")
                if value_col not in df.columns:
                    return None
                data = (
                    df.groupby(col, dropna=False)[value_col]
                    .agg(agg)
                    .sort_values(ascending=False)
                    .head(top)
                    .reset_index()
                )
                data.columns = [col, "value"]
                value_label = f"{agg}({value_col})"
            horizontal = chart_type in ("horizontal_bar", "hbar") or (
                spec.get("orientation") == "h"
            )
            if horizontal:
                fig = px.bar(
                    data, y=col, x="value", orientation="h", title=title,
                    color="value", color_continuous_scale="Viridis",
                )
                fig.update_layout(xaxis_title=value_label)
                fig.update_yaxes(autorange="reversed")
            else:
                fig = px.bar(
                    data, x=col, y="value", title=title,
                    color="value", color_continuous_scale="Viridis",
                )
                fig.update_layout(yaxis_title=value_label, xaxis_tickangle=-30)
            return fig

        if chart_type == "funnel":
            col = spec["groupby"]
            if col not in df.columns:
                return None
            counts = df[col].fillna("(boş)").value_counts()
            order = spec.get("order")
            if order:
                counts = counts.reindex(order).fillna(0)
            data = counts.reset_index()
            data.columns = [col, "count"]
            return px.funnel(data, x="count", y=col, title=title)

        if chart_type == "line":
            x = spec.get("x", "created_at")
            freq = spec.get("freq", "D")
            color = spec.get("color")
            if x not in df.columns:
                return None
            tmp = df.dropna(subset=[x]).copy()
            tmp[x] = pd.to_datetime(tmp[x], utc=True, errors="coerce")
            tmp = tmp.dropna(subset=[x])
            if color and color in tmp.columns:
                ts = (
                    tmp.set_index(x)
                    .groupby([pd.Grouper(freq=freq), color])
                    .size()
                    .reset_index(name="count")
                )
                return px.line(ts, x=x, y="count", color=color, title=title, markers=True)
            ts = tmp.set_index(x).resample(freq).size().reset_index(name="count")
            return px.line(ts, x=x, y="count", title=title, markers=True)

        if chart_type == "scatter":
            x_col = spec.get("x")
            y_col = spec.get("y")
            if not x_col or not y_col or x_col not in df.columns or y_col not in df.columns:
                return None
            return px.scatter(
                df, x=x_col, y=y_col,
                color=spec.get("color"), title=title, hover_data=spec.get("hover", []),
            )

        if chart_type == "table":
            cols = spec.get("columns") or list(df.columns)[:8]
            cols = [c for c in cols if c in df.columns]
            data = df[cols].head(int(spec.get("rows", 30)))
            fig = go.Figure(
                data=[
                    go.Table(
                        header=dict(values=cols, fill_color="#262730", font=dict(color="white")),
                        cells=dict(values=[data[c].astype(str) for c in cols]),
                    )
                ]
            )
            fig.update_layout(title=title, margin=dict(t=40, b=10, l=0, r=0))
            return fig
    except Exception:
        return None
    return None
