"""Feature flags.

Al quitar un flag del registro, cualquier uso olvidado falla aquí.
"""

import re
from pathlib import Path

import pytest

from config import KNOWN_FEATURES, feature

ROOT = Path(__file__).resolve().parent.parent
USAGE = re.compile(r"""(?:\bfeature|\bhasFeature)\(\s*['"]([^'"]+)['"]""")


def test_unknown_feature_raises():
    with pytest.raises(KeyError):
        feature("no_existe")


def test_every_used_flag_is_registered():
    sources = [
        *(ROOT / "backend").rglob("*.py"),
        ROOT / "db" / "build_db.py",
        *(ROOT / "frontend" / "src").rglob("*.vue"),
        *(ROOT / "frontend" / "src").rglob("*.js"),
    ]
    used = {
        (path.relative_to(ROOT), name)
        for path in sources
        for name in USAGE.findall(path.read_text(encoding="utf-8"))
    }
    unknown = sorted((str(p), n) for p, n in used if n not in KNOWN_FEATURES)
    assert not unknown, f"flags usados sin registrar: {unknown}"


def test_features_endpoint_lists_only_known(client):
    r = client.get("/api/features")
    assert r.status_code == 200
    assert set(r.json()) <= set(KNOWN_FEATURES)
