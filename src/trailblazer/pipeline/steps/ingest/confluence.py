from pathlib import Path
from ....core.logging import log


def ingest_confluence_minimal(outdir: str) -> None:
    """
    Minimal placeholder that writes an empty NDJSON to prove pathing works.
    """
    p = Path(outdir) / "confluence.ndjson"
    p.write_text("", encoding="utf-8")
    log.info("ingest.confluence.wrote", file=str(p))
