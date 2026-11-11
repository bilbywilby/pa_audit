"""Forensic claim auditor with PII pseudonymization and NSA checks."""
import hashlib
import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from pa_audit.ncci.parse import NCCIEdit
from pa_audit.pfs.load import FeeScheduleItem, FeeScheduleLoader


class PIIScrubber:
    """Deterministic HMAC-SHA256 pseudonymization.

    Key source (in order): PA_AUDIT_SALT env var, ~/.pa_audit_salt file, or generated.
    """

    def __init__(self, secret_key: bytes | None = None):
        if secret_key is None:
            env = os.environ.get("PA_AUDIT_SALT")
            if env:
                secret_key = env.encode()
            else:
                salt_path = Path.home() / ".pa_audit_salt"
                if salt_path.exists():
                    secret_key = salt_path.read_bytes()
                else:
                    secret_key = os.urandom(32)
                    salt_path.write_bytes(secret_key)
                    os.chmod(salt_path, 0o600)
        self._key = secret_key

    def scrub_id(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        digest = hmac.new(self._key, raw_value.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"ANON-{digest[:12].upper()}"


@dataclass
class AuditResult:
    claim_id: str
    patient_id_anon: str
    billed_amount: float
    allowed_fmv: float
    variance_pct: float
    risk_category: str
    nsa_violation: bool
    violations: List[str] = field(default_factory=list)


class ForensicClaimAuditor:
    def __init__(self, pfs_data: Dict[str, FeeScheduleItem], ncci_edits: List[NCCIEdit]):
        self.pfs = pfs_data
        self.ncci = {(e.column1_code, e.column2_code): e for e in ncci_edits}
        self.scrubber = PIIScrubber()

    def audit_claim(self, claim: Dict[str, Any]) -> AuditResult:
        claim_id = claim.get("claim_id", "CLM-000")
        patient_anon = self.scrubber.scrub_id(claim.get("patient_id", "UNKNOWN"))

        billed = float(claim.get("billed_amount", 0.0))
        cpt = claim.get("cpt_code", "")
        is_facility = claim.get("is_facility", False)
        gpci = float(claim.get("gpci", 1.0))
        is_emergency = claim.get("is_emergency", False)
        is_oon = claim.get("is_out_of_network", False)

        violations: List[str] = []

        item = self.pfs.get(cpt)
        fmv = FeeScheduleLoader.calculate_fmv(item, gpci, is_facility) if item else billed * 0.5

        variance = ((billed - fmv) / fmv) * 100 if fmv > 0 else 0.0

        if variance < 15.0:
            risk = "PASS"
        elif variance <= 40.0:
            risk = "POTENTIAL_AUDIT"
        else:
            risk = "CRITICAL_OVERCHARGE"

        nsa_violation = False
        if is_emergency and is_oon and billed > fmv:
            nsa_violation = True
            violations.append(
                f"NSA: Emergency OON billed ${billed:.2f} vs allowed ${fmv:.2f} "
                f"(+{variance:.1f}%). Balance billing prohibited under 45 CFR 149."
            )

        for (c1, c2), edit in self.ncci.items():
            if cpt in (c1, c2) and edit.modifier_indicator == "0":
                other = c2 if cpt == c1 else c1
                violations.append(f"NCCI: {cpt} bundled with {other} (modifier not allowed).")

        return AuditResult(
            claim_id=claim_id,
            patient_id_anon=patient_anon,
            billed_amount=billed,
            allowed_fmv=round(fmv, 2),
            variance_pct=round(variance, 2),
            risk_category=risk,
            nsa_violation=nsa_violation,
            violations=violations,
        )
