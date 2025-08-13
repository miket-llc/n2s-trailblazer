from typing import Optional
from sqlalchemy import text
from sqlalchemy.engine import create_engine
from .config import SETTINGS

_engine = None


def get_engine():
    global _engine
    if _engine is None and SETTINGS.TRAILBLAZER_DB_URL:
        _engine = create_engine(SETTINGS.TRAILBLAZER_DB_URL, future=True)
    return _engine


def ping() -> Optional[bool]:
    eng = get_engine()
    if not eng:
        return None
    with eng.connect() as c:
        c.execute(text("SELECT 1"))
    return True
