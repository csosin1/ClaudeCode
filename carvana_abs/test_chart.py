#!/usr/bin/env python3
"""Quick test: does Plotly chart generation produce actual data?"""
import plotly.express as px
import plotly.io as pio

fig = px.line(x=["Jan","Feb","Mar"], y=[377000000, 243000000, 154000000])
h = pio.to_html(fig, full_html=False, include_plotlyjs=False, config={"displayModeBar": False})
print(f"Length: {len(h)}")
print(f"Has 377: {'377' in h}")
print(f"First 300: {h[:300]}")
