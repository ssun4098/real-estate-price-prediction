"""Regression fixtures for linked scale, integer dwellings and budget envelopes."""
import copy
import unittest

from server.domain.analysis import analyze, validate_snapshot
from test_engine import fixture, add_boundary


def revision_fixture():
    data = fixture()
    data["parcels"][0]["areaM2"] = 1000
    add_boundary(data['parcels'][0])
    data["comparables"]["revenueCases"][0].update(supplyAreaM2=100, priceManwon=100000)
    data["comparables"]["landCases"][0].update(areaM2=1000, priceManwon=300000)
    data["assumptions"]["targetMarginPct"] = 15
    data["linkedScenario"] = {"enabled": True, "farDefaultPct": 200, "farMaxPct": 500,
                              "farPct": 200, "areaMode": "median", "supplyAreaM2": None}
    data["budgetAllocation"] = {"constructionPct": 60, "indirectPct": 4, "salesPct": 4,
                                "taxPct": 3, "financePct": 4, "trustType": "management",
                                "trustRatePct": 1}
    return data


# 수지분석 기본 계산식 (2026-10-29): 공사비 = 공급면적÷3.3×1,000만원, 간접 7%·분양 6%·제세 5%·금융 6.5% = 공사비 대비, 신탁 1% = 총수입 대비
def expected_budget(supply_m2, revenue, land, trust_pct=1):
    construction = supply_m2 / 3.3 * 1000 * 10_000
    total = land + construction * (1 + .07 + .06 + .05 + .065) + revenue * trust_pct / 100
    return construction, total, (revenue / total * 100 - 100 if revenue and total else None)


class LinkedScaleTests(unittest.TestCase):
    def result(self, data=None):
        return analyze(data or revision_fixture(), partial=True)["results"]

    def test_exact_reference_scale_and_budget(self):
        result = self.result()
        dev, budget = result["development"], result["budget"]
        self.assertEqual((dev["landAreaM2"], dev["capacitySupplyAreaM2"], dev["units"]), (1000, 2000, 20))
        self.assertEqual((dev["assignedSupplyAreaM2"], dev["unassignedSupplyAreaM2"], dev["farAreaPerUnitM2"]), (2000, 0, 100))
        self.assertEqual(result["revenue"]["representativeWon"], 20_000_000_000)
        construction, total, margin = expected_budget(2000, 20_000_000_000, 3_000_000_000)
        self.assertAlmostEqual(budget["allocationRows"][0]["amountWon"], construction, delta=1)
        self.assertAlmostEqual(budget["allocationRows"][1]["amountWon"], construction * .07, delta=1)
        self.assertAlmostEqual(budget["allocationRows"][4]["amountWon"], construction * .065, delta=1)
        self.assertAlmostEqual(budget["totalExpenseWon"], total, delta=1)
        self.assertAlmostEqual(budget["allocatedWon"], total, delta=1)
        self.assertEqual(budget["unallocatedWon"], 0)
        self.assertAlmostEqual(budget["targetMarginPct"], margin)
        self.assertAlmostEqual(budget["profitWon"], 20_000_000_000 - total, delta=1)
        self.assertIsNone(budget["allocationPctTotal"])
        self.assertEqual(budget["trustWon"], 200_000_000)
        self.assertTrue(budget["complete"])

    def test_integer_units_use_assigned_area(self):
        data = revision_fixture()
        data["linkedScenario"].update(areaMode="manual", supplyAreaM2=120)
        result = self.result(data)
        dev = result["development"]
        self.assertEqual((dev["units"], dev["supplyAreaM2"], dev["unassignedSupplyAreaM2"], dev["farAreaPerUnitM2"]), (16, 1920, 80, 125))
        self.assertEqual(result["revenue"]["representativeWon"], 19_200_000_000)
        self.assertEqual(result["budget"]["revenueWon"], 19_200_000_000)

    def test_round_half_up_then_enforce_capacity(self):
        for capacity, unit_area, expected in ((250, 100, 2), (200, 100, 2), (99, 100, 0), (300, .1, 3000), (.3, .1, 3)):
            with self.subTest(capacity=capacity, unit_area=unit_area):
                data = revision_fixture()
                data["parcels"][0]["areaM2"] = capacity
                data["linkedScenario"].update(farPct=100, areaMode="manual", supplyAreaM2=unit_area)
                dev = self.result(data)["development"]
                self.assertEqual(dev["units"], expected)
                self.assertLessEqual(dev["assignedSupplyAreaM2"], capacity + max(1e-8, capacity * 1e-12))

    def test_zero_far_has_zero_units_not_missing(self):
        data = revision_fixture()
        data["linkedScenario"]["farPct"] = 0
        result = self.result(data)
        self.assertEqual(result["development"]["units"], 0)
        self.assertIsNone(result["development"]["farAreaPerUnitM2"])
        self.assertEqual(result["revenue"]["representativeWon"], 0)
        self.assertEqual(result["budget"]["allowableWon"], 3_000_000_000)  # 공급면적 0 → 공사비 0, 남는 건 토지비
        self.assertEqual(result["budget"]["overallocatedWon"], 0)
        self.assertIsNone(result["budget"]["appliedTargetMarginPct"])
        self.assertEqual(result["budget"]["targetAdjustmentStatus"], "zero-revenue")

    def test_changes_scale_not_land(self):
        data = revision_fixture()
        data["linkedScenario"]["farPct"] = 300
        result = self.result(data)
        self.assertEqual(result["revenue"]["representativeWon"], 30_000_000_000)
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)

    def test_missing_area_and_invalid_default_suspend_only_dependents(self):
        for key, value in (("farDefaultPct", 600), ("farPct", 501), ("farMaxPct", 0), ("farPct", "bad")):
            with self.subTest(key=key):
                data = revision_fixture()
                data["linkedScenario"][key] = value
                result = self.result(data)
                self.assertIsNone(result["development"]["supplyAreaM2"])
                self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)
                self.assertTrue(result["linkedScenario"]["fieldErrors"])
                self.assertIn("→", result["linkedScenario"]["fieldErrors"][0]["message"])

    def test_duplicate_parcel_counted_once(self):
        data = revision_fixture()
        data["parcels"].append(copy.deepcopy(data["parcels"][0]))
        self.assertEqual(self.result(data)["development"]["capacitySupplyAreaM2"], 2000)

    def test_capacity_survives_missing_supply_sample_but_units_stay_unknown(self):
        data = revision_fixture()
        data["comparables"]["revenueCases"] = []
        result = self.result(data)
        dev = result["development"]
        self.assertEqual(dev["capacitySupplyAreaM2"], 2000)
        self.assertIsNone(dev["units"])
        self.assertIsNone(dev["assignedSupplyAreaM2"])
        self.assertEqual(dev["areaStats"]["n"], 0)
        self.assertIsNone(result["revenue"]["representativeWon"])

    def test_capacity_survives_invalid_manual_unit_area(self):
        data = revision_fixture()
        data["linkedScenario"].update(areaMode="manual", supplyAreaM2=0)
        dev = self.result(data)["development"]
        self.assertEqual(dev["capacitySupplyAreaM2"], 2000)
        self.assertIsNone(dev["units"])

    def test_preserve_manual_plan_and_ignore_its_invalid_fields_while_linked(self):
        data = revision_fixture()
        data["unitPlan"][0]["units"] = "invalid draft"
        original = copy.deepcopy(data)
        snapshot = analyze(data, partial=True)
        self.assertEqual(data, original)
        self.assertEqual(snapshot["inputs"]["unitPlan"], original["unitPlan"])
        self.assertEqual(snapshot["results"]["development"]["units"], 20)
        self.assertFalse(any(e["path"].startswith("unitPlan") for e in snapshot["results"]["validation"]["fieldErrors"]))

    def test_legacy_stays_manual(self):
        data = fixture()
        result = self.result(data)
        self.assertFalse(result["development"]["linkedMode"])
        self.assertEqual(result["development"]["supplyAreaM2"], 1000)
        self.assertIsNone(result["budget"])

    def test_area_statistics_equal_complex_weights_and_same_eligible_cases(self):
        data = revision_fixture()
        case = data["comparables"]["revenueCases"][0]
        data["comparables"]["revenueCases"].extend([
            dict(case, id="m2", modelNo="m2", supplyAreaM2=200, priceManwon=200000),
            dict(case, id="h2", houseManageNo="h2", supplyAreaM2=50, priceManwon=50000),
            dict(case, id="excluded", houseManageNo="h3", supplyAreaM2=500, eligible=False),
            dict(case, id="bad-price", houseManageNo="h4", supplyAreaM2=600, priceManwon=None),
        ])
        result = self.result(data)
        self.assertEqual([p["valueM2"] for p in result["development"]["areaPoints"]], [150, 50])
        self.assertEqual(result["development"]["areaStats"]["median"], 100)
        self.assertEqual(result["development"]["unitSupplyAreaM2"], 100)
        self.assertEqual(result["revenue"]["supplyAreaStats"]["n"], 2)
        self.assertEqual(result["revenue"]["eligibleComplexes"], result["revenue"]["points"])
        self.assertFalse(result["development"]["areaStats"]["showBox"])

    def test_no_cases_keep_land_and_manual_area_can_still_compute_scale(self):
        data = revision_fixture()
        data["comparables"]["revenueCases"] = []
        result = self.result(data)
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)
        self.assertIsNone(result["development"]["units"])
        self.assertIsNone(result["budget"]["allowableWon"])
        data["linkedScenario"].update(areaMode="manual", supplyAreaM2=100)
        result = self.result(data)
        self.assertEqual(result["development"]["units"], 20)
        self.assertIsNone(result["revenue"]["representativeWon"])

    def test_snapshot_round_trip_keeps_linked_settings_and_original_rows(self):
        original = analyze(revision_fixture(), partial=True)
        result = validate_snapshot(original)
        self.assertEqual(result["inputs"], original["inputs"])
        self.assertEqual(result["results"], original["results"])

    def test_extreme_far_overflow_is_field_error_and_keeps_land(self):
        data = revision_fixture()
        data["linkedScenario"].update(farPct=1e308, farMaxPct=1e308)
        result = self.result(data)
        self.assertIsNone(result["development"]["capacitySupplyAreaM2"])
        self.assertIsNone(result["development"]["units"])
        self.assertIsNone(result["revenue"]["representativeWon"])
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)
        self.assertTrue(any(e["path"] == "linkedScenario.farPct" for e in result["linkedScenario"]["fieldErrors"]))

    def test_unsafe_integer_count_is_field_error(self):
        data = revision_fixture()
        data["linkedScenario"].update(areaMode="manual", supplyAreaM2=1e-30)
        result = self.result(data)
        self.assertIsNone(result["development"]["units"])
        self.assertTrue(result["linkedScenario"]["fieldErrors"])
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)

    def test_revenue_product_overflow_does_not_drop_only_expensive_cases(self):
        data = revision_fixture()
        data["linkedScenario"].update(farPct=1e8, farMaxPct=1e8)
        data["comparables"]["revenueCases"].append(dict(data["comparables"]["revenueCases"][0],
                                                        id="huge", houseManageNo="huge", priceManwon=1e298))
        result = self.result(data)
        self.assertEqual(result["development"]["units"], 10_000_000)
        self.assertIsNone(result["revenue"]["representativeWon"])
        self.assertEqual(len(result["revenue"]["points"]), 2)
        self.assertTrue(all(p["valueWon"] is None for p in result["revenue"]["points"]))
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)
        self.assertTrue(any(e["section"] == "revenue" for e in result["validation"]["fieldErrors"]))


class BudgetEnvelopeTests(unittest.TestCase):
    def test_large_land_makes_target_negative_without_changing_expense_settings(self):
        data = revision_fixture()
        data["comparables"]["landCases"][0]["priceManwon"] = 2_000_000  # 토지비 200억 = 총수입과 같음
        result = analyze(data, partial=True)["results"]
        budget = result["budget"]
        self.assertTrue(budget["complete"])
        construction, total, margin = expected_budget(2000, 20_000_000_000, 20_000_000_000)
        self.assertAlmostEqual(budget["allocatedWon"], total, delta=1)
        self.assertLess(budget["targetMarginPct"], 0)  # (수입 ÷ 지출 × 100) − 100: 음수 = 적자
        self.assertAlmostEqual(budget["appliedTargetMarginPct"], margin)
        self.assertEqual((budget["allocationRows"][0]["mode"], budget["allocationRows"][0]["value"]), ("areaUnit", 1000))
        self.assertAlmostEqual(budget["allocationRows"][0]["amountWon"], construction, delta=1)
        self.assertEqual(budget["status"], "수지 계산 완료 · 목표 수익률 자동 산정")
        self.assertEqual(result["costs"]["totalWon"], 20_000_000_000)

    def test_margin_change_does_not_reduce_independent_costs(self):
        data = revision_fixture()
        base = analyze(data, partial=True)["results"]
        data["assumptions"]["targetMarginPct"] = 20  # 예전 입력값은 수지분석에 쓰지 않는다
        changed = analyze(data, partial=True)["results"]
        self.assertEqual(base["costs"]["totalWon"], changed["costs"]["totalWon"])
        self.assertEqual(base["budget"]["totalExpenseWon"], changed["budget"]["totalExpenseWon"])
        self.assertEqual(base["budget"]["targetMarginPct"], changed["budget"]["targetMarginPct"])

    def test_unsupported_or_distribution_product_has_no_invented_fee(self):
        for choice in ("other", "distribution"):
            data = revision_fixture()
            data["budgetAllocation"]["trustType"] = choice
            budget = analyze(data, partial=True)["results"]["budget"]
            self.assertIsNone(budget["trustWon"])
            self.assertFalse(budget["complete"])
            self.assertIsNone(budget["allocatedWon"])
            self.assertIsNone(budget["targetMarginPct"])
            self.assertAlmostEqual(budget["allocationRows"][0]["amountWon"], expected_budget(2000, 1, 0)[0], delta=1)
            self.assertTrue(budget["fieldErrors"])

    def test_completion_rate_and_user_override(self):
        data = revision_fixture()
        data["budgetAllocation"]["trustType"] = "completion"
        data["budgetAllocation"]["trustRatePct"] = 2
        self.assertEqual(analyze(data)["results"]["budget"]["trustWon"], 400_000_000)
        data["budgetAllocation"]["trustRatePct"] = 1.5
        self.assertEqual(analyze(data)["results"]["budget"]["trustWon"], 300_000_000)

    def test_explicitly_cleared_trust_editor_is_not_silently_restored(self):
        for missing in (None, "", "absent"):
            data = revision_fixture()
            if missing == "absent":
                data["financeEditor"] = {"expenses": {"trust": {"mode": "revenuePct"}}}
            else:
                data["financeEditor"] = {"expenses": {"trust": {"mode": "revenuePct", "value": missing}}}
            result = analyze(data, partial=True)["results"]
            budget = result["budget"]
            self.assertIsNone(budget["trustRatePct"])
            self.assertIsNone(budget["trustWon"])
            self.assertFalse(budget["complete"])
            self.assertTrue(any(e["path"] == "financeEditor.expenses.trust.value" for e in budget["fieldErrors"]))
            self.assertEqual(result["revenue"]["representativeWon"], 20_000_000_000)
            self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)

    def test_cashflow_error_does_not_clear_valid_linked_revenue_and_budget(self):
        data = revision_fixture()
        data["cashflow"] = {"openingCashWon": "not a number"}
        result = analyze(data, partial=True)["results"]
        self.assertTrue(any(e["section"] == "cashflow" for e in result["validation"]["fieldErrors"]))
        self.assertEqual(result["revenue"]["representativeWon"], 20_000_000_000)
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)
        self.assertAlmostEqual(result["budget"]["allowableWon"], expected_budget(2000, 20_000_000_000, 3_000_000_000)[1], delta=1)
        self.assertTrue(result["budget"]["complete"])

    def test_bad_rate_preserves_other_rows_and_land(self):
        data = revision_fixture()
        data["financeEditor"] = {"expenses": {"indirect": {"mode": "constructionPct", "value": 101}}}
        result = analyze(data, partial=True)["results"]
        construction = expected_budget(2000, 1, 0)[0]
        self.assertIsNone(result["budget"]["allocationRows"][1]["amountWon"])
        self.assertAlmostEqual(result["budget"]["allocationRows"][0]["amountWon"], construction, delta=1)
        self.assertAlmostEqual(result["budget"]["allocationRows"][2]["amountWon"], construction * .06, delta=1)
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)
        self.assertFalse(result["budget"]["complete"])

    def test_allowance_uses_potential_while_actual_cost_margin_uses_net(self):
        data = revision_fixture()
        data["assumptions"].update(finalSalesPct=80, discountPct=10)
        result = analyze(data, partial=True)["results"]
        self.assertEqual(result["budget"]["revenueWon"], 20_000_000_000)
        self.assertEqual(result["revenue"]["netRevenueWon"], 14_400_000_000)
        self.assertEqual(result["costs"]["allowableWon"], 12_240_000_000)

    def test_large_finite_amounts_avoid_intermediate_overflow(self):
        data = revision_fixture()
        data["comparables"]["revenueCases"][0]["priceManwon"] = 5e302
        result = analyze(data, partial=True)["results"]
        self.assertAlmostEqual(result["revenue"]["representativeWon"] / 1e308, 1)
        self.assertTrue(result["budget"]["complete"])
        self.assertAlmostEqual(result["budget"]["allowableWon"] / 1e306, 1)  # 신탁 1%가 대부분
        self.assertAlmostEqual(result["budget"]["targetMarginPct"] / 9_900, 1)  # (수입 ÷ 지출(≈신탁 1%) × 100) − 100
        data["financeEditor"] = {"expenses": {key: {"mode": "budgetPct", "value": 100}
                                              for key in ("construction", "indirect", "sales", "tax", "finance")}}
        result = analyze(data, partial=True)["results"]
        self.assertIsNone(result["budget"]["allocatedWon"])
        self.assertEqual(result["budget"]["targetAdjustmentStatus"], "infeasible")
        self.assertTrue(all(row["amountWon"] is None for row in result["budget"]["allocationRows"]))
        self.assertTrue(result["budget"]["fieldErrors"])
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)


if __name__ == "__main__":
    unittest.main()
