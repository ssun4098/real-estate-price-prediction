"""External public-data access (VWorld, data.go.kr, Juso, KOSIS, SGIS) via the existing Collector."""
from __future__ import annotations

import datetime as dt
import threading
from contextlib import contextmanager

from app.core.errors import ApiError
from pf_api import Collector
from pf_survey import enrich_parcel, site_survey


class PublicDataService:
    def __init__(self, collector: Collector, jobs: int = 4):
        self.collector = collector
        self._jobs = threading.BoundedSemaphore(jobs)

    @contextmanager
    def _slot(self):
        # Upstream APIs are rate limited; refuse instead of queueing unbounded work.
        if not self._jobs.acquire(blocking=False):
            raise ApiError("BUSY", "다른 자료를 조회 중입니다. 잠시 후 다시 시도하세요.", 429)
        try:
            yield
        finally:
            self._jobs.release()

    def status(self, snapshot_storage: str) -> dict:
        c = self.collector
        info = c.status()
        info["version"] = "6.0.0"
        info["exportPolicy"] = "v5-geocoder-requery"
        info["jsonSaveDirectory"] = snapshot_storage
        info["apiStatus"].update({k: "준비" if c.keys.get(k) else "인증 미준비" for k in ("vworldGeocoder", "vworldSearch", "kosis")})
        info["apiStatus"]["sgis"] = "준비" if c.keys.get("sgisId") and c.keys.get("sgisSecret") else "서비스 ID·비밀값 확인 필요"
        return info

    def tile(self, z: int, y: int, x: int) -> bytes:
        return self.collector.tile(z, y, x)

    def parcels(self, bbox: str):
        with self._slot():
            return self.collector.parcels([float(v) for v in bbox.split(",")])

    def parcel(self, pnu: str, year: int | None, refresh: bool):
        year = year or dt.date.today().year
        with self._slot():
            return enrich_parcel(self.collector, self.collector.parcel(pnu, year, refresh=refresh), year)

    def boundary_allocation(self, pnu: str, year: int | None, refresh: bool):
        with self._slot():
            return self.collector.boundary_allocation(pnu, year or dt.date.today().year, refresh=refresh)

    def site_survey(self, query: dict):
        with self._slot():
            return site_survey(self.collector, query)

    def address(self, keyword: str):
        with self._slot():
            return self.collector.address(keyword, geocode=True)

    def regions(self, **kwargs):
        with self._slot():
            return self.collector.regions(**kwargs)

    def data_coverage(self):
        with self._slot():
            return self.collector.data_coverage()

    def land_cache(self, sgg: str | None):
        with self._slot():
            return self.collector.land_storage(sgg)

    def comparables(self, *args, **kwargs):
        with self._slot():
            return self.collector.comparables(*args, **kwargs)
