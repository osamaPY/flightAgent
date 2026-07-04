"""v5: Static HTML dashboard — SQLite → sortable HTML table.

Zero framework, zero server. Generates one self-contained HTML file with:
- Sortable table of all deals (click column headers to sort)
- Color-coded confidence labels
- Grand total breakdown (flights + transfers + 10 kg carry-on bags)
- Ranking by true cost with confidence penalty

Run: python scripts/dashboard.py
Open: data/dashboard.html in browser
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.core.storage import Storage
from src.core.airports import CANDIDATE_DESTINATIONS


def _city(iata: str) -> str:
    for a in CANDIDATE_DESTINATIONS:
        if a.iata == iata:
            return f"{a.flag} {a.city}"
    return iata


def _conf_color(label: str) -> str:
    if not label:
        return "#999"
    if "HIGH" in label:
        return "#2e7d32"
    if "MEDIUM" in label:
        return "#f57f17"
    return "#c62828"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Flight Meet — Deals Dashboard</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; margin: 20px; }}
  h1 {{ color: #00d4ff; }}
  .stats {{ display: flex; gap: 20px; margin: 10px 0 20px; }}
  .stat {{ background: #16213e; padding: 12px 20px; border-radius: 8px; }}
  .stat .val {{ font-size: 1.5em; font-weight: bold; color: #00d4ff; }}
  .stat .label {{ font-size: 0.8em; color: #888; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
  th {{ background: #0f3460; padding: 10px 8px; text-align: left; cursor: pointer; position: sticky; top: 0; }}
  th:hover {{ background: #1a4a7a; }}
  td {{ padding: 8px; border-bottom: 1px solid #333; }}
  tr:hover {{ background: #16213e; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: bold; }}
  .grand {{ font-weight: bold; color: #00d4ff; }}
  .pct {{ font-size: 0.8em; color: #888; }}
  .updated {{ color: #666; font-size: 0.8em; margin-top: 20px; }}
</style>
</head>
<body>
<h1>Flight Meet — Deals Dashboard</h1>
<div class="stats">
  <div class="stat"><div class="val">{total_deals}</div><div class="label">Total deals</div></div>
  <div class="stat"><div class="val">EUR {best_price:.0f}</div><div class="label">Best grand total</div></div>
  <div class="stat"><div class="val">{high_conf}</div><div class="label">HIGH confidence</div></div>
  <div class="stat"><div class="val">{cities}</div><div class="label">Destinations</div></div>
</div>
<table id="deals">
<thead><tr>
  <th onclick="sort(0)">#</th>
  <th onclick="sort(1)">Destination</th>
  <th onclick="sort(2)">Dates</th>
  <th onclick="sort(3)">Flights</th>
  <th onclick="sort(4)">+Transfers+Bags</th>
  <th onclick="sort(5)">Grand Total</th>
  <th onclick="sort(6)">Airlines</th>
  <th onclick="sort(7)">Confidence</th>
  <th onclick="sort(8)">Deal %</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
<p class="updated">Generated {timestamp}</p>
<script>
  function sort(col) {{
    const tbody = document.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const isNum = [0,3,4,5,8].includes(col);
    rows.sort((a,b) => {{
      let va = a.children[col].textContent.replace('EUR ','').replace('%','');
      let vb = b.children[col].textContent.replace('EUR ','').replace('%','');
      if (isNum) return parseFloat(vb) - parseFloat(va);
      if (col === 2) return va.localeCompare(vb);
      return va.localeCompare(vb);
    }});
    rows.forEach(r => tbody.appendChild(r));
  }}
  sort(5);
</script>
</body>
</html>"""


def build_dashboard(output_path: str = "data/dashboard.html") -> str:
    storage = Storage()
    now = datetime.now().isoformat(timespec="minutes")

    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT destination, total_price, outbound_date, return_date,
                   a_origin, a_price, b_origin, b_price,
                   grand_total, transfer_cost, bag_cost,
                   flight_airlines, flight_numbers, confidence_label,
                   deal_percentile, source
            FROM results
            WHERE timestamp > datetime('now', '-30 days')
            ORDER BY
                CASE
                    WHEN confidence_label LIKE '%HIGH%' THEN grand_total
                    WHEN confidence_label LIKE '%MEDIUM%' THEN grand_total + 15
                    ELSE grand_total + 40
                END ASC
        """)
        rows = cursor.fetchall()

    if not rows:
        return "No deals found. Run a search first."

    total_deals = len(rows)
    seen_cities = set()
    high_conf = 0
    best_price = float("inf")

    row_html = ""
    for i, row in enumerate(rows, 1):
        (dest, total, out, ret, a_org, a_p, b_org, b_p,
         grand, transfer, bag, airlines, flight_nos,
         conf, pct, source) = row

        seen_cities.add(dest)
        grand_f = float(grand or total or 0)
        if grand_f < best_price:
            best_price = grand_f
        if conf and "HIGH" in str(conf):
            high_conf += 1

        extras = round(float(transfer or 0) + float(bag or 0), 2)
        conf_str = str(conf or "")

        row_html += (
            f"<tr>"
            f"<td>{i}</td>"
            f"<td>{_city(dest)} ({dest})</td>"
            f"<td>{out} → {ret}</td>"
            f"<td>EUR {float(total or 0):.0f}</td>"
            f"<td>EUR {extras:.0f}</td>"
            f"<td class=\"grand\">EUR {grand_f:.0f}</td>"
            f"<td>{airlines or '—'}</td>"
            f"<td><span class=\"badge\" style=\"background:{_conf_color(conf_str)}\">"
            f"{conf_str or '—'}</span></td>"
            f"<td>{float(pct or 0):.0f}%</td>"
            f"</tr>\n"
        )

    html = HTML_TEMPLATE.format(
        total_deals=total_deals,
        best_price=best_price,
        high_conf=high_conf,
        cities=len(seen_cities),
        rows=row_html,
        timestamp=now,
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return f"Dashboard written to {output_path} ({total_deals} deals, {len(seen_cities)} cities)"


if __name__ == "__main__":
    print(build_dashboard())
