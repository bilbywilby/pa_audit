import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pa_audit.eob.audit import ForensicClaimAuditor, PIIScrubber
from pa_audit.pfs.load import FeeScheduleItem, FeeScheduleLoader


def test_pii_scrubber_deterministic():
    s = PIIScrubber(b"test-key")
    a = s.scrub_id("JOHN_DOE_123")
    b = s.scrub_id("JOHN_DOE_123")
    c = s.scrub_id("JANE_DOE_456")
    assert a == b
    assert a != c
    assert a.startswith("ANON-")


def test_fmv_calculation():
    item = FeeScheduleItem("99214", "test", 130.0, 95.0)
    assert FeeScheduleLoader.calculate_fmv(item, 1.0, False) == 130.0
    assert FeeScheduleLoader.calculate_fmv(item, 1.15, False) == 149.5
    assert FeeScheduleLoader.calculate_fmv(item, 1.0, True) == 95.0


def test_audit_claim_pass():
    pfs = {"72148": FeeScheduleItem("72148", "MRI", 350.0, 275.0)}
    auditor = ForensicClaimAuditor(pfs, [])
    r = auditor.audit_claim({
        "claim_id": "T1", "patient_id": "P1",
        "billed_amount": 360.0, "cpt_code": "72148",
        "is_facility": False, "gpci": 1.0,
    })
    assert r.risk_category == "PASS"
    assert not r.nsa_violation


def test_audit_claim_critical():
    pfs = {"72148": FeeScheduleItem("72148", "MRI", 350.0, 275.0)}
    auditor = ForensicClaimAuditor(pfs, [])
    r = auditor.audit_claim({
        "claim_id": "T2", "patient_id": "P2",
        "billed_amount": 950.0, "cpt_code": "72148",
        "is_facility": False, "gpci": 1.0,
        "is_emergency": True, "is_out_of_network": True,
    })
    assert r.risk_category == "CRITICAL_OVERCHARGE"
    assert r.nsa_violation
    assert len(r.violations) >= 1
