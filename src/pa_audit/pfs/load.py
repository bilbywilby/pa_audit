"""MPFS / fee schedule loader and FMV calculator."""
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass
class FeeScheduleItem:
    cpt_code: str
    description: str
    non_facility_price: float
    facility_price: float


class FeeScheduleLoader:
    @staticmethod
    def load_pfs_csv(file_path: Path) -> Dict[str, FeeScheduleItem]:
        pfs: Dict[str, FeeScheduleItem] = {}
        if not file_path.exists():
            return pfs
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                code = (row.get("cpt_code") or row.get("code") or "").strip()
                if not code:
                    continue
                pfs[code] = FeeScheduleItem(
                    cpt_code=code,
                    description=(row.get("description") or "").strip(),
                    non_facility_price=float(row.get("non_facility_price") or row.get("nf_price") or 0),
                    facility_price=float(row.get("facility_price") or row.get("f_price") or 0),
                )
        return pfs

    @staticmethod
    def load_pfs_json(file_path: Path) -> Dict[str, FeeScheduleItem]:
        if not file_path.exists():
            return {}
        data = json.loads(file_path.read_text())
        pfs: Dict[str, FeeScheduleItem] = {}
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            code = item.get("cpt_code", "").strip()
            if code:
                pfs[code] = FeeScheduleItem(
                    cpt_code=code,
                    description=item.get("description", ""),
                    non_facility_price=float(item.get("non_facility_price", 0)),
                    facility_price=float(item.get("facility_price", 0)),
                )
        return pfs

    @staticmethod
    def calculate_fmv(item: FeeScheduleItem, gpci: float = 1.0, is_facility: bool = False) -> float:
        base = item.facility_price if is_facility else item.non_facility_price
        return round(base * gpci, 2)
