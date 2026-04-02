#!/usr/bin/env python3
"""Test different Plotly to_html approaches."""
import plotly.express as px
import plotly.io as pio
import json

fig = px.line(x=["Jan","Feb","Mar"], y=[377000000, 243000000, 154000000])

# Method 1: to_html with include_plotlyjs=False
h1 = fig.to_html(full_html=False, include_plotlyjs=False)
print(f"Method 1 (no js): len={len(h1)}, has 377={'377' in h1}")

# Method 2: to_html with include_plotlyjs='cdn'
h2 = fig.to_html(full_html=False, include_plotlyjs='cdn')
print(f"Method 2 (cdn): len={len(h2)}, has 377={'377' in h2}")

# Method 3: Manual - extract fig data as JSON and build div ourselves
fig_json = fig.to_json()
print(f"Method 3 (json): len={len(fig_json)}, has 377={'377' in fig_json}")
print(f"JSON preview: {fig_json[:200]}")
