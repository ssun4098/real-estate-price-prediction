"""수지분석 지출 계산식 (2026-10-29): 화면(frontend/test-budget-priority.mjs)과 같은 예시로 서버 계산을 검사한다.

공사비 = 계획 공급면적 ÷ 3.3 × 평당 단가, 간접·분양·제세·금융 = 공사비 대비 %, 신탁 = 총수입 대비 %.
목표 수익률 = (총수입 − 총지출) ÷ 총수입 × 100.
"""
import json
import unittest
from pathlib import Path

from server.domain.analysis.costs import _budget_allocation

FIXTURES = json.loads((Path(__file__).resolve().parents[1] / "frontend" / "test-budget-priority-fixtures.json").read_text(encoding="utf-8"))


def close(test, actual, expected):
    if expected is None:
        test.assertIsNone(actual)
    else:
        test.assertAlmostEqual(actual, expected, delta=max(1e-6, abs(expected) * 1e-12))


class BudgetParityTests(unittest.TestCase):
    def test_same_results_as_screen(self):
        for f in FIXTURES:
            with self.subTest(f["name"]):
                data = {"assumptions": {}, "budgetAllocation": {"trustType": f["trustType"], "trustRatePct": 1},
                        "financeEditor": {"expenses": f["expenses"]}}
                r = _budget_allocation(data, {"representativeWon": f["revenue"]}, {"representativeWon": f["land"]}, [],
                                       {"supplyAreaM2": f["supply"]})
                e = f["expected"]
                self.assertEqual(r["complete"], e["complete"])
                self.assertEqual(r["targetAdjustmentStatus"], e["state"])
                close(self, r["totalExpenseWon"], e["total"])
                close(self, r["targetMarginPct"], e["margin"] if e["complete"] else None)
                if e["complete"]:
                    close(self, r["allocationRows"][0]["amountWon"], e["construction"])
                    close(self, f["land"] + sum(row["amountWon"] for row in r["allocationRows"]) + r["trustWon"], e["total"])
                if "constructionShown" in e:
                    close(self, r["allocationRows"][0]["amountWon"], e["constructionShown"])

    def test_old_target_and_old_shares_are_not_used(self):
        legacy = {"assumptions": {"targetMarginPct": 15},
                  "budgetAllocation": {"constructionPct": 60, "indirectPct": 4, "salesPct": 4, "taxPct": 3, "financePct": 4,
                                       "trustType": "", "trustRatePct": 1}}
        r = _budget_allocation(legacy, {"representativeWon": 1e10}, {"representativeWon": 2e9}, [], {"supplyAreaM2": 330})
        self.assertEqual([(row["mode"], row["value"]) for row in r["allocationRows"]],
                         [("areaUnit", 1000), ("constructionPct", 7), ("constructionPct", 6), ("constructionPct", 5), ("constructionPct", 6.5)])
        close(self, r["totalExpenseWon"], 3.345e9)
        close(self, r["targetMarginPct"], 1e10 / 3.345e9 * 100)


if __name__ == "__main__":
    unittest.main()
