import os
import tempfile

import pytest

# DATA_DIR is read once at import time; point it at an isolated temp DB before importing app.
_TMP = tempfile.mkdtemp(prefix="pricecab-test-")
os.environ["DATA_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import connect  # noqa: E402


@pytest.fixture()
def client():
    # Fresh schema per test: remove the DB file so seed_if_empty rebuilds it.
    from app.config import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()
    # Re-run seeding explicitly (module import only happens once).
    from app.seed import seed_if_empty

    seed_if_empty()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def conn():
    c = connect()
    try:
        yield c
    finally:
        c.close()
