"""Selection/query regression checks. Amounts are synthetic test inputs only."""
import copy
import unittest

from server.domain.engine import analyze
from test_engine import fixture, add_boundary
from test_radius_engine import radius_fixture


def linked_fixture():
    data = fixture()
    data['parcels'][0].update(legalDongCode='1165010800', dong='서초동',
                              legalDongName='서울특별시 서초구 서초동')
    data['comparisonFilters'] = {
        'scope': 'dong', 'sgg': '11650', 'dong': '서초동',
        'legalDongCode': '1165010800', 'start': '2025-01', 'end': '2025-12',
        'selectionLinked': True,
    }
    data['comparables']['query'] = {
        k: v for k, v in data['comparisonFilters'].items()
        if k not in ('legalDongCode', 'selectionLinked')
    }
    data['comparables']['revenueCases'][0].update(legalDongCode='1165010800', date='2025-03-20')
    data['comparables']['landCases'][0].update(sggCode='11650', dong='서초동', date='2025-02-01')
    return data


class ParcelLinkageTests(unittest.TestCase):
    def assert_both_blocked(self, data):
        result = analyze(data)['results']
        for dataset in ('land', 'revenue'):
            self.assertIsNone(result[dataset]['representativeWon'])
            self.assertTrue(result[dataset]['comparisonReason'])
        self.assertIsNone(result['costs']['allowableWon'])
        return result

    def test_matching_selected_parcel_and_query_keep_values(self):
        result = analyze(linked_fixture())['results']
        self.assertEqual(result['land']['representativeWon'], 100_000_000)
        self.assertEqual(result['revenue']['representativeWon'], 5_000_000_000)

    def test_clear_selection_cannot_keep_revenue_or_land_estimates(self):
        data = linked_fixture()
        data['parcels'] = []
        self.assert_both_blocked(data)

    def test_change_selected_dong_without_updating_filters_is_blocked(self):
        data = linked_fixture()
        data['parcels'][0].update(pnu='1165010100100010001', legalDongCode='1165010100', dong='방배동')
        self.assert_both_blocked(data)

    def test_change_selected_sgg_without_updating_filters_is_blocked(self):
        data = linked_fixture()
        data['parcels'][0].update(pnu='1168010100100010001', legalDongCode='1168010100', dong='역삼동')
        self.assert_both_blocked(data)

    def test_changed_filters_cannot_relabel_old_query(self):
        data = linked_fixture()
        data['parcels'][0].update(pnu='1165010100100010001', legalDongCode='1165010100', dong='방배동')
        data['comparisonFilters'].update(legalDongCode='1165010100', dong='방배동')
        self.assert_both_blocked(data)

    def test_query_must_exist_and_match_period(self):
        for alteration in ('query', 'start', 'end'):
            with self.subTest(alteration=alteration):
                data = linked_fixture()
                if alteration == 'query':
                    data['comparables'].pop('query')
                else:
                    data['comparisonFilters'][alteration] = '2024-12'
                self.assert_both_blocked(data)

    def test_different_legal_dongs_cannot_share_one_land_query(self):
        data = linked_fixture()
        data['parcels'].append({
            'pnu': '1165010100100010001', 'legalDongCode': '1165010100',
            'dong': '방배동', 'areaM2': 100,
        })
        result = self.assert_both_blocked(data)
        self.assertIn('서로 다른 법정동', result['land']['comparisonReason'])

    def test_same_dong_new_parcel_reuses_population_but_recalculates_area(self):
        data = linked_fixture()
        data['parcels'][0].update(pnu='1165010800100020001', areaM2=150)
        add_boundary(data['parcels'][0])
        result = analyze(data)['results']
        self.assertEqual(result['land']['representativeWon'], 150_000_000)
        self.assertEqual(result['revenue']['representativeWon'], 5_000_000_000)

    def test_conflicting_pnu_and_legal_code_are_blocked(self):
        data = linked_fixture()
        data['parcels'][0]['legalDongCode'] = '1165010100'
        self.assert_both_blocked(data)

    def test_wrong_land_dong_sgg_or_month_cannot_be_manually_included(self):
        data = linked_fixture()
        case = data['comparables']['landCases'][0]
        for i, fields in enumerate(({'dong': '방배동'}, {'dong': '내곡동'},
                                    {'sggCode': '11680'}, {'date': '2024-12-01'}, {'date': None})):
            data['comparables']['landCases'].append({**case, **fields, 'id': f'bad-{i}', 'eligible': True})
        result = analyze(data)['results']['land']
        self.assertEqual(result['representativeWon'], 100_000_000)
        self.assertEqual(result['groups'][0]['stats']['n'], 1)
        self.assertEqual(len(result['excluded']), 5)

    def test_wrong_revenue_dong_cannot_be_manually_included_in_dong_mode(self):
        data = linked_fixture()
        data['comparables']['revenueCases'][0].update(legalDongCode='1165010100', eligible=True)
        result = analyze(data)['results']['revenue']
        self.assertIsNone(result['representativeWon'])
        self.assertIn('법정동 밖', result['excluded'][0]['reason'])

    def test_scope_change_requires_revenue_requery_but_land_population_is_same(self):
        data = linked_fixture()
        data['comparables']['query']['scope'] = 'radius'
        result = analyze(data)['results']
        self.assertIsNone(result['revenue']['representativeWon'])
        self.assertEqual(result['land']['representativeWon'], 100_000_000)

    def test_full_legal_name_fallback_preserves_older_api_snapshot(self):
        data = linked_fixture()
        data['parcels'][0].pop('dong')
        data['comparisonFilters'].pop('legalDongCode')
        self.assertEqual(analyze(data)['results']['land']['representativeWon'], 100_000_000)
        data.pop('comparisonFilters')
        self.assertEqual(analyze(data)['results']['land']['representativeWon'], 100_000_000)

    def test_eup_myeon_parent_required_for_village_name(self):
        data = linked_fixture()
        data['parcels'][0]['dong'] = '와부읍 도곡리'
        for record in (data['comparisonFilters'], data['comparables']['query']):
            record['dong'] = '와부읍 도곡리'
        data['comparables']['landCases'][0]['dong'] = '다른읍 도곡리'
        self.assertIsNone(analyze(data)['results']['land']['representativeWon'])

    def test_clear_radius_selection_hides_both_datasets(self):
        data = radius_fixture()
        data['parcels'] = []
        self.assert_both_blocked(data)

    def test_manual_input_without_api_metadata_still_supported(self):
        data = fixture()
        result = analyze(data)['results']
        self.assertEqual(result['revenue']['representativeWon'], 5_000_000_000)
        self.assertEqual(result['land']['representativeWon'], 100_000_000)


if __name__ == '__main__':
    unittest.main()
