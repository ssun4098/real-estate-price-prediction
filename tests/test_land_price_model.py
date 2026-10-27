"""토지 단가 모델(data/models/land_price_model.py, land_price_inputs.py) 테스트.

그룹 이름 만들기·입력 자료 계산은 항상 검사한다. 실제 예측은 catboost 가 설치되어 있고
data/models/model.cbm 이 있을 때만 검사한다 (모델 파일은 git 에 없음).
"""
import importlib.util
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data" / "models"
sys.path.insert(0, str(ROOT))
if str(MODEL_DIR) not in sys.path:
    sys.path.append(str(MODEL_DIR))  # 서버(ModelHolder)가 하는 것과 같이 맨 뒤에 추가

import land_price_inputs  # noqa: E402
import land_price_model  # noqa: E402

HAVE_MODEL = importlib.util.find_spec("catboost") is not None and (MODEL_DIR / land_price_model.MODEL_FILE).is_file()

# 팀원 전달 자료 examples/expected_prediction.csv 의 첫 행 (11110|대|상업지역, 기준월 2026-09)
EXAMPLE_RAW = {"지가변동률": 0.446, "건축허가면적": 2559834.16, "경제심리지수_원계열": 97.9, "동행종합지수_전월비": 1.0,
               "M1_평잔_원계열": 1375941.4, "비은행_주택관련대출": 21841.6, "신규취급액기준_COFIX": 3.18}
EXAMPLE_HISTORY = (28532141.62942592, 6.5)
EXAMPLE_PRICE = 24361831.409772802


class LandGroupKeyTests(unittest.TestCase):
    def test_groups_like_teammate_table(self):
        key = land_price_model.land_group_key
        self.assertEqual(key("11110", "대", "제2종일반주거지역"), "11110|대|일반주거지역")
        self.assertEqual(key("11110", "대", "제1종전용주거지역"), "11110|대|전용주거지역")
        self.assertEqual(key("11110", "공장용지", "준공업지역"), "11110|공장용지|공업지역")
        self.assertEqual(key("41820", "도로", "자연녹지지역"), "41820|기타|녹지지역")
        self.assertEqual(key("41820", "임야", "계획관리지역"), "41820|임야|비도시지역")
        self.assertEqual(key("41820", "답", "농림지역"), "41820|답|비도시지역")
        self.assertEqual(key("11110", "대", "개발제한구역"), "11110|대|용도미지정 등")
        self.assertEqual(key("11110", "대", "용도미지정"), "11110|대|용도미지정 등")

    def test_unknown_names_are_rejected_not_guessed(self):
        for args in (("1111", "대", "상업지역"), ("11110", "", "상업지역"), ("11110", "대", ""), ("11110", "대", "완충녹지")):
            with self.assertRaises(ValueError):
                land_price_model.land_group_key(*args)

    def test_group_names_match_training_list(self):
        info = json.loads((MODEL_DIR / land_price_model.INFO_FILE).read_text(encoding="utf-8-sig"))
        groups = [g.split("|") for g in info["training_groups"]]
        self.assertEqual({g[1] for g in groups}, set(land_price_model.MAIN_JIMOK) | {land_price_model.OTHER_JIMOK})
        self.assertEqual({g[2] for g in groups}, set(land_price_model.ZONE_TABLE))


class InputBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = land_price_inputs.InputBuilder(MODEL_DIR)

    def test_latest_month_follows_cofix_coverage(self):
        # 지표는 2026-07 까지 → 기준월 2026-09 후보지만, COFIX 공시가 2026-08 까지라 2026-08
        self.assertEqual(str(self.builder.latest_month), "2026-08")

    def test_rebuilds_teammate_context_example(self):
        """팀원 examples/rebuilt_context.csv 와 같은 입력이 나와야 한다."""
        built = self.builder.build("11110|기타|상업지역", land_price_inputs.Month.parse("2026-05"))
        context = built["context"]
        self.assertEqual((context["featureMonth"], context["targetMonth"], context["cofixReleaseDate"]),
                         ("2026-03", "2026-11", "2026-05-15"))
        self.assertEqual(context["historyTradeCount"], 7)
        self.assertEqual(context["raw"], {"지가변동률": 0.396, "건축허가면적": 1282243.71, "경제심리지수_원계열": 94.0,
                                          "동행종합지수_전월비": 0.6, "M1_평잔_원계열": 1374894.6,
                                          "비은행_주택관련대출": 21490.1, "신규취급액기준_COFIX": 2.89})
        self.assertAlmostEqual(built["features"]["log_history_unit_price"], math.log1p(25158823.529411767))
        self.assertEqual(built["features"]["forecast_month_index"], 124.0)

    def test_missing_data_is_not_filled(self):
        with self.assertRaises(land_price_inputs.InputsMissing):
            self.builder.build("11110|대|일반주거지역", land_price_inputs.Month.parse("2026-09"))  # 지표 없음
        with self.assertRaises(land_price_inputs.InputsMissing):
            self.builder.build_latest("99999|대|상업지역")  # 거래 기록 없음


@unittest.skipUnless(HAVE_MODEL, "catboost 또는 data/models/model.cbm 없음")
class LandPricePredictorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.predictor = land_price_model.LandPricePredictor()
        cls.predictor.load(MODEL_DIR)

    def test_reproduces_teammate_example(self):
        features = land_price_inputs.model_features(EXAMPLE_RAW, *EXAMPLE_HISTORY, land_price_inputs.Month.parse("2026-09"))
        result = self.predictor.predict({**features, "land_group_key": "11110|대|상업지역"})
        self.assertAlmostEqual(result["unitPriceKrwPerM2"], EXAMPLE_PRICE, delta=1e-4)
        self.assertTrue(result["knownGroup"])

    def test_builds_inputs_from_group_only(self):
        result = self.predictor.predict({"sggCode": "11110", "jimok": "대", "landUse": "제2종일반주거지역"})
        self.assertEqual(result["landGroupKey"], "11110|대|일반주거지역")
        self.assertEqual(result["context"]["forecastMonth"], "2026-08")
        self.assertEqual(result["context"]["targetMonth"], "2027-02")
        self.assertGreater(result["unitPriceKrwPerM2"], 0)

    def test_missing_data_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self.predictor.predict({"land_group_key": "11110|대|일반주거지역", "forecastMonth": "2026-09"})

    def test_bad_input_raises_input_errors(self):
        with self.assertRaises(KeyError):
            self.predictor.predict({"forecastMonth": "2026-08"})
        with self.assertRaises(TypeError):
            features = land_price_inputs.model_features(EXAMPLE_RAW, *EXAMPLE_HISTORY, land_price_inputs.Month.parse("2026-09"))
            self.predictor.predict({**features, "지가변동률": "0.4", "land_group_key": "11110|대|상업지역"})


@unittest.skipUnless(HAVE_MODEL, "catboost 또는 data/models/model.cbm 없음")
class ModelApiTests(unittest.TestCase):
    """MODEL_ENTRYPOINT 로 켠 서버에서 /api/model/* 가 동작하는지."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from server.main import create_app
        from server.settings import Settings

        cls.directory = tempfile.TemporaryDirectory()
        cls.env = {"DATABASE_URL": "sqlite:///" + os.path.join(cls.directory.name, "t.db").replace("\\", "/"),
                   "MODEL_DIR": str(MODEL_DIR), "MODEL_ENTRYPOINT": "land_price_model:LandPricePredictor"}
        cls.saved = {k: os.environ.get(k) for k in cls.env}
        os.environ.update(cls.env)
        cls.client = TestClient(create_app(Settings.from_env()), base_url="http://127.0.0.1:4175")
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        for key, value in cls.saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
        cls.directory.cleanup()

    def test_status_reports_data_months(self):
        status = self.client.get("/api/model/status").json()
        self.assertEqual((status["state"], status["data"]["latestTargetMonth"]), ("ready", "2027-02"))

    def test_predict_and_error_codes(self):
        body = {"features": {"sggCode": "11110", "jimok": "대", "landUse": "일반상업지역"}}
        self.assertEqual(self.client.post("/api/model/predict", json=body).json()["result"]["landGroupKey"], "11110|대|상업지역")
        response = self.client.post("/api/model/predict", json={"features": {"forecastMonth": "2026-08"}})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (422, "INVALID_FEATURES"))
        response = self.client.post("/api/model/predict", json={"features": {"land_group_key": "99999|대|상업지역"}})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "MODEL_DATA_MISSING"))

    def test_land_estimate_sums_priced_parcels(self):
        parcels = [
            {"pnu": "1111010100100010000", "jimok": "대", "landUse": "제2종일반주거지역", "areaM2": 100},
            {"pnu": "1111010100100020000", "jimok": "대", "landUse": "제3종일반주거지역", "areaM2": 50},   # 같은 그룹
            {"pnu": "1111010100100030000", "jimok": "대", "landUse": "완충녹지", "areaM2": 10},            # 분류 불가
        ]
        result = self.client.post("/api/model/land-estimate", json={"parcels": parcels}).json()
        rows = result["rows"]
        self.assertEqual([r["status"] for r in rows], ["산출", "산출", "분류 불가"])
        self.assertAlmostEqual(rows[0]["unitPriceKrwPerM2"], rows[1]["unitPriceKrwPerM2"])
        self.assertIsNone(result["totalWon"])  # 하나라도 못 구하면 합계 없음
        self.assertAlmostEqual(result["partialWon"], rows[0]["unitPriceKrwPerM2"] * 150)
        self.assertEqual((result["pricedCount"], result["rowCount"], result["targetMonths"]), (2, 3, ["2027-02"]))

        full = self.client.post("/api/model/land-estimate", json={"parcels": parcels[:2]}).json()
        self.assertAlmostEqual(full["totalWon"], full["partialWon"])

    def test_land_estimate_rejects_bad_parcels(self):
        bad = {"parcels": [{"pnu": "123", "jimok": "대", "landUse": "상업지역", "areaM2": 10}]}
        self.assertEqual(self.client.post("/api/model/land-estimate", json=bad).status_code, 400)


if __name__ == "__main__":
    unittest.main()


class LandModelInAnalysisTests(unittest.TestCase):
    """분석(analyze)의 토지매입대금이 모델 금액으로 바뀌는지. 모델 파일 없이 가짜 모델 함수로 검사한다."""

    def test_combine_matches_screen_formula(self):
        # 화면 테스트(model-land-estimate.test.mjs)와 같은 숫자: 3억 + 평균 2백만 × 50㎡ = 4억
        from server.domain.analysis.land_price import combine_land_model
        m = combine_land_model([{"areaM2": 100, "unitPriceKrwPerM2": 1e6}, {"areaM2": 50, "unitPriceKrwPerM2": 4e6},
                                {"areaM2": 30}, {"areaM2": 20, "status": "분류 불가"}])
        self.assertEqual((m["totalWon"], m["pricedWon"], m["filledWon"], m["averageUnitPriceKrwPerM2"]), (4e8, 3e8, 1e8, 2e6))
        self.assertEqual([r["basis"] for r in m["rows"]], ["모델 예측", "모델 예측", "평균 단가로 채움", "평균 단가로 채움"])
        self.assertIsNone(combine_land_model([{"areaM2": 100}, {"areaM2": 50}]))
        self.assertIsNone(combine_land_model([{"areaM2": 100, "unitPriceKrwPerM2": 1e6}, {"areaM2": None}]))

    def _input(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from test_land_twelve import make_input
        data = make_input("제1종일반주거지역", "대")
        data["assumptions"]["landAdjustmentPct"] = 10
        data["financeEditor"] = {"land": {"mode": "comparablePct", "value": 100}}  # 수지분석 표의 '모델% 100'
        return data

    def test_model_amount_feeds_land_and_costs(self):
        from server.domain.analysis import analyze
        seen = []

        def fake_model(parcels):
            seen.extend(parcels)
            return {"rows": [{**p, "unitPriceKrwPerM2": 3e6, "status": "산출", "targetMonth": "2027-02"} for p in parcels]}

        plain = analyze(self._input(), partial=True)["results"]["land"]
        result = analyze(self._input(), partial=True, land_model=fake_model)["results"]
        land = result["land"]
        area = sum(p["areaM2"] for p in seen)
        self.assertEqual(seen[0]["jimok"], "대")
        self.assertEqual(land["amountBasis"], "model")
        self.assertAlmostEqual(land["representativeWon"], 3e6 * area * 1.1)          # 가격 보정 10% 포함
        self.assertAlmostEqual(land["comparableWon"], land["representativeWon"])      # 표의 '모델%' 기준
        self.assertEqual(land["comparablesRepresentativeWon"], plain["representativeWon"])  # 비교사례 금액은 따로 남김
        self.assertEqual(result["budget"]["landWon"], land["representativeWon"])        # 수지분석 표도 같은 금액

    def test_without_model_or_on_failure_comparables_are_used(self):
        from server.domain.analysis import analyze
        plain = analyze(self._input(), partial=True)["results"]["land"]
        self.assertEqual((plain["amountBasis"], plain["modelEstimate"]["used"]), ("comparables", False))

        def broken(parcels):
            raise RuntimeError("model down")
        land = analyze(self._input(), partial=True, land_model=broken)["results"]["land"]
        self.assertEqual(land["representativeWon"], plain["representativeWon"])
        self.assertEqual(land["amountBasis"], "comparables")
        none_priced = analyze(self._input(), partial=True, land_model=lambda ps: {"rows": [{**p, "status": "자료 없음"} for p in ps]})
        self.assertEqual(none_priced["results"]["land"]["representativeWon"], plain["representativeWon"])
