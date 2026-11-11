"""PA rating areas RA1-RA9 with PY2027 base multipliers."""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class RatingArea:
    code: str
    name: str
    counties: List[str]
    base_multiplier: float


PA_RATING_AREAS: Dict[str, RatingArea] = {
    "RA1": RatingArea("RA1", "Philadelphia", ["Philadelphia"], 1.15),
    "RA2": RatingArea("RA2", "Southeast Suburban", ["Bucks", "Chester", "Delaware", "Montgomery"], 1.10),
    "RA3": RatingArea("RA3", "Lehigh Valley", ["Lehigh", "Northampton"], 1.02),
    "RA4": RatingArea("RA4", "Central PA", ["Dauphin", "Huntingdon", "Mifflin", "Perry", "Union"], 0.98),
    "RA5": RatingArea("RA5", "Northeast", ["Lackawanna", "Lucerne", "Wyoming", "Susquehanna", "Pike"], 0.95),
    "RA6": RatingArea("RA6", "Lancaster / Southern", ["Lancaster", "Lebanon"], 0.97),
    "RA7": RatingArea("RA7", "Pittsburgh / Western", ["Allegheny", "Armstrong", "Butler", "Westmoreland"], 1.00),
    "RA8": RatingArea("RA8", "Erie / Northwest", ["Erie", "Cambria", "Jefferson", "Crawford"], 0.94),
    "RA9": RatingArea("RA9", "Rural / Northern Tier", ["Centre", "Clearfield", "Clinton", "Lycoming", "McKean", "Tioga"], 0.92),
}


def get_multiplier(ra_code: str) -> float:
    ra = PA_RATING_AREAS.get(ra_code.upper())
    if ra is None:
        raise KeyError(f"Unknown rating area: {ra_code}. Valid: {list(PA_RATING_AREAS.keys())}")
    return ra.base_multiplier
