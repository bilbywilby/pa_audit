## The Complete `full_audit.py` (The Script That Ties Everything Together)

```python
#!/usr/bin/env python3
"""full_audit.py — Complete EOB audit: variance + NCCI + MUE + add-on + balance billing.

Usage:
  python3 full_audit.py --input cases/2026-11-11_smith/eob.json
  python3 full_audit.py --input cases/2026-11-11_smith/eob.json --output audit_result.json

Loads all data files once (~5s), then processes every line in the EOB.
"""
import json, sys, time, argparse
from pathlib import Path
from datetime import date

BASE = Path.home() / "pa_audit"
PFS = BASE / "pfs" / "pfall26d.txt"
NCCI_DIR = BASE / "ncci"
CARC_FILE = BASE / "data" / "carc_rarc_lookup.json"

CF_2026 = 33.4009


# ─── DATA LOADERS ───────────────────────────────────────────────────────

def load_pfall(path):
    """Load PFALL into {(code, mod, pos, loc): allowed_dollar}."""
    idx = {}
    p = Path(path).expanduser()
    if not p.exists():
        print(f"WARNING: {p} not found. Variance checks disabled.", file=sys.stderr)
        return idx
    with open(p, "r") as f:
        for line in f:
            if len(line) < 76:
                continue
            code = line[2:8].strip().lstrip("0")
            if not code:
                continue
            mod = line[8:10].strip()
            pos = line[10:12].strip()
            loc = line[12:14].strip()
            # Try bytes 68:76 first, then 79:88
            try:
                amt = float(line[68:76])
            except ValueError:
                try:
                    amt = float(line[79:88])
                except ValueError:
                    continue
            if amt > 0:
                idx[(code, mod, pos, loc)] = amt
    return idx


def load_ncci():
    """Load NCCI PTP edits."""
    sys.path.insert(0, str(NCCI_DIR))
    try:
        from ncci_parse import load_ncci_ptp
    except ImportError:
        print("WARNING: ncci_parse.py not found. NCCI checks disabled.", file=sys.stderr)
        return {}
    files = sorted(NCCI_DIR.glob("ccipra-v323r0-f*.TXT"))
    if not files:
        print("WARNING: No NCCI files found. NCCI checks disabled.", file=sys.stderr)
        return {}
    return load_ncci_ptp([str(f) for f in files])


def load_carc():
    """Load CARC/RARC lookup."""
    p = Path(CARC_FILE).expanduser()
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


# ─── AUDIT LOGIC ────────────────────────────────────────────────────────

def audit_single_line(line, pfall, ncci, carc, locality):
    """Audit one EOB line. Returns dict with all findings."""
    cpt = line["cpt"].strip()
    mod = line.get("modifier", "").strip()
    pos = line.get("pos", "11").strip()
    billed = float(line["billed"])
    allowed = float(line["allowed"])
    patient_resp = float(line.get("patient_responsibility", 0))
    carc_code = line.get("carc", "")
    facility_in = line.get("facility_in_network", None)

    r = {
        "cpt": cpt, "modifier": mod, "pos": pos,
        "billed": billed, "allowed": allowed,
        "patient_responsibility": patient_resp, "carc": carc_code,
    }

    # ── Variance / NDF ──
    med_allowed = pfall.get((cpt, mod, pos, locality))
    if med_allowed is None and mod:
        med_allowed = pfall.get((cpt, "", pos, locality))

    if med_allowed and med_allowed > 0:
        r["medicare_allowed"] = med_allowed
        r["ndf"] = allowed / med_allowed
        r["variance_pct"] = (billed - allowed) / allowed * 100 if allowed > 0 else None
    else:
        r["medicare_allowed"] = None
        r["ndf"] = None
        r["variance_pct"] = (billed - allowed) / allowed * 100 if allowed > 0 else None

    # ── Balance billing check ──
    write_off = billed - allowed
    r["write_off"] = write_off

    if patient_resp > allowed and allowed > 0:
        r["balance_billing"] = True
        r["overcharge"] = patient_resp - allowed
    elif patient_resp > 0 and write_off > 0:
        r["balance_billing"] = "CHECK"
    else:
        r["balance_billing"] = False

    # ── Variance flag ──
    v = r["variance_pct"]
    if v is None:
        r["flag"] = "ERROR"
    elif v <= 15:
        r["flag"] = "PASS"
    elif v <= 40:
        r["flag"] = "POTENTIAL_AUDIT"
    else:
        r["flag"] = "CRITICAL_OVERCHARGE"

    # ── NSA check ──
    if carc_code == "OE-132" and facility_in:
        r["flag"] = "NSA_REVIEW_REQUIRED"
        r["nsa_note"] = "OON provider at IN facility. Verify NSA applicability."

    # ── CARC interpretation ──
    if carc_code and carc_code in carc:
        r["carc_meaning"] = carc[carc_code].get("meaning", "")
        r["carc_action"] = carc[carc_code].get("action", "")

    # ── Bundling detection (CO-97, CO-236, CO-234, CO-B15) ──
    if carc_code in ("CO-97", "CO-236", "CO-234", "CO-231", "CO-B15"):
        r["bundling_denial"] = True
        r["bundling_carc"] = carc_code
        if allowed == 0 and patient_resp == 0:
            r["bundling_harm"] = False
            r["bundling_note"] = "Bundled code. Patient not charged. No action needed."
        elif patient_resp > 0:
            r["bundling_harm"] = True
            r["bundling_note"] = (
                f"Bundled code but patient charged ${patient_resp:.2f}. "
                f"Verify this is not balance billing."
            )

    # ── Dual eligible check ──
    if line.get("dual_eligible") and patient_resp > 0:
        r["dual_eligible_error"] = True
        r["dual_note"] = (
            f"Dual-eligible patient charged ${patient_resp:.2f}. "
            f"Should be $0. CHC-MCO covers Medicare cost-sharing."
        )

    return r


def check_ncci_pairs(lines, ncci):
    """Check all CPT code pairs on the claim for NCCI bundling."""
    codes = []
    modifiers = {}
    for line in lines:
        cpt = line["cpt"].strip()
        if cpt and cpt not in codes:
            codes.append(cpt)
        mod = line.get("modifier", "").strip()
        if mod:
            modifiers.setdefault(cpt, []).append(mod)

    if len(codes) < 2 or not ncci:
        return []

    violations = []
    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            a, b = codes[i], codes[j]
            edit = ncci.get((a, b)) or ncci.get((b, a))
            if edit is None:
                continue
            col1, col2 = (a, b) if ncci.get((a, b)) else (b, a)
            mods_on_col2 = modifiers.get(col2, [])
            qualifying = {"25", "59", "XE", "XP", "XS", "XU", "EP"}
            has_mod = any(m in qualifying for m in mods_on_col2)

            if edit["ccmi"] == 0:
                violations.append({
                    "pair": f"{col1}/{col2}",
                    "ccmi": 0,
                    "status": "BUNDLED — never payable together",
                    "denied": col2,
                })
            elif edit["ccmi"] == 1 and not has_mod:
                violations.append({
                    "pair": f"{col1}/{col2}",
                    "ccmi": 1,
                    "status": "BUNDLED — modifier required",
                    "denied": col2,
                })
            elif edit["ccmi"] == 1 and has_mod:
                violations.append({
                    "pair": f"{col1}/{col2}",
                    "ccmi": 1,
                    "status": f"Edit triggered — modifier {mods_on_col2} applied",
                    "denied": None,
                })
    return violations


# ─── MAIN ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Full EOB audit")
    ap.add_argument("--input", required=True)
    ap.add_argument("--locality", default="99", choices=["01", "99"])
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    # Load data
    t0 = time.time()
    pfall = load_pfall(PFS)
    ncci = load_ncci()
    carc = load_carc()
    load_time = time.time() - t0
    print(f"Data loaded in {load_time:.1f}s "
          f"(PFALL: {len(pfall):,}, NCCI: {len(ncci):,}, CARC: {len(carc):,})")

    # Load EOB
    with open(args.input) as f:
        eob = json.load(f)

    locality = args.locality
    lines = eob.get("lines", [])

    # Audit each line
    results = []
    for line in lines:
        r = audit_single_line(line, pfall, ncci, carc, locality)
        results.append(r)

    # NCCI pair check
    ncci_violations = check_ncci_pairs(lines, ncci)

    # Summary
    flagged = [r for r in results if r["flag"] not in ("PASS",)]
    balance = [r for r in results if r.get("balance_billing") is True]
    nsa = [r for r in results if r["flag"] == "NSA_REVIEW_REQUIRED"]
    dual = [r for r in results if r.get("dual_eligible_error")]
    bundling_harm = [r for r in results if r.get("bundling_harm")]

    total_billed = sum(r["billed"] for r in results)
    total_allowed = sum(r["allowed"] for r in results)
    total_patient = sum(r["patient_responsibility"] for r in results)

    print(f"\n{'='*60}")
    print(f"  EOB AUDIT: {eob.get('payer', 'Unknown')}")
    print(f"  Member: {eob.get('member_id', 'N/A')}")
    print(f"  DOS:    {eob.get('date_of_service', 'N/A')}")
    print(f"  Lines:  {len(results)}")
    print(f"  Billed: ${total_billed:,.2f}  Allowed: ${total_allowed:,.2f}  Patient: ${total_patient:,.2f}")
    print(f"{'='*60}\n")

    for r in results:
        flag = r["flag"]
        v = r.get("variance_pct")
        v_str = f"V={v:.1f}%" if v is not None else "V=N/A"
        ndf = r.get("ndf")
        ndf_str = f"NDF={ndf*100:.0f}%" if ndf else ""
        bb = ""
        if r.get("balance_billing") is True:
            bb = f" ⚠ BALANCE BILLING +${r.get('overcharge', 0):.2f}"
        elif r.get("balance_billing") == "CHECK":
            bb = " ? CHECK"
        if r.get("dual_eligible_error"):
            bb += " ⚠ DUAL ELIGIBLE"
        if r.get("bundling_harm"):
            bb += " ⚠ BUNDLING HARM"

        print(f"  [{flag:25s}] {r['cpt']}-{r['modifier'] or '  '}  "
              f"${r['billed']:>8.2f}→${r['allowed']:>8.2f}  {v_str:10s} {ndf_str}{bb}")

    # NCCI violations
    if ncci_violations:
        print(f"\n  NCCI EDITS ({len(ncci_violations)}):")
        for v in ncci_violations:
            print(f"    [{v['status']}] {v['pair']}")

    # Summary
    print(f"\n  SUMMARY: {len(flagged)} flagged | {len(balance)} balance billing | "
          f"{len(nsa)} NSA | {len(dual)} dual-eligible | {len(bundling_harm)} bundling harm")

    # Action items
    actions = []
    for r in flagged:
        if r["flag"] == "CRITICAL_OVERCHARGE":
            actions.append(f"  • {r['cpt']}-{r['modifier']}: File claim dispute with payer")
        elif r["flag"] == "POTENTIAL_AUDIT":
            actions.append(f"  • {r['cpt']}-{r['modifier']}: Request itemized bill")
        elif r["flag"] == "NSA_REVIEW_REQUIRED":
            actions.append(f"  • {r['cpt']}-{r['modifier']}: Payer NSA line + CMS complaint")
    for r in balance:
        actions.append(f"  • {r['cpt']}: Balance billing ${r.get('overcharge', 0):.2f} → demand letter")
    for r in dual:
        actions.append(f"  • {r['cpt']}: Dual-eligible billing error → CHC-MCO + PA DHS OIG")

    if actions:
        print(f"\n  ACTION ITEMS:")
        for a in actions:
            print(a)
    else:
        print(f"\n  ✓ No action required. All lines within normal parameters.")

    # Write full results
    if args.output:
        out = {
            "eob_metadata": {k: v for k, v in eob.items() if k != "lines"},
            "locality": locality,
            "audit_date": str(date.today()),
            "results": results,
            "ncci_violations": ncci_violations,
            "summary": {
                "total_lines": len(results),
                "flagged": len(flagged),
                "balance_billing": len(balance),
                "nsa": len(nsa),
                "dual_eligible": len(dual),
                "bundling_harm": len(bundling_harm),
            },
            "actions": actions,
        }
        Path(args.output).write_text(json.dumps(out, indent=2))
        print(f"\n  Full results: {args.output}")


if __name__ == "__main__":
    main()
```

## The `eob.json` Input Format (What You Actually Type)

This is the file you create by hand (or OCR) from the patient's documents. Every field:

```json
{
  "payer": "Highmark",
  "member_id": "HM123456789",
  "date_of_service": "2026-10-15",
  "provider_npi": "1234567890",
  "provider_name": "Lehigh Valley Radiology Associates",
  "facility_in_network": true,
  "provider_in_network": true,
  "dual_eligible": false,
  "deductible_met": true,
  "deductible_remaining": 0,
  "coinsurance_rate": 0.20,
  "oop_remaining": 3400,
  "lines": [
    {
      "cpt": "99214",
      "modifier": "",
      "pos": "11",
      "billed": 350.00,
      "allowed": 185.00,
      "patient_responsibility": 37.00,
      "carc": "PR-1"
    },
    {
      "cpt": "72148",
      "modifier": "26",
      "pos": "11",
      "billed": 1200.00,
      "allowed": 437.21,
      "patient_responsibility": 850.00,
      "carc": "OB-157",
      "facility_in_network": true,
      "provider_in_network": false
    },
    {
      "cpt": "72148",
      "modifier": "TC",
      "pos": "22",
      "billed": 2800.00,
      "allowed": 1150.00,
      "patient_responsibility": 0.00,
      "carc": "OB-137"
    }
  ]
}
```

**Where each field comes from:**

| Field | Source | Notes |
|-------|--------|-------|
| `payer` | Top of EOB | Payer name |
| `member_id` | EOB header | Patient's insurance ID |
| `date_of_service` | EOB or itemized bill | The date the service was rendered |
| `provider_npi` | Itemized bill header | 10 digits |
| `facility_in_network` | EOB (network status column) | Yes/No for the facility |
| `provider_in_network` | EOB (network status column) | Yes/No for the rendering provider |
| `dual_eligible` | Patient tells you / Medicare card | True if they have both Medicare + Medicaid |
| `deductible_met` | EOB ("Deductible met: Yes/No") | Affects the balance billing check |
| `coinsurance_rate` | EOB or plan documents | Usually 10%, 20%, or 30% |
| `oop_remaining` | EOB ("OOP max remaining: $X") | Affects whether patient should owe anything |
| `lines[].cpt` | Itemized bill (CPT column) | 5 alphanumeric chars |
| `lines[].modifier` | Itemized bill (modifier column) | 2 chars or blank |
| `lines[].pos` | Itemized bill or context | 11=office, 22=outpatient, 24=ER |
| `lines[].billed` | Itemized bill (charge column) | What the provider charged |
| `lines[].allowed` | EOB (allowed column) | What the payer approved |
| `lines[].patient_responsibility` | EOB (your responsibility column) | What the patient was told to pay |
| `lines[].carc` | EOB (adjustment code) | 2-5 char code (OB-157, OE-132, etc.) |

**The 30-second cross-check before running the audit:**

```
For each line:
  billed - allowed = write_off (should be ≥ 0)
  If deductible met: patient_resp ≈ allowed × coinsurance_rate
  If patient_resp > allowed: STOP. You probably misread a column.
```

## Case Management: The INDEX.md

As you accumulate cases, `~/pa_audit/cases/INDEX.md` tracks everything:

```markdown
# Case Index

| Case ID | Patient | Payer | CPT | Flag | Status | Deadline |
|---------|---------|-------|-----|------|--------|----------|
| 2026-11-11_smith | J. Smith | Highmark | 72148-26 | BALANCE BILLING | Awaiting billing office | 2027-05-10 (180d) |
| 2026-11-12_jones | M. Jones | UPMC | 27447 | OA-16 DENIAL | LMN drafted, awaiting signature | 2027-05-11 (180d) |
| 2026-11-14_doe | R. Doe | Keystone | 99213 | PASS | Closed | — |

## Active Deadlines (sorted)

| Deadline | Case | Action |
|----------|------|--------|
| 2026-11-25 | jones | Get physician signature on LMN |
| 2026-12-01 | jones | File internal appeal with UPMC |
| 2027-01-15 | jones | If denied: file PA DOI external review |
| 2027-05-10 | smith | 180-day deadline (hard stop) |
```

**The deadline calculation:**

```python
from datetime import date, timedelta

def appeal_deadline(eob_date_str):
    """180 days from EOB date."""
    eob = date.fromisoformat(eob_date_str)
    return eob + timedelta(days=180)

def external_review_deadline(denial_date_str):
    """4 calendar months from final internal denial."""
    denial = date.fromisoformat(denial_date_str)
    # Add 4 months (calendar, not 120 days)
    month = denial.month + 4
    year = denial.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(denial.day, 28)  # Avoid month-length issues
    return date(year, month, day)
```

## Legal Liability: Operating as an Unpaid Patient Advocate

This is the question nobody asks until it matters. You're not a lawyer, not a registered agent, not a licensed insurance adjuster. What are you?

**In PA, the relevant categories:**

| Role | License Required? | What You Can Do | What You Can't Do |
|------|:---:|----------------|------------------|
| **Patient advocate** (unpaid, for a specific person) | No | Help them read their EOB, make phone calls, draft letters, file complaints | Give legal advice, represent them in court, charge a fee for "legal services" |
| **Insurance agent/adjuster** | Yes (PA DOI license) | Negotiate with insurers for compensation, file claims on behalf of clients | — |
| **Attorney** | Yes (PA Bar) | File lawsuits, represent in external review (formally), give legal advice | — |
| **Medical billing auditor** (for providers) | No (but CPA/CPC certification common) | Audit provider billing, identify coding errors | Bill patients, give legal advice |

**The safe zone:** If you're helping a specific person (family member, friend, volunteer) for free, and you're:
- Reading documents they gave you
- Making phone calls they authorize
- Drafting letters they sign and send
- Filing complaints with PA DOI / CMS on their behalf (with their written authorization)

...you're a **patient advocate**, not a lawyer or agent. No license required. This is explicitly permitted.

**The line you must not cross:**

| Action | Risk |
|--------|------|
| Telling a patient "you have a legal right to X" | Fine (stating the law) |
| Telling a patient "you should sue the provider" | **Crosses into legal advice** |
| Charging a patient $50/hour for your time | **Requires insurance agent license** (PA DOI) |
| Taking a percentage of the recovered amount | **Requires insurance agent license + contract** |
| Filing a small claims complaint on their behalf | **Requires attorney license** (or they file it themselves) |
| Signing documents as their "representative" without a HIPAA release | **HIPAA violation** |

**The HIPAA release:** Before you look at anyone's EOB, medical records, or make any call on their behalf, you need a signed **HIPAA authorization** (45 CFR § 164.508). It's a one-page form:

```
HIPAA AUTHORIZATION FOR DISCLOSURE OF PROTECTED HEALTH INFORMATION

I, [Patient Name], authorize [Your Name] to receive and discuss
my protected health information, including billing records,
Explanations of Benefits, and claim status, with the following
healthcare providers and health plans:

  Providers: [list or "any"]
  Health Plans: [list or "any"]

Purpose: To assist me in reviewing my medical bills and
          pursuing any applicable disputes or appeals.

Expiration: [Date or "treatment, payment, health care operations"]

Signature: ________________________  Date: __________

I understand that I may revoke this authorization in writing at
any time, and that my treatment will not be affected by whether
I sign or revoke this authorization.
```

**The practical risk:** Low, if you stay in the "helping a specific person for free" zone. The PA DOI does not regulate patient advocates. The PA Bar does not regulate non-legal assistance. The only real risk is if you start doing this for multiple people, charging money, or giving advice that crosses into "practice of law" or "unlicensed insurance adjustment."

**The disclaimer to include in every case file:**

```
I am not an attorney, insurance agent, or licensed adjuster.
I am assisting [Pati
