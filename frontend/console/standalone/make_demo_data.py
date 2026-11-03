"""분석 콘솔 '가상 데이터' 단독 HTML 에 넣을 자료를 만든다 (2026-11-03 요청).

서버를 띄우지 않고 서버와 같은 계산 코드를 직접 불러서 만든다:
- 기본 샘플(data/samples/default.json)을 현재 계산 규칙 + 토지가격 모델로 다시 계산한 결과
- 그 샘플의 토지 그룹 월별 단가(차트용), 시군구 지가변동률·COFIX
결과: frontend/console/standalone/demo-data.json.gz  (build-standalone.mjs 가 HTML 안에 넣는다)

실행 (프로젝트 폴더에서): python frontend/console/standalone/make_demo_data.py
필요: requirements.txt + 모델 파일 (data/models/linear/model.joblib)
"""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))  # 프로젝트 폴더의 server 패키지를 쓰기 위해 (이 스크립트는 server 밖에 있음)

from server.domain.analysis import analyze
from server.features.console import ModelInputs
from server.features.model import ModelHolder

SAMPLES = ROOT / "data" / "samples"
MODEL_DIR = ROOT / "data" / "models"
OUT = Path(__file__).with_name("demo-data.json.gz")


def main():
    default_id = json.loads((SAMPLES / "default.json").read_text(encoding="utf-8"))["id"]
    item = json.loads((SAMPLES / f"{default_id}.json").read_text(encoding="utf-8"))

    # 1) 현재 규칙·모델로 다시 계산 (서버 /api/analyze 와 같은 코드)
    model = ModelHolder(MODEL_DIR, "land_price_linear:LandPriceLinearPredictor")
    model.load()
    estimator = model.estimator()
    if estimator is None:
        raise SystemExit("토지가격 모델을 불러오지 못했습니다: " + json.dumps(model.info(), ensure_ascii=False))
    # 저장(export) 규칙은 지오코딩한 분양사례를 지우므로 쓰지 않고, /api/analyze 와 같은 analyze() 를 바로 쓴다
    old = item["snapshot"]
    snapshot = analyze(old["inputs"], partial=True, land_model=estimator)
    snapshot.update({k: old[k] for k in ("id", "createdAt", "name", "scenario") if k in old})

    # 2) 차트 자료: 샘플 시군구의 토지 그룹 월별 단가 + 지역 지표
    inputs = ModelInputs(MODEL_DIR / "inputs")
    sggs = sorted({str(p["pnu"])[:5] for p in snapshot["inputs"]["parcels"]})
    history = {}
    for sgg in sggs:
        for key, points in inputs.history(sgg).items():
            history[key] = [p for p in points if p[0] >= "2019-01"]
    indicators = {sgg: inputs.indicators(sgg) for sgg in sggs}

    demo = {
        "sample": {**item, "id": "demo-" + default_id, "name": item["name"] + " (가상 데이터)",
                   "snapshot": snapshot},
        "landHistory": history,
        "indicators": indicators,
        "model": {"name": model.info().get("name") or "토지가격 모델", "version": model.info().get("version")},
    }
    raw = json.dumps(demo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    OUT.write_bytes(gzip.compress(raw, 9))
    est = snapshot["results"]["land"].get("modelEstimate") or {}
    print(f"{OUT.name}: {len(raw)/1e6:.1f}MB → 압축 {OUT.stat().st_size/1e6:.1f}MB · 필지 {len(snapshot['inputs']['parcels'])} · "
          f"토지 그룹 {len(history)} · 모델 예측 행 {len(est.get('rows') or [])}")


if __name__ == "__main__":
    main()
