#!/usr/bin/env python3
"""Check the generated HTML for the deal dropdown."""
import os

html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site", "preview", "index.html")
if not os.path.exists(html_path):
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site", "index.html")

if not os.path.exists(html_path):
    print(f"No HTML file found")
else:
    with open(html_path) as f:
        html = f.read()
    print(f"File: {html_path}")
    print(f"Size: {len(html)} bytes")
    print(f"Has 'dealSelect': {'dealSelect' in html}")
    print(f"Has '<select': {'<select' in html}")
    print(f"Has 'switchDeal': {'switchDeal' in html}")
    print(f"Has '2021-P1': {'2021-P1' in html}")
    print(f"Has 'deal-2020-P1': {'deal-2020-P1' in html}")
    print(f"Has 'deal-2021-N1': {'deal-2021-N1' in html}")

    # Show the first 2000 chars to see structure
    print(f"\nFirst 2000 chars:\n{html[:2000]}")
