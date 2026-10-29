import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
# This package, plus the Environment Protocol v0 reference
# implementation (DavidFox998/soph-e-runway). The Alexa build is a
# second tenant + household layer ON that environment, not a fork
# of it. Locate the runway package: $RUNWAY_SRC, or a sibling clone
# named soph-e-runway (or soph-e-runway-ref in the home workspace).
sys.path.insert(0, str(ROOT / "src"))

_candidates = [
    os.environ.get("RUNWAY_SRC"),
    ROOT.parent / "soph-e-runway" / "src",
    ROOT.parent / "soph-e-runway-ref" / "src",
]
for _c in _candidates:
    if _c and (Path(_c) / "runway").exists():
        sys.path.insert(0, str(_c))
        break
else:
    raise RuntimeError(
        "runway package not found: clone DavidFox998/soph-e-runway "
        "alongside this repo, or set RUNWAY_SRC to its src/ directory")
