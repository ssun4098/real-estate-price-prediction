"""Synthetic locations only; verify that imported/stale rows cannot bypass radius rules."""
import copy
import unittest
from pf_engine import analyze, _geo_distance_km
from test_engine import fixture


def radius_fixture():
    data = fixture()
    data['parcels'][0]['geometry'] = {'type':'Polygon','coordinates':[[
        [127.029,37.489],[127.031,37.489],[127.031,37.491],[127.029,37.491],[127.029,37.489]]]}
    data['comparisonFilters'] = {'scope':'radius','radiusKm':5,'sgg':'11650','dong':'서초동','start':'2025-01','end':'2025-12'}
    data['comparables']['query'] = {**data['comparisonFilters'],'center':{'lon':127.03,'lat':37.49}}
    data['comparables']['revenueCases'][0].update(lon=127.04,lat=37.49,addressVerified=True,coordinateVerified=True,legalDongName='검증용 다른 동')
    return data


class RadiusEngineTests(unittest.TestCase):
    def test_saved_dong_null_radius_defaults_to_five_after_new_radius_query(self):
        for version in ('pf-study-1', 'pf-study-3'):
            with self.subTest(version=version):
                saved = analyze(radius_fixture())
                saved['analysisVersion'] = version
                restored = copy.deepcopy(saved['inputs'])
                restored['comparisonFilters'].update(scope='dong', radiusKm=None)
                restored['comparables']['query'].update(scope='dong', radiusKm=None)
                restored['comparisonFilters']['scope']='radius'
                # A fresh radius response supplies the actual 5 km query; the
                # imported filter's null is the UI default, not an invalid zero.
                restored['comparables']['query'].update(scope='radius',radiusKm=5)
                result = analyze(restored)['results']['revenue']
                self.assertIsNone(result['comparisonReason'])
                self.assertEqual(result['radiusKm'],5)
                self.assertEqual(result['representativeWon'],5_000_000_000)

    def test_invalid_explicit_radius_does_not_fall_back_to_five(self):
        for radius in (0, '', -1, 'bad'):
            with self.subTest(radius=radius):
                data=radius_fixture();data['comparisonFilters']['radiusKm']=radius
                result=analyze(data)['results']['revenue']
                self.assertIsNone(result['representativeWon'])
                self.assertTrue(result['comparisonReason'])

    def test_other_dong_within_radius_retained_and_total_unchanged(self):
        result = analyze(radius_fixture())['results']['revenue']
        self.assertEqual(result['stats']['n'],1)
        self.assertEqual(result['representativeWon'],5_000_000_000)
        self.assertAlmostEqual(result['points'][0]['distanceKm'],.8823,places=3)

    def test_outside_and_unconfirmed_cannot_be_manually_included(self):
        data = radius_fixture()
        original = data['comparables']['revenueCases'][0]
        outside = {**original,'id':'far','houseManageNo':'far','lon':127.2,'distanceKm':0,'eligible':True}
        unresolved = {**original,'id':'unknown','houseManageNo':'unknown','addressVerified':False,'eligible':True}
        missing = {**original,'id':'missing','houseManageNo':'missing','lon':None,'eligible':True}
        data['comparables']['revenueCases'].extend([outside,unresolved,missing])
        result = analyze(data)['results']['revenue']
        self.assertEqual(result['stats']['n'],1)
        self.assertEqual(len(result['excluded']),3)

    def test_changed_parcel_radius_period_require_new_query(self):
        for alteration in ('geometry','radiusKm','start','query'):
            with self.subTest(alteration=alteration):
                data = radius_fixture()
                if alteration == 'geometry':
                    for point in data['parcels'][0]['geometry']['coordinates'][0]:point[0] += .05
                elif alteration == 'query':
                    data['comparables'].pop('query')
                else:
                    data['comparisonFilters'][alteration] = 3 if alteration == 'radiusKm' else '2024-01'
                result = analyze(data)['results']['revenue']
                self.assertIsNone(result['representativeWon'])
                self.assertEqual(result['status'],'주변 분양사례 재조회 필요')

    def test_supply_plan_does_not_change_comparison_population(self):
        data = radius_fixture()
        baseline = analyze(data)['results']['revenue']
        data['unitPlan'][0]['units'] *= 2
        changed = analyze(data)['results']['revenue']
        self.assertEqual(baseline['stats']['n'],changed['stats']['n'])
        self.assertEqual(changed['representativeWon'],baseline['representativeWon']*2)

    def test_legacy_dong_snapshot_keeps_its_results(self):
        self.assertEqual(analyze(fixture())['results']['revenue']['representativeWon'],5_000_000_000)

    def test_zero_distance_and_symmetry(self):
        self.assertEqual(_geo_distance_km(127,37,127,37),0)
        self.assertAlmostEqual(_geo_distance_km(127,37,128,38),_geo_distance_km(128,38,127,37))


if __name__ == '__main__':unittest.main()
