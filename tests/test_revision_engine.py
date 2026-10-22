"""Regression fixtures for linked scale, integer dwellings and budget envelopes."""
import copy
import unittest

from pf_engine import analyze, validate_snapshot
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


class LinkedScaleTests(unittest.TestCase):
    def result(self, data=None):
        return analyze(data or revision_fixture(), partial=True)["results"]

    def test_exact_reference_scale_and_budget(self):
        result = self.result()
        dev, budget = result["development"], result["budget"]
        self.assertEqual((dev["landAreaM2"], dev["capacitySupplyAreaM2"], dev["units"]), (1000, 2000, 20))
        self.assertEqual((dev["assignedSupplyAreaM2"], dev["unassignedSupplyAreaM2"], dev["farAreaPerUnitM2"]), (2000, 0, 100))
        self.assertEqual(result["revenue"]["representativeWon"], 20_000_000_000)
        self.assertEqual((budget["allowableWon"], budget["allocatedWon"], budget["unallocatedWon"]), (17_000_000_000, 15_950_000_000, 1_050_000_000))
        self.assertEqual(budget["allocationPctTotal"], 75)
        self.assertEqual(budget["trustWon"], 200_000_000)

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
        self.assertEqual(result["budget"]["requestedAllowableWon"], 0)
        self.assertEqual(result["budget"]["allowableWon"], 12_000_000_000)
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
    def test_land_overallocation_lowers_target_without_changing_expense_settings(self):
        data = revision_fixture()
        data["comparables"]["landCases"][0]["priceManwon"] = 500000
        result = analyze(data, partial=True)["results"]
        budget = result["budget"]
        self.assertTrue(budget["complete"])
        self.assertEqual((budget["allocatedWon"], budget["overallocatedWon"]), (20_800_000_000, 0))
        self.assertEqual(budget["requestedTargetMarginPct"], 15)
        self.assertAlmostEqual(budget["appliedTargetMarginPct"], -4)
        self.assertEqual(budget["allocationRows"][0]["value"], 60)
        self.assertEqual(budget["status"], "지출 설정 유지 · 목표 수익률 조정")
        self.assertEqual(result["costs"]["totalWon"], 5_000_000_000)

    def test_margin_change_does_not_reduce_independent_costs(self):
        data = revision_fixture()
        base = analyze(data, partial=True)["results"]
        data["assumptions"]["targetMarginPct"] = 20
        changed = analyze(data, partial=True)["results"]
        self.assertEqual(base["costs"]["totalWon"], changed["costs"]["totalWon"])
        self.assertEqual(changed["budget"]["allowableWon"], 16_000_000_000)

    def test_unsupported_or_distribution_product_has_no_invented_fee(self):
        for choice in ("other", "distribution"):
            data = revision_fixture()
            data["budgetAllocation"]["trustType"] = choice
            budget = analyze(data, partial=True)["results"]["budget"]
            self.assertIsNone(budget["trustWon"])
            self.assertFalse(budget["complete"])
            self.assertIsNone(budget["allocatedWon"])
            self.assertEqual(budget["allowableWon"], 17_000_000_000)
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
        self.assertEqual(result["budget"]["allowableWon"], 17_000_000_000)
        self.assertTrue(result["budget"]["complete"])

    def test_bad_rate_preserves_other_rows_and_land(self):
        data = revision_fixture()
        data["budgetAllocation"]["constructionPct"] = 101
        result = analyze(data, partial=True)["results"]
        self.assertIsNone(result["budget"]["allocationRows"][0]["amountWon"])
        self.assertEqual(result["budget"]["allocationRows"][1]["amountWon"], 680_000_000)
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
        self.assertAlmostEqual(result["budget"]["allowableWon"] / 1e308, .85)
        self.assertAlmostEqual(result["budget"]["allocationRows"][0]["amountWon"] / 1e308, .51)
        for key in ("constructionPct", "indirectPct", "salesPct", "taxPct", "financePct"):
            data["budgetAllocation"][key] = 100
        result = analyze(data, partial=True)["results"]
        self.assertIsNone(result["budget"]["allocatedWon"])
        self.assertEqual(result["budget"]["knownAllocatedWon"], 1e306)
        self.assertEqual(result["budget"]["targetAdjustmentStatus"], "infeasible")
        self.assertTrue(all(row["amountWon"] is None for row in result["budget"]["allocationRows"]))
        self.assertTrue(result["budget"]["fieldErrors"])
        self.assertEqual(result["land"]["representativeWon"], 3_000_000_000)


if __name__ == "__main__":
    unittest.main()
