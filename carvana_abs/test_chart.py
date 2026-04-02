#!/usr/bin/env python3
"""Test: generate chart using raw Plotly.js instead of Python Plotly."""
import json

x = ["Jan", "Feb", "Mar"]
y = [377000000, 243000000, 154000000]

html = f"""<!DOCTYPE html>
<html><head>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head><body>
<div id="chart1" style="width:100%;height:350px;"></div>
<script>
Plotly.newPlot('chart1', [{{
    x: {json.dumps(x)},
    y: {json.dumps(y)},
    type: 'scatter',
    fill: 'tozeroy'
}}], {{
    title: 'Pool Balance',
    yaxis: {{tickformat: '$,.0f'}},
    margin: {{l:60,r:20,t:40,b:30}}
}}, {{displayModeBar: false}});
</script>
</body></html>"""

with open("carvana_abs/static_site/test.html", "w") as f:
    f.write(html)
print(f"Written test.html ({len(html)} bytes)")
print(f"Has 377: {'377' in html}")
