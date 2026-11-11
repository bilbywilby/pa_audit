"""NCCI Procedure-to-Procedure (PTP) edit parser."""
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class NCCIEdit:
    column1_code: str
    column2_code: str
    effective_date: str
    deletion_date: Optional[str]
    modifier_indicator: str


class NCCIParser:
    @staticmethod
    def load_ncci_ptp(file_path: Path) -> List[NCCIEdit]:
        edits: List[NCCIEdit] = []
        if not file_path.exists():
            return edits
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
            f.seek(0)
            delimiter = "\t" if "\t" in first_line else ","
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                if len(row) < 5:
                    continue
                if row[0].startswith("#") or row[0].lower().startswith("column"):
                    continue
                c1, c2 = row[0].strip(), row[1].strip()
                if not c1 or not c2:
                    continue
                edits.append(NCCIEdit(
                    column1_code=c1,
                    column2_code=c2,
                    effective_date=row[2].strip(),
                    deletion_date=row[3].strip() or None,
                    modifier_indicator=row[4].strip(),
                ))
        return edits
