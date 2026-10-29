"""Cross-group substitutes use eligible transaction medians, never invented cases."""
import copy
import unittest

from server.domain.analysis import analyze, validate_snapshot
from server.domain.land import RULES_VERSION
from test_engine import add_boundary, parcel_evidence
from test_v3_land import v3_fixture


def fallback_fixture():
    data = v3_fixture()
    original = data['comparables']['landCases'][0]
    data['comparables']['landCases'] = [
        dict(original, id=f'commercial-{i}', landUse='일반상업지역', priceManwon=i * 10000)
        for i in (1, 2, 3)
    ] + [dict(original, id='industrial-9', landUse='일반공업지역', jimok='임야', priceManwon=90000)]
    return data


class MedianFallbackTests(unittest.TestCase):
    def test_pool_transactions_including_unselected_groups_not_group_medians(self):
        data = fallback_fixture()
        data['assumptions'].update(landMethod='mean', landAdjustmentPct=10)
        land = analyze(data)['results']['land']
        group, ref = land['groups'][0], land['referenceGroups'][0]
        self.assertEqual(land['ruleVersion'], RULES_VERSION)
        self.assertEqual(group['representativeUnitPriceWonM2'], 2.5e6)
        self.assertAlmostEqual(land['representativeWon'], 275e6)
        self.assertEqual(group['points'], [])
        self.assertEqual(group['caseIds'], [])
        self.assertEqual(group['stats']['n'], 0)
        self.assertIsNone(group['unitPriceStats']['median'])
        self.assertEqual(ref['stats']['n'], 0)
        self.assertEqual(ref['fallback'], group['fallback'])
        self.assertEqual(group['fallback']['sourceCaseCount'], 4)
        self.assertEqual(group['fallback']['sourceGroupCount'], 2)
        self.assertEqual(group['fallback']['reason'], '동일 그룹 비교사례 없음 · 중앙값 대체')
        self.assertTrue(land['completeness']['complete'])
        self.assertEqual(land['fallback']['parcelCount'], 1)
        for row in [land['parcelAssignments'][0], land['boundaryParts'][0]]:
            self.assertEqual(row['fallback'], group['fallback'])
            self.assertAlmostEqual(row['appliedUnitPriceWonM2'], 2.75e6)
            self.assertAlmostEqual(row['representativeWon'], 275e6)
        self.assertTrue(all(row['classificationBasis']['fallbackUsed'] for row in land['caseDecisions']))
        self.assertFalse(any(row['eligible'] for row in land['caseDecisions']))

    def test_matching_cases_always_win_and_keep_selected_method(self):
        data = fallback_fixture()
        source = v3_fixture()['comparables']['landCases'][0]
        data['comparables']['landCases'] += [dict(source, id=f'direct-{i}', priceManwon=i*10000) for i in (4, 5, 9)]
        data['assumptions']['landMethod'] = 'mean'
        land = analyze(data)['results']['land']
        self.assertEqual(land['groups'][0]['unitPriceStats']['n'], 3)
        self.assertEqual(land['representativeWon'], 6e8)
        self.assertEqual(land['groups'][0]['fallback'], {'used': False})
        self.assertFalse(land['fallback']['used'])

    def test_invalid_donors_cannot_return_through_fallback(self):
        patches = [dict(cancelled=True), dict(cancellationDate='2025-02-02'),
            dict(shareTrade=True), dict(shareDealingType='지분매매'),
            dict(userExcluded=True), dict(manualExclusion=True), dict(sourceEligible=False),
            dict(areaM2=0), dict(priceManwon=-1), dict(priceManwon=1e308),
            dict(date='2024-12-01'), dict(date='2025-02-30'), dict(date='2030-01-01'),
            dict(dong='방배동'), dict(sggCode='99999'),
            dict(landUse='완충녹지'), dict(landUse='주거지역'),  # 개발제한구역은 이제 '용도미지정 등'으로 유효
            dict(landUse='일반상업지역', landUseCode='UQA123'), dict(jimok='대', jimokCode='01')]
        for patch in patches:
            data = fallback_fixture()
            data['comparables']['landCases'] = [dict(data['comparables']['landCases'][0], **patch)]
            with self.subTest(patch=patch):
                land = analyze(data, partial=True)['results']['land']
                self.assertIsNone(land['representativeWon'])
                self.assertFalse(land['fallback']['used'])
                self.assertFalse(land['caseDecisions'][0]['fallbackEligible'])

    def test_partial_stale_and_explicit_filters_still_hold(self):
        for scenario in ('partial', 'stale', 'jimok-filter', 'zone-filter', 'missing-query'):
            data = fallback_fixture()
            if scenario == 'partial': data['comparables']['landCollectionStatus'] = 'partial'
            elif scenario == 'stale': data['comparisonFilters']['end'] = '2025-11'
            elif scenario == 'jimok-filter': data['comparisonFilters']['jimok'] = '답'
            elif scenario == 'zone-filter': data['comparisonFilters']['landUse'] = '주거'
            else: data['comparables'].pop('query')
            with self.subTest(scenario=scenario):
                land = analyze(data)['results']['land']
                self.assertIsNone(land['representativeWon'])
                self.assertFalse(land['fallback']['used'])

    def test_empty_population_boundary_failure_and_unknown_area_hold(self):
        for scenario in ('empty', 'boundary', 'area'):
            data = fallback_fixture()
            if scenario == 'empty': data['comparables']['landCases'] = []
            elif scenario == 'boundary':  # 경계 없음 + 선택 면적이 대장과 다름 → 단일 용도지역 대체도 불가
                data['parcels'][0].pop('boundaryAllocation'); data['parcels'][0]['areaM2'] += 1
            else: data['parcels'][0]['areaM2'] = None
            with self.subTest(scenario=scenario):
                land = analyze(data, partial=True)['results']['land']
                self.assertIsNone(land['representativeWon'])
                self.assertFalse(land['fallback']['used'])

    def test_multiple_targets_share_donors_without_duplicate_summary_counts(self):
        data = fallback_fixture()
        parcel = copy.deepcopy(data['parcels'][0])
        parcel.update(pnu='1165010800100010002', areaM2=200, attributes=parcel_evidence('농림지역', '전'))
        add_boundary(parcel)
        data['parcels'].append(parcel)
        land = analyze(data)['results']['land']
        self.assertEqual(land['representativeWon'], 750e6)
        self.assertEqual(land['fallback']['groupCount'], 2)
        self.assertEqual(land['fallback']['parcelCount'], 2)
        self.assertEqual(land['fallback']['sourceCaseCount'], 4)
        self.assertEqual(land['fallback']['sourceGroupCount'], 2)
        self.assertTrue(all(len(row['fallbackGroupIds']) == 2 for row in land['caseDecisions']))

    def test_snapshot_recalculation_rejects_forged_substitute_and_preserves_source(self):
        data = fallback_fixture()
        original = copy.deepcopy(data)
        snapshot = analyze(data)
        snapshot['results']['land']['groups'][0]['fallback']['unitPriceWonM2'] = 1
        restored = validate_snapshot(snapshot)['results']['land']
        self.assertEqual(restored['groups'][0]['fallback']['unitPriceWonM2'], 2.5e6)
        self.assertEqual(data, original)


if __name__ == '__main__':
    unittest.main()
