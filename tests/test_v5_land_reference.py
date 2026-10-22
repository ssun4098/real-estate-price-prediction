"""Reference unit distributions must not relax acquisition eligibility."""
import copy
import unittest
from server.domain.engine import analyze
from test_v3_land import v3_fixture
from server.domain.persistence import export_snapshot


def reference_fixture():
    data = v3_fixture()
    source = data['comparables']['landCases'][0]
    data['comparables']['landCases'] = [dict(source, id=f'r{i}', priceManwon=i*10000,
        landUse='' if i in (2, 5) else '제3종일반주거지역') for i in range(1, 6)]
    return data


class LandReferenceTests(unittest.TestCase):
    def test_missing_zones_no_longer_enter_residential_reference_quartiles(self):
        result = analyze(reference_fixture())['results']['land']
        ref = result['referenceGroups'][0]
        self.assertEqual(ref['stats']['n'], 3)
        self.assertEqual((ref['knownZoneCount'], ref['unknownZoneCount']), (3, 0))
        self.assertEqual((ref['stats']['q1'], ref['stats']['median'], ref['stats']['q3']), (2e6, 3e6, 3.5e6))
        self.assertFalse(ref['stats']['showBox'])
        self.assertEqual(result['groups'][0]['caseIds'], ['r1', 'r3', 'r4'])
        self.assertEqual(result['representativeWon'], 3e8)
        missing = result['caseDecisions'][1]
        self.assertFalse(missing['eligible'])
        self.assertFalse(missing['referenceEligible'])
        self.assertEqual(missing['zoningStatus'], 'missing')

    def test_missing_boundary_holds_total_without_hiding_reference_distribution(self):
        data = reference_fixture()
        data['parcels'][0].pop('boundaryAllocation')
        result = analyze(data)['results']['land']
        self.assertIsNone(result['representativeWon'])
        self.assertEqual(result['groups'], [])
        self.assertEqual(result['referenceGroups'][0]['stats']['n'], 3)

    def test_invalid_or_excluded_cases_do_not_reappear_as_unknown(self):
        changes = [dict(cancelled=True), dict(shareTrade=True), dict(cancellationDate='2025-02-02'),
            dict(userExcluded=True), dict(manualExclusion=True), dict(sourceEligible=False),
            dict(areaM2=0), dict(priceManwon=-1), dict(dong='방배동'), dict(sggCode='99999'),
            dict(date='2024-12-01'), dict(date='2025-02-30'), dict(jimok='학교용지'), dict(jimok='')]
        for change in changes:
            data = reference_fixture()
            data['comparables']['landCases'] = [dict(data['comparables']['landCases'][1], **change)]
            with self.subTest(change=change):
                result = analyze(data, partial=True)['results']['land']
                self.assertEqual(result['referenceGroups'][0]['stats']['n'], 0)
                self.assertFalse(result['caseDecisions'][0]['referenceEligible'])

    def test_mismatched_known_zones_and_facilities_are_not_treated_as_missing(self):
        for name in ('일반상업지역', '개발제한구역', '완충녹지', '분류코드오류'):
            data = reference_fixture()
            data['comparables']['landCases'] = [dict(data['comparables']['landCases'][1], landUse=name)]
            with self.subTest(name=name):
                result = analyze(data)['results']['land']
                self.assertEqual(result['referenceGroups'][0]['stats']['n'], 0)

    def test_partial_and_stale_requests_still_hold_reference_stats(self):
        for patch in ('partial', 'stale'):
            data = reference_fixture()
            if patch == 'partial': data['comparables']['landCollectionStatus'] = 'partial'
            else: data['comparisonFilters']['end'] = '2025-11'
            result = analyze(data)['results']['land']
            self.assertEqual(result['referenceGroups'][0]['stats']['n'], 0)

    def test_valid_missing_zone_group_can_supply_explicit_fallback_without_direct_cases(self):
        data = reference_fixture()
        data['comparables']['landCases'] = data['comparables']['landCases'][1:2]
        result = analyze(data)['results']['land']
        self.assertEqual(result['representativeWon'], 2e8)
        self.assertTrue(result['groups'][0]['fallback']['used'])
        self.assertEqual(result['referenceGroups'][0]['stats']['n'], 0)
        self.assertFalse(result['referenceGroups'][0]['stats']['showBox'])

    def test_explicit_filters_reassess_raw_rows_without_reincluding_cancelled(self):
        data = reference_fixture()
        data['comparables']['landCases'][3]['cancelled'] = True
        data['comparisonFilters']['landUse'] = '제3종'
        result = analyze(data)['results']['land']
        self.assertEqual(result['referenceGroups'][0]['caseIds'], ['r1', 'r3'])
        self.assertEqual(result['groups'][0]['caseIds'], ['r1', 'r3'])
        data['comparisonFilters']['landUse'] = ''
        result = analyze(data)['results']['land']
        self.assertEqual(result['referenceGroups'][0]['caseIds'], ['r1', 'r3'])
        data['comparisonFilters']['jimok'] = '임야'
        result = analyze(data)['results']['land']
        self.assertEqual(result['referenceGroups'][0]['stats']['n'], 0)
        self.assertIsNone(result['representativeWon'])

    def test_save_reload_recomputes_reference_evidence_and_preserves_exclusion(self):
        data = reference_fixture()
        data['comparables']['landCases'][1].update(manualExclusion=True, manualExclusionReason='현장 검토 제외')
        original = copy.deepcopy(data['comparables']['landCases'])
        snapshot = analyze(data)
        snapshot['results']['land']['referenceGroups'][0]['stats']['median'] = -999
        saved = export_snapshot(snapshot)
        restored = analyze(saved['inputs'])['results']['land']
        self.assertEqual(restored['referenceGroups'][0]['caseIds'], ['r1', 'r3', 'r4'])
        self.assertEqual(restored['referenceGroups'][0]['stats']['median'], 3e6)
        self.assertEqual(saved['inputs']['comparables']['landCases'], original)
        self.assertIn('현장 검토 제외', restored['caseDecisions'][1]['referenceReasons'])

    def test_scope_change_reuses_valid_raw_rows_but_respects_transaction_failures(self):
        data = reference_fixture()
        data['comparables']['landCases'][1].update(dong='방배동', landUse='제3종일반주거지역', eligible=False, apiEligible=False, baseEligible=False)
        data['comparables']['landCases'][4].update(dong='방배동', cancelled=True)
        self.assertNotIn('r2', analyze(data)['results']['land']['referenceGroups'][0]['caseIds'])
        data['comparisonFilters']['landScope'] = 'sgg'
        result = analyze(data)['results']['land']
        self.assertIn('r2', result['referenceGroups'][0]['caseIds'])
        self.assertNotIn('r5', result['referenceGroups'][0]['caseIds'])

    def test_malformed_zone_type_is_not_treated_as_source_missing(self):
        for value in (False, 0, [], {}):
            data = reference_fixture()
            data['comparables']['landCases'] = [dict(data['comparables']['landCases'][1], landUse=value)]
            self.assertFalse(analyze(data)['results']['land']['caseDecisions'][0]['referenceEligible'])


if __name__ == '__main__': unittest.main()
