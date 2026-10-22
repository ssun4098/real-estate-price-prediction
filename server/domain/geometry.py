"""Load geometry dependencies from the active Python environment only."""
from __future__ import annotations
import importlib


def load_geometry():
    try:
        return importlib.import_module('shapely'), importlib.import_module('pyproj')
    except ImportError:
        raise RuntimeError(
            '경계 계산 라이브러리가 없습니다. 프로젝트 폴더에서 '
            'python -m pip install -r requirements.txt 명령으로 설치하세요.'
        ) from None
