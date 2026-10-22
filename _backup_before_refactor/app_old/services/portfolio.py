"""Portfolio sample shelf: explicitly captured, read-only results (rules unchanged from V6)."""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import urllib.parse
import uuid

from app.core.errors import MAX_JSON, ApiError
from app.repositories.portfolio import PortfolioRepository
from pf_engine import _safe_tree, validate_snapshot
from pf_persistence import PORTFOLIO_POLICY, portfolio_capture_tree


class PortfolioService:
    def __init__(self, repository: PortfolioRepository, secrets=(), *, bundled_entries=None, bundled_default_id=None):
        self.repository = repository
        self.secrets = tuple(s for s in secrets if s)
        self.bundled: dict[str, dict] = {}
        for item in bundled_entries or []:
            clean = self.checked(item)
            self.validate_item(clean, clean.get("id"))
            self.bundled[clean["id"]] = clean
        self.bundled_default_id = bundled_default_id if bundled_default_id in self.bundled else None

    def checked(self, value):
        # Drop only transport/private fields; keep rows, query status, coordinates and results.
        value = _safe_tree(portfolio_capture_tree(value))
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_JSON:
            raise ValueError("결과 파일이 64MB를 초과했습니다.")
        for secret in self.secrets:
            if secret in serialized or urllib.parse.quote(secret, safe="") in serialized:
                raise ValueError("인증키를 포함한 자료는 저장할 수 없습니다.")
        return value

    @staticmethod
    def check_id(ident):
        if not re.fullmatch(r"pf-sample-[a-f0-9]{32}", str(ident)):
            raise ValueError("저장한 분석 식별자가 올바르지 않습니다.")

    def validate_item(self, item, ident):
        self.check_id(ident)
        if (not isinstance(item, dict) or item.get("id") != ident or
                item.get("persistencePolicy") != PORTFOLIO_POLICY or
                item.get("readOnly") is not True or
                not isinstance(item.get("snapshot"), dict) or
                not isinstance(item["snapshot"].get("inputs"), dict) or
                not isinstance(item["snapshot"].get("results"), dict)):
            raise ValueError("저장한 분석의 형식이 올바르지 않습니다.")
        try:
            dt.datetime.fromisoformat(str(item.get("capturedAt")).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("저장 시각이 올바르지 않습니다.") from None
        # A newer engine is never run over a historical, validated capture.
        return item

    def save(self, body) -> dict:
        if not isinstance(body, dict) or not isinstance(body.get("snapshot"), dict):
            raise ValueError("저장할 분석 결과가 필요합니다.")
        clean = self.checked(body)
        candidate = clean["snapshot"]
        prior = candidate.get("results")
        validation = prior.get("validation") if isinstance(prior, dict) else None
        if isinstance(validation, dict) and validation.get("mode") == "browser-preview":
            # Browser totals are never trusted: recompute with the same partial mode as /api/analyze.
            validation["mode"] = "partial"
        snapshot = validate_snapshot(candidate)
        name = str(clean.get("name") or snapshot.get("name") or "저장한 분석").strip()
        if not name or len(name) > 120:
            raise ValueError("분석 이름은 1~120자로 입력하세요.")
        display = self._display_state(clean.get("displayState") or {})
        item = self.checked({
            "id": "pf-sample-" + uuid.uuid4().hex,
            "name": name,
            "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "readOnly": True,
            "persistencePolicy": PORTFOLIO_POLICY,
            "snapshot": snapshot,
            "displayState": display,
        })
        while self.repository.exists(item["id"]):
            item["id"] = "pf-sample-" + uuid.uuid4().hex
        self.repository.add(item)
        return {**item, "fileName": item["id"], "storage": "mysql"}

    @staticmethod
    def _display_state(display) -> dict:
        if not isinstance(display, dict):
            raise ValueError("화면 자료는 객체여야 합니다.")
        display = {key: display[key] for key in ("survey", "address", "viewState", "mapView") if key in display}
        if "address" in display and not isinstance(display["address"], str):
            raise ValueError("화면 주소는 문자열이어야 합니다.")
        if "survey" in display and display["survey"] is not None and not isinstance(display["survey"], dict):
            raise ValueError("입지 조사 자료는 객체여야 합니다.")
        if "viewState" in display:
            view = display["viewState"]
            if (not isinstance(view, dict) or view.get("main") not in ("finance", "survey") or
                    view.get("tab") not in ("parcels", "regulation", "location", "development")):
                raise ValueError("저장할 화면 탭이 올바르지 않습니다.")
            display["viewState"] = {key: view[key] for key in ("main", "tab")}
        if "mapView" in display:
            view = display["mapView"]
            limits = {"lon": (-180, 180), "lat": (-85.05112878, 85.05112878), "z": (0, 22)}
            if not isinstance(view, dict) or any(
                    not isinstance(view.get(key), (int, float)) or isinstance(view.get(key), bool) or
                    not math.isfinite(view[key]) or not low <= view[key] <= high
                    for key, (low, high) in limits.items()):
                raise ValueError("저장할 지도 위치가 올바르지 않습니다.")
            display["mapView"] = {key: view[key] for key in limits}
        return display

    def read(self, ident) -> dict:
        self.check_id(ident)
        stored = self.repository.get(ident)
        if stored is None:
            if ident in self.bundled:
                return self.checked(self.bundled[ident])
            raise ApiError("NOT_FOUND", "저장한 분석을 찾을 수 없습니다.", 404)
        return self.validate_item(self.checked(stored), ident)

    def default_id(self):
        ident = self.repository.get_default_id()
        if ident is None:
            return self.bundled_default_id
        try:
            self.read(ident)
            return ident
        except (ValueError, ApiError, KeyError, TypeError):
            # An invalid explicit pointer does not silently select another sample.
            return None

    def set_default(self, ident) -> dict:
        self.read(ident)
        self.repository.set_default_id(ident)
        return {"id": ident}

    def entries(self) -> list[dict]:
        items = dict(self.bundled)
        for raw in self.repository.list_all():
            try:
                item = self.validate_item(self.checked(raw), raw.get("id"))
                items[item["id"]] = item
            except (ValueError, KeyError, TypeError):
                continue
        return sorted(items.values(), key=lambda item: item["capturedAt"], reverse=True)

    def list(self) -> list[dict]:
        default_id = self.default_id()
        result = []
        for item in self.entries():
            try:
                snapshot = item["snapshot"]
                result.append({
                    "id": item["id"], "name": item["name"], "capturedAt": item["capturedAt"],
                    "readOnly": True, "persistencePolicy": PORTFOLIO_POLICY,
                    "isDefault": item["id"] == default_id,
                    "scenario": snapshot.get("scenario"),
                    "parcelCount": len(snapshot["inputs"].get("parcels", [])),
                    "areaM2": snapshot["results"].get("development", {}).get("landAreaM2"),
                })
            except (KeyError, TypeError):
                continue
        return result
