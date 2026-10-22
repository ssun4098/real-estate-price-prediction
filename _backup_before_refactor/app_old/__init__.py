"""V6 FastAPI application, split into layers.

    api (HTTP)  ->  services (use cases)  ->  repositories (MySQL)  ->  db (ORM)
                         |
                         +-> backend/ (existing analysis engine and public-data adapters)
                         +-> ml/      (pluggable trained model)

Each layer only imports the layer to its right. In particular, only
``repositories`` and ``db`` may import SQLAlchemy, and only ``api`` and
``core`` may import FastAPI.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The existing engine modules (pf_engine, pf_api, ...) use flat imports.
_backend = str(ROOT / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)
