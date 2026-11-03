"""Windows bootstrap: SETUP/START/STOP, wizard, AVD, secret store.

Real Windows install verification must run on Windows — Linux pytest only
covers logic/unit paths and must not be treated as install proof.
"""

from __future__ import annotations

import sys


def is_windows() -> bool:
    return sys.platform.startswith("win")
