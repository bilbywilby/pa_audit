"""CLI entry point: pa-audit or python -m pa_audit."""
import argparse
import json
from pathlib import Path

from pa_audit.eob.audit import ForensicClaimAuditor
from pa_audit.ncci.parse import NCCIParser
from pa_audit.pfs.load import FeeScheduleLoader
from pa_audit.pa.rating_areas import get_multiplier


def main():
    parser = argparse.ArgumentParser(prog="pa-audit", description="PA forensic claim auditor")
    sub = parser.add_subparsers(dest="command")

    p_audit = sub.add_parser("audit", help="Audit a single claim from JSON")
    p_audit.add_argument("claim_json")
    p_audit.add_argument("--pfs", required=True)
    p_audit.add_argument("--ncci", required=True)
    p_audit.add_argument("--ra", default="RA7")
    p_audit.add_argument("--output")

    p_batch = sub.add_parser("batch", help="Audit all claims in a directory")
    p_batch.add_argument("claims_dir")
    p_batch.add_argument("--pfs", required=True)
    p_batch.add_argument("--ncci", required=True)
    p_batch.add_argument("--ra", default="RA7")
    p_batch.add_argument("--ledger")

    sub.add_parser("init", help="Create sample fixtures")

    args = parser.parse_args()

    if args.command == "init":
        _init_fixtures()
    elif args.command == "audit":
        _run_audit(args)
    elif args.command == "batch":
        _run_batch(args)
    else:
        parser.print_help()


def _init_fixtures():
    fx = Path("data/fixtures")
    fx.mkdir(parents=True, exist_ok=True)
    pfs = fx / "sample_pfs.csv"
    if not pfs.exists():
        pfs.write_text(
            "cpt_code,description,non_facility_price,facility_price\n"
            "99214,Office visit est med 25min,130.00,95.00\n"
            "99215,Office visit est med 30min,175.00,125.00\n"
            "72148,MRI lumbar w/o contrast,350.00,275.00\n"
            "45378,Diagnostic colonoscopy,600.00,450.00\n"
            "93000,EKG routine,45.00,30.00\n"
        )
    ncci = fx / "sample_ncci.txt"
    if not ncci.exists():
        ncci.write_text(
            "Column1Code\tColumn2Code\tEffectiveDate\tDeletionDate\tModifierIndicator\n"
            "99214\t72148\t20260101\t\t0\n"
            "45378\t93000\t20260101\t\t1\n"
        )
    print(f"Fixtures created in {fx}/")


def _load_data(pfs_path: str, ncci_path: str):
    pfs_file = Path(pfs_path)
    if pfs_file.suffix == ".json":
        pfs = FeeScheduleLoader.load_pfs_json(pfs_file)
    else:
        pfs = FeeScheduleLoader.load_pfs_csv(pfs_file)
    ncci = NCCIParser.load_ncci_ptp(Path(ncci_path))
    return pfs, ncci


def _run_audit(args):
    pfs, ncci = _load_data(args.pfs, args.ncci)
    gpci = get_multiplier(args.ra)
    auditor = ForensicClaimAuditor(pfs, ncci)
    claim = json.loads(Path(args.claim_json).read_text())
    claim.setdefault("gpci", gpci)
    result = auditor.audit_claim(claim)
    report = {
        "audit_version": "PY2027-v1.0",
        "rating_area": args.ra,
        "gpci_applied": gpci,
        "claim": {
            "claim_id": result.claim_id,
            "patient_anon": result.patient_id_anon,
            "billed": result.billed_amount,
            "allowed_fmv": result.allowed_fmv,
            "variance_pct": result.variance_pct,
            "risk": result.risk_category,
            "nsa_violation": result.nsa_violation,
            "violations": result.violations,
        },
    }
    output = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}")
    else:
        print(output)


def _run_batch(args):
    pfs, ncci = _load_data(args.pfs, args.ncci)
    gpci = get_multiplier(args.ra)
    auditor = ForensicClaimAuditor(pfs, ncci)
    claims_dir = Path(args.claims_dir)
    results = []
    for f in sorted(claims_dir.glob("*.json")):
        claim = json.loads(f.read_text())
        claim.setdefault("gpci", gpci)
        r = auditor.audit_claim(claim)
        results.append({"file": f.name, "claim_id": r.claim_id, "risk": r.risk_category, "variance_pct": r.variance_pct, "nsa_violation": r.nsa_violation})
        if args.ledger:
            with open(args.ledger, "a") as ledger:
                ledger.write(json.dumps({"file": f.name, "claim_id": r.claim_id, "risk": r.risk_category, "variance_pct": r.variance_pct, "nsa_violation": r.nsa_violation, "violations": r.violations}) + "\n")
    print(json.dumps({"total": len(results), "results": results}, indent=2))


if __name__ == "__main__":
    main()
