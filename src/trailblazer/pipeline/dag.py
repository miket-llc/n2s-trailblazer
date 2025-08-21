DEFAULT_PHASES: list[str] = [
    "ingest",
    "normalize",
    "enrich",
    "chunk",
    "classify",
    "embed",
    "retrieve",
    "compose",
    "create",
    "audit",
]


def validate_phases(phases: list[str]) -> list[str]:
    bad = [p for p in phases if p not in DEFAULT_PHASES]
    if bad:
        raise ValueError(f"Unknown phases: {bad}")
    return phases
