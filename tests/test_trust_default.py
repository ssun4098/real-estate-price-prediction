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
            result = _budget_allocation(data, {'representativeWon': 1000}, {'representativeWon': 230}, [])
            self.assertEqual(result['trustWon'], 10)
            self.assertEqual(result['trustRatePct'], 1)
            self.assertEqual(result['trustType'], '')
            self.assertEqual(result['allowableWon'], 960)
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
        self.assertEqual(before['allowableWon'], 960)
        self.assertEqual(after['allowableWon'], 1700)
        self.assertEqual(after['allocatedWon'], 1525)
        self.assertEqual(after['profitWon'], 475)
        self.assertEqual(after['appliedTargetMarginPct'], 15)


if __name__ == '__main__':
    unittest.main()
