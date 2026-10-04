"""
Pytest bootstrap for the FloodSight repository.

Why this file exists
--------------------
The test suite imports the first-party packages directly::

    from floodsight.alerts.engine import compute_alert_level
    from api.routers.forecast import get_grid_alerts

Neither ``floodsight`` nor ``api`` is an installed distribution — there is no
pyproject.toml or setup.py — so those imports only resolve when the repository
root happens to be on ``sys.path``. Pytest puts the *rootdir* on sys.path only
under the legacy "rootdir insertion" behaviour, which does not apply once the
tests live in a ``tests/`` directory without an ``__init__.py``. The result was
that every test failed at import time with::

    ModuleNotFoundError: No module named 'floodsight'

Pytest reports those as ordinary failures, so the suite looked "red for a while"
rather than "structurally unable to run", and nothing in CI executed it anyway.

This is the same defect class that silently disabled the CHEW health alerts:
``scripts/send_health_alerts.py`` was missing the equivalent
``sys.path.insert(...)`` and raised ModuleNotFoundError the moment a pilot LGA
reached Watch/Warning.

conftest.py is imported by pytest before collection begins, and pytest inserts
its directory (the rootdir) into sys.path automatically, so putting the path
fix here guarantees first-party imports resolve no matter which directory the
suite is invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repository root — the directory containing this file, i.e. the parent of
# both floodsight/ and api/.
ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    # insert(0) rather than append so the in-repo packages win over any
    # like-named package that may exist in site-packages.
    sys.path.insert(0, str(ROOT))
