from typing import List

DEFAULT_PHASES: List[str] = [
    "ingest",
    "normalize",
    "enrich",
    "classify",
    "embed",
    "retrieve",
    "compose",
    "create",
    "audit",
]


def validate_phases(phases: List[str]) -> List[str]:
    bad = [p for p in phases if p not in DEFAULT_PHASES]
    if bad:
        raise ValueError(f"Unknown phases: {bad}")
    return phases
