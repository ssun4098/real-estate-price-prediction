"""Trust budget defaults and live calculation; contract cash flows stay separate."""
import copy
import unittest
from server.domain.analysis.costs import _budget_allocation
from server.domain.analysis import analyze
from test_revision_engine import revision_fixture


class TrustDefaultTests(unittest.TestCase):
    def test_unset_legacy_rate_defaults_without_selecting_product(self):
        for config in ({}, {'trustType': '', 'trustRatePct': None},
                       {'trustType': None, 'trustRatePct': ' '}):
            data = {'assumptions': {'targetMarginPct': 15}, 'budgetAllocation': config}
            before = copy.deepcopy(data)
            result = _budget_allocation(data, {'representativeWon': 1000}, {'representativeWon': 230}, [], {'supplyAreaM2': 0})
            self.assertEqual(result['trustWon'], 10)
            self.assertEqual(result['trustRatePct'], 1)
            self.assertEqual(result['trustType'], '')
            self.assertEqual(result['allowableWon'], 240)  # 공급면적 0 → 공사비 0: 토지 230 + 신탁 10
            self.assertAlmostEqual(result['targetMarginPct'], 1000 / 240 * 100 - 100)  # (수입 ÷ 지출 × 100) − 100
            self.assertTrue(result['complete'])
            self.assertEqual(data, before)

    def test_api_revenue_change_recalculates_fee_and_allocation(self):
        data = revision_fixture()
        data['budgetAllocation'].update(trustType='', trustRatePct=None)
        data['financeEditor'] = {'revenue': {'mode': 'amount', 'value': 1000},
                                 'land': {'mode': 'amount', 'value': 230}}
        before = analyze(data, partial=True)['results']['budget']
        data['financeEditor']['revenue']['value'] = 2000
        after = analyze(data, partial=True)['results']['budget']
        self.assertEqual(before['trustWon'], 10)
        self.assertEqual(after['trustWon'], 20)
        construction = 2000 / 3.3 * 1000 * 10_000
        self.assertAlmostEqual(after['allowableWon'] - before['allowableWon'], 10, delta=1)  # 수입이 늘면 신탁보수만 늘어난다
        self.assertAlmostEqual(after['allocatedWon'], 230 + 20 + construction * 1.245, delta=1)
        self.assertAlmostEqual(after['profitWon'], 2000 - after['allocatedWon'], delta=1)
        self.assertAlmostEqual(after['appliedTargetMarginPct'], 2000 / after['allocatedWon'] * 100 - 100, delta=2000 / after['allocatedWon'] * 100 * 1e-12)


if __name__ == '__main__':
    unittest.main()
