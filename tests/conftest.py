"""pytest fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

# project root on sys.path so `import brain` works without install
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
