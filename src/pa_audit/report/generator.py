import json
from pathlib import Path
from jinja2 import Template

TPL = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>PA Audit Summary</title>
<style>
body{font-family:system-ui;margin:40px;background:#f9fafb;color:#111}
h1{border-bottom:2px solid #e5e7eb;padding-bottom:12px}
table{width:100%;border-collapse:collapse;margin-top:24px}
th,td{padding:12px;text-align:left;border-bottom:1px solid #e5e7eb}
.badge{padding:4px 8px;border-radius:4px;font-size:12px;font-weight:500}
.pass{background:#d1fae5;color:#065f46}.warn{background:#fef3c7;color:#92400e}.crit{background:#fee2e2;color:#991b1b}
</style></head><body>
<h1>PA Forensic Audit - {{ rating_area }} (GPCI {{ gpci }})</h1>
<p>{{ total }} claims | {{ critical }} critical | {{ nsa }} NSA violations</p>
<table><thead><tr><th>File</th><th>Claim</th><th>Billed</th><th>FMV</th><th>Var%</th><th>Risk</th></tr></thead>
<tbody>
{% for r in results %}
<tr>
<td>{{ r.get("source_file") or r.get("file", "?") }}</td>
<td>{{ r.get("claim_id", "?") }}</td>
<td>${{ "%.2f"|format(r.get("billed_amount", 0)) }}</td>
<td>${{ "%.2f"|format(r.get("allowed_fmv", 0)) }}</td>
<td>{{ r.get("variance_pct", 0) }}%</td>
<td>
{% set risk = r.get("risk_category") or r.get("risk", "PASS") %}
{% if risk == "PASS" %}<span class="badge pass">PASS</span>
{% elif risk in ("POTENTIAL_AUDIT","POTENTIAL") %}<span class="badge warn">POTENTIAL</span>
{% else %}<span class="badge crit">CRITICAL</span>{% endif %}
</td>
</tr>
{% endfor %}
</tbody></table>
</body></html>"""


def generate(ledger_path: Path, output_path: Path, ra: str = "RA7", gpci: float = 1.0):
    results = [json.loads(l) for l in ledger_path.read_text().splitlines() if l.strip()]
    critical = sum(1 for r in results if (r.get("risk_category") or r.get("risk")) == "CRITICAL_OVERCHARGE")
    nsa = sum(1 for r in results if r.get("nsa_violation") is True)
    html = Template(TPL).render(rating_area=ra, gpci=gpci, total=len(results), critical=critical, nsa=nsa, results=results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    print(f"Report: {output_path}")
