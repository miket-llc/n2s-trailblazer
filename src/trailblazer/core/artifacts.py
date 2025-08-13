from datetime import datetime, timezone
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[3]  # repo root
RUNS = ROOT / "runs"


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"


def phase_dir(run_id: str, phase: str) -> Path:
    p = RUNS / run_id / phase
    p.mkdir(parents=True, exist_ok=True)
    return p
