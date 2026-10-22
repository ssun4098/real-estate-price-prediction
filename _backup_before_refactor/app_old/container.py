"""Composition root: the only place that wires settings, DB, repositories and services together."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.errors import set_secrets
from app.core.settings import Settings
from app.db.session import create_db_engine, init_schema, make_session_factory, ping_database, wait_for_database
from app.ml.registry import ModelRegistry
from app.repositories.land_trades import MySqlLandStore
from app.repositories.portfolio import PortfolioRepository
from app.repositories.snapshots import SnapshotRepository
from app.services.analysis import AnalysisService
from app.services.pages import PageService
from app.services.portfolio import PortfolioService
from app.services.prediction import PredictionService
from app.services.public_data import PublicDataService
from app.services.snapshots import SnapshotService
from pf_api import Collector


@dataclass
class Container:
    settings: Settings
    engine: object
    public_data: PublicDataService
    analysis: AnalysisService
    snapshots: SnapshotService
    portfolio: PortfolioService
    pages: PageService
    prediction: PredictionService

    def ping(self) -> None:
        ping_database(self.engine)

    def close(self) -> None:
        self.engine.dispose()
        self.public_data.collector.keys.clear()


def _bundled_samples(settings: Settings):
    entries = [json.loads(p.read_text("utf-8")) for p in sorted(settings.samples_dir.glob("pf-sample-*.json"))]
    default_file = settings.samples_dir / "default.json"
    default_id = json.loads(default_file.read_text("utf-8")).get("id") if default_file.is_file() else None
    return entries, default_id


def build_container(settings: Settings) -> Container:
    set_secrets(settings.secrets)

    engine = create_db_engine(settings.database_url)
    wait_for_database(engine, settings.db_connect_retries)
    init_schema(engine)
    sessions = make_session_factory(engine)

    collector = Collector(settings.keys, settings.vworld_domain)
    collector.land_store = MySqlLandStore(sessions, secrets=settings.secrets)

    bundled, bundled_default = _bundled_samples(settings)
    portfolio = PortfolioService(PortfolioRepository(sessions), settings.secrets,
                                 bundled_entries=bundled, bundled_default_id=bundled_default)

    registry = ModelRegistry(settings.model_dir, settings.model_entrypoint)
    registry.load()

    return Container(
        settings=settings,
        engine=engine,
        public_data=PublicDataService(collector),
        analysis=AnalysisService(),
        snapshots=SnapshotService(SnapshotRepository(sessions), settings.secrets),
        portfolio=portfolio,
        pages=PageService(settings.template_path.read_text("utf-8"), portfolio),
        prediction=PredictionService(registry),
    )
