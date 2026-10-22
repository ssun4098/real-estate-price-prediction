"""Calculation fixtures, not project defaults. Run: python -m unittest -v test_engine."""
import copy
import unittest

from server.domain.engine import analyze, calculate_cashflow, statistics, validate_snapshot, COST_LABELS
from test_boundary_fixture import add_boundary


def parcel_evidence(zone="제3종일반주거지역", jimok="대"):
    """Synthetic current-source evidence for V3 classification regressions."""
    return {"landRegister": {"status": "호출 확인", "rows": [{"lndcgrCodeNm": jimok}]},
            "landUse": {"status": "호출 확인", "rows": [{"prposAreaDstrcCodeNm": zone, "cnflcAt": "1", "cnflcAtNm": "포함"}]}}


def fixture():
    data = {
        "project": {"name": "계산 검증용", "asOf": "2026-01-01"},
        "parcels": [{"pnu": "1165010800100010001", "areaM2": 100, "group": "기본", "attributes": parcel_evidence()}],
        "unitPlan": [{"id": "A", "units": 10, "supplyAreaM2": 100, "farAreaM2": 80}],
        "comparables": {
            "revenueCases": [{"id": "r1", "houseManageNo": "h1", "announcementNo": "a1", "modelNo": "m1", "supplyAreaM2": 100, "priceManwon": 50000}],
            "landCases": [{"id": "l1", "areaM2": 100, "priceManwon": 10000, "group": "기본", "jimok": "대", "landUse": "제3종일반주거지역", "cancelled": False, "shareTrade": False}]},
        "assumptions": {"targetMarginPct": 10},
        "costs": [{"id": k, "amountWon": 0, "sourceStatus": "사용자 가정"} for k in COST_LABELS if k != "land_purchase"],
    }
    for parcel in data['parcels']: add_boundary(parcel)
    return data


def cash_fixture():
    return {"asOf": "2026-01-01", "startDate": "2026-01-01", "endDate": "2026-12-31",
            "openingCashWon": 0, "openingDebtWon": 0, "loanLimitWon": 1000,
            "annualRatePct": 0, "maturityDate": "2026-06-30", "financingConfirmed": True,
            "autoDraw": True, "scheduleComplete": True, "financeComplete": True,
            "trust": {"notApplicable": True}, "events": []}


class StatisticsTests(unittest.TestCase):
    def test_spec_example(self):
        s = statistics([10, 20, 30, 40, 100])
        self.assertEqual((s['q1'], s['median'], s['q3'], s['mean']), (20, 30, 40, 40))
        self.assertEqual((s['whiskerLow'], s['whiskerHigh'], s['outliers']), (10, 40, [100]))
        self.assertTrue(s['showBox'])

    def test_empty_small_and_identical(self):
        self.assertIsNone(statistics([])['median'])
        for n in (1, 4):
            self.assertFalse(statistics([3] * n)['showBox'])
        s = statistics([7] * 5)
        self.assertEqual((s['q1'], s['q3'], s['whiskerLow'], s['whiskerHigh']), (7, 7, 7, 7))

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            statistics([float('nan')])


class AnalysisTests(unittest.TestCase):
    def test_units_50_eok(self):
        r = analyze(fixture())['results']
        self.assertEqual(r['revenue']['representativeWon'], 5_000_000_000)
        self.assertEqual(r['land']['representativeWon'], 100_000_000)
        self.assertEqual(r['costs']['totalWon'], 100_000_000)

    def test_complex_median_fixed_mean_changes_only_between(self):
        f = fixture()
        cases = f['comparables']['revenueCases']
        for i, price in enumerate((50000, 200000)):
            cases.append(dict(cases[0], id=f'a{i}', modelNo=f'm{i+2}', priceManwon=price))
        cases.append(dict(cases[0], id='b1', houseManageNo='h2', priceManwon=200000))
        f['assumptions']['revenueMethod'] = 'mean'
        r = analyze(f)['results']['revenue']
        self.assertEqual(len(r['points']), 2)
        self.assertEqual(r['points'][0]['unitPriceWonM2'], 5_000_000)
        self.assertEqual(r['representativeWon'], 12_500_000_000)

    def test_multiple_announcements_require_resolution(self):
        f = fixture()
        f['comparables']['revenueCases'].append(dict(f['comparables']['revenueCases'][0], id='r2', announcementNo='new'))
        self.assertIsNone(analyze(f)['results']['revenue']['representativeWon'])
        f['comparables']['revenueCases'][1]['representativeAnnouncement'] = True
        self.assertEqual(len(analyze(f)['results']['revenue']['points']), 1)

    def test_parcel_dedup_missing_area_and_no_far_autoplan(self):
        f = fixture()
        f['parcels'].append(copy.deepcopy(f['parcels'][0]))
        f['assumptions'].update(farPct=100, farBaseAreaM2=100)
        r = analyze(f)['results']
        self.assertEqual(r['development']['landAreaM2'], 100)
        self.assertEqual(r['development']['supplyAreaM2'], 1000)
        self.assertEqual(r['development']['status'], '제약 위반')
        f['parcels'].append({'pnu': 'missing', 'areaM2': None})
        self.assertIsNone(analyze(f)['results']['land']['representativeWon'])

    def test_land_groups_are_not_joint_distribution(self):
        f = fixture()
        f['parcels'].append({'pnu': '1165010800100010002', 'areaM2': 200, 'group': 'B', 'attributes': parcel_evidence('일반상업지역')})
        add_boundary(f['parcels'][-1])
        f['comparables']['landCases'].extend([
            {'id': 'b', 'areaM2': 100, 'priceManwon': 20000, 'group': 'B', 'landUse': '일반상업지역', 'jimok': '대'},
            {'id': 'c', 'areaM2': 100, 'priceManwon': 90000, 'group': 'B', 'cancelled': True},
            {'id': 's', 'areaM2': 100, 'priceManwon': 90000, 'group': 'B', 'shareTrade': True}])
        land = analyze(f)['results']['land']
        self.assertEqual(land['representativeWon'], 500_000_000)
        self.assertEqual(len(land['groups']), 2)
        self.assertNotIn('stats', land)
        self.assertEqual(len(land['excluded']), 2)

    def test_target_changes_allowable_not_costs(self):
        f = fixture()
        before = analyze(f)['results']['costs']
        f['assumptions']['targetMarginPct'] = 15
        after = analyze(f)['results']['costs']
        self.assertEqual(before['totalWon'], after['totalWon'])
        self.assertEqual(before['marginPct'], after['marginPct'])
        self.assertGreater(before['allowableWon'], after['allowableWon'])

    def test_missing_is_not_zero(self):
        f = fixture()
        f['costs'] = []
        r = analyze(f)['results']['costs']
        self.assertIsNone(r['totalWon'])
        self.assertIsNone(r['marginPct'])
        self.assertGreater(r['knownSubtotalWon'], 0)

    def test_partial_collection_cannot_become_complete_by_eligible_override(self):
        f = fixture()
        f['collectionStatus'] = 'partial'
        for rows in f['comparables'].values():
            for row in rows:
                row['eligible'] = True
        r = analyze(f)['results']
        self.assertIsNone(r['revenue']['representativeWon'])
        self.assertIsNone(r['land']['representativeWon'])
        self.assertIsNone(r['costs']['allowableWon'])
        self.assertEqual(r['revenue']['status'], '부분 수집 · 판정 보류')
        f.pop('collectionStatus')
        f['sources'] = [{'id':'land', 'collectionStatus':'partial'}]
        self.assertIsNone(analyze(f)['results']['land']['representativeWon'])

    def test_one_failed_dataset_does_not_hide_other_confirmed_complete_dataset(self):
        f = fixture()
        f['collectionStatus'] = 'partial'
        f['sources'] = [{'id':'applyhome', 'collectionStatus':'partial'}, {'id':'land', 'collectionStatus':'complete'}]
        r = analyze(f)['results']
        self.assertIsNone(r['revenue']['representativeWon'])
        self.assertEqual(r['land']['representativeWon'],100_000_000)
        self.assertIsNone(r['costs']['marginPct'])

    def test_adjustment_and_mean_leave_box_definition(self):
        f = fixture()
        f['assumptions']['revenueAdjustmentPct'] = 10
        r = analyze(f)['results']['revenue']
        self.assertAlmostEqual(r['representativeWon'], 5_500_000_000)
        self.assertEqual(r['baseStats']['median'], 5_000_000_000)
        f['assumptions']['revenueAdjustmentPct'] = -100
        with self.assertRaises(ValueError):
            analyze(f)

    def test_no_confirmed_okr_uses_universal_goals(self):
        f = fixture()
        f['okr'] = {'targetsConfirmed': False, 'targets': {'unsold6Pct': 20}, 'actuals': {'unsold6Pct': 15}}
        r = analyze(f)['results']['okr']['rows'][0]
        self.assertIsNone(r['target'])
        self.assertEqual(r['status'], '목표 미설정')


class CashflowTests(unittest.TestCase):
    def test_explicit_schedule_confirmation_required(self):
        c = cash_fixture()
        c.pop('scheduleComplete')
        self.assertEqual(calculate_cashflow(c)['status'], '계산 미완료')

    def test_daily_interest_not_monthly(self):
        c = cash_fixture()
        c.update(openingDebtWon=1000, openingCashWon=2000, annualRatePct=36.5,
                 maturityDate='2026-01-11', endDate='2026-01-11')
        r = calculate_cashflow(c)
        self.assertAlmostEqual(r['summary']['interestWon'], 10)
        self.assertEqual(r['summary']['maturityUnpaidWon'], 0)
        self.assertAlmostEqual(r['summary']['finalCashWon'], 990)

    def test_intra_month_shortage_not_hidden(self):
        c = cash_fixture()
        c.update(loanLimitWon=0, financingConfirmed=False)
        c['events'] = [{'date':'2026-01-05','kind':'cost','amountWon':100}, {'date':'2026-01-20','kind':'equity','amountWon':100}]
        r = calculate_cashflow(c)
        self.assertEqual(r['summary']['maxUnfundedWon'], 100)
        self.assertEqual(r['summary']['maxUnfundedDate'], '2026-01-05')
        self.assertEqual(r['summary']['finalUnpaidWon'], 0)

    def test_principal_is_not_interest_cost(self):
        c = cash_fixture()
        c.update(openingDebtWon=100, openingCashWon=100)
        r = calculate_cashflow(c)
        self.assertEqual(r['summary']['interestWon'], 0)
        self.assertEqual(sum(row['principalPaidWon'] for row in r['rows']), 100)

    def test_unconfirmed_debt_not_available(self):
        c = cash_fixture()
        c['financingConfirmed'] = False
        c['events'] = [{'date':'2026-01-05','kind':'cost','amountWon':100}]
        self.assertEqual(calculate_cashflow(c)['summary']['maxUnfundedWon'],100)

    def test_early_principal_arrears_carried_forward(self):
        c = cash_fixture()
        c.update(openingDebtWon=100, autoDraw=False)
        c['events'] = [{'date':'2026-01-05','kind':'loanRepay','amountWon':100}, {'date':'2026-01-20','kind':'equity','amountWon':100}]
        r = calculate_cashflow(c)
        jan20 = next(row for row in r['rows'] if row['date']=='2026-01-20')
        self.assertEqual(jan20['principalPaidWon'],100)
        self.assertEqual(jan20['debtWon'],0)

    def test_auto_draw_does_not_roll_early_principal(self):
        c = cash_fixture()
        c.update(openingDebtWon=100, autoDraw=True)
        c['events'] = [{'date':'2026-01-05','kind':'loanRepay','amountWon':100}]
        r = calculate_cashflow(c)
        jan5 = next(row for row in r['rows'] if row['date']=='2026-01-05')
        self.assertEqual(jan5['drawWon'],0)
        self.assertEqual(jan5['principalOverdueWon'],100)

    def test_exit_fixed_past_and_future_cash_path(self):
        c = cash_fixture()
        c.update(openingDebtWon=60, autoDraw=False)
        c['exit'] = {'pastContractedPct':20,'expectedFutureContractedPct':80,
                     'futureSalesCurve':[{'contractDate':'2026-02-01','sharePct':100,'collections':[{'date':'2026-06-01','pct':100}]}]}
        r = calculate_cashflow(c,100)
        self.assertEqual(r['exit']['expectedPct'],100)
        # Half-won solver settlement tolerance, at a fixture price of 1 won/percentage point.
        self.assertAlmostEqual(r['exit']['requiredPct'],79.5,places=6)
        self.assertAlmostEqual(r['exit']['additionalRequiredPct'],59.5,places=6)

    def test_100_percent_receipts_after_maturity_unpayable(self):
        c = cash_fixture()
        c.update(openingDebtWon=60,autoDraw=False)
        c['exit']={'pastContractedPct':0,'expectedFutureContractedPct':100,
                   'futureSalesCurve':[{'contractDate':'2026-02-01','sharePct':100,'collections':[{'date':'2026-07-01','pct':100}]}]}
        r = calculate_cashflow(c,100)
        self.assertEqual(r['exit']['status'],'현재 조건에서 상환 불가')
        self.assertIsNone(r['exit']['requiredPct'])
        self.assertEqual(r['summary']['maturityUnpaidWon'],60)
        self.assertEqual(r['summary']['finalDebtWon'],0)

    def test_past_actual_not_double_counted(self):
        c = cash_fixture()
        c['openingCashWon']=100
        c['events']=[{'date':'2025-12-31','kind':'equity','amountWon':100,'actual':True}]
        r=calculate_cashflow(c)
        self.assertEqual(r['summary']['finalCashWon'],100)
        self.assertEqual(r['pastActualCount'],1)

    def test_trust_basis_is_explicit_no_revenue_fallback(self):
        c=cash_fixture()
        c['trust']={'ratePct':1}
        r=calculate_cashflow(c,10000)
        self.assertFalse(r['financeComplete'])
        c['trust']={'basisWon':1000,'ratePct':1,'paymentSchedule':[{'date':'2026-02-01','pct':100}]}
        c['openingCashWon']=100
        r=calculate_cashflow(c,10000)
        self.assertEqual(r['summary']['trustFeeWon'],10)

    def test_required_receipt_not_equal_cash_already_collected(self):
        c=cash_fixture()
        c.update(openingCashWon=100,loanLimitWon=0)
        c['events']=[{'date':'2026-02-01','kind':'salesReceipt','amountWon':100}, {'date':'2026-02-01','kind':'cost','amountWon':50}]
        r=calculate_cashflow(c)
        self.assertEqual(max(row['requiredSalesReceiptWon'] for row in r['rows']),0)


class SecurityTests(unittest.TestCase):
    def test_secret_rejected_and_public_price_reference_preserved(self):
        f=fixture()
        f['parcels'][0]['attributes'].update(pblntfPclnd=1234, jimok='대')
        s=analyze(f)
        self.assertEqual(s['inputs']['parcels'][0]['attributes']['pblntfPclnd'],1234)
        self.assertEqual(s['results']['land']['representativeWon'],100_000_000)
        f['sources']=[{'url':'https://example.com?serviceKey=secret'}]
        with self.assertRaises(ValueError):
            analyze(f)

    def test_validator_recomputes_tampered_results(self):
        s=analyze(fixture())
        old=s['id']
        s['results']['costs']['totalWon']=0
        validated=validate_snapshot(s)
        self.assertEqual(validated['id'],old)
        self.assertEqual(validated['results']['costs']['totalWon'],100_000_000)


if __name__ == '__main__':
    unittest.main()
