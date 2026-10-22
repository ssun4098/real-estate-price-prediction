import copy
import unittest
from server.domain.boundary import tolerated_adjacent_zones, recompute_boundary, attribute_basis
from server.domain.analysis import analyze
from test_boundary import multi_fixture, polygon


def residual_fixture(width=2e-10):
    data = multi_fixture()
    p = data['parcels'][0]
    cut = 127.002 - width
    geometry = polygon(127., 127.002)
    geometry['coordinates'][0] = [[127.,37.],[cut,37.],[127.002,37.],[127.002,37.001],[cut,37.001],[127.,37.001],[127.,37.]]
    evidence = p['boundaryAllocation']
    evidence['parcelGeometry'] = geometry
    evidence['parcelFeature']['geometry'] = copy.deepcopy(geometry)
    evidence['sourceFeatures'][0]['geometry'] = polygon(127., cut)
    evidence['sourceFeatures'][1]['geometry'] = polygon(cut, 127.002)
    p['attributes']['landUse']['rows'][0].update(cnflcAt='1', cnflcAtNm='포함')
    p['attributes']['landUse']['rows'][1].update(cnflcAt='3', cnflcAtNm='접함')
    evidence['attributeBasis'] = attribute_basis(p)
    return data


class AdjacentResidualTests(unittest.TestCase):
    def test_aggregate_existing_tolerance_below_equal_above(self):
        for values, allowed in [({'a':.004,'b':.005}, True), ({'a':.006,'b':.004}, True), ({'a':.006,'b':.004001}, False)]:
            result = tolerated_adjacent_zones({'inside': 100, **values}, {'inside'}, {'a','b'}, .01)
            self.assertEqual(result, {'a','b'} if allowed else set())
        self.assertEqual(tolerated_adjacent_zones({'inside':100,'unknown':.001},{'inside'},{'other'},.01),set())
        self.assertEqual(tolerated_adjacent_zones({'adjacent':.001},set(),{'adjacent'},.01),set())

    def test_micro_adjacent_raw_geometry_retained_but_never_priced_or_rescaled(self):
        data=residual_fixture();p=data['parcels'][0];raw=copy.deepcopy(p['boundaryAllocation']['sourceFeatures'])
        a=recompute_boundary(p)
        self.assertEqual(a['status'],'ready',a['reasons'])
        ignored=[part for part in a['parts'] if part.get('pricingExcluded')]
        self.assertEqual(len(ignored),1);self.assertLess(ignored[0]['geometryAreaM2'],.01)
        self.assertEqual(a['sourceFeatures'],raw)
        p['boundaryAllocation']=a
        land=analyze(data)['results']['land']
        self.assertEqual(len(land['groups']),1);self.assertEqual(len(land['boundaryParts']),1)
        self.assertLess(land['groups'][0]['areaM2'],p['areaM2'])
        self.assertGreater(land['groups'][0]['areaM2'],p['areaM2']*.999)
        self.assertTrue(land['completeness']['complete'])

    def test_substantive_or_undeclared_or_conflicting_adjacent_still_held(self):
        self.assertEqual(recompute_boundary(residual_fixture(2e-7)['parcels'][0])['status'],'held')
        for label, relation in [('접함','9'),('포함','3')]:
            p=residual_fixture()['parcels'][0]
            p['attributes']['landUse']['rows'][1].update(cnflcAt=relation,cnflcAtNm=label)
            p['boundaryAllocation']['attributeBasis']=attribute_basis(p)
            self.assertEqual(recompute_boundary(p)['status'],'held')
        p=residual_fixture()['parcels'][0]
        p['attributes']['landUse']['rows'].pop()
        p['boundaryAllocation']['attributeBasis']=attribute_basis(p)
        self.assertEqual(recompute_boundary(p)['status'],'held')

    def test_analysis_normalizes_only_verified_evidence_and_is_idempotent(self):
        data=residual_fixture();data['parcels'][0]['boundaryAllocation']['status']='held'
        first=analyze(data,partial=True);second=analyze(first['inputs'],partial=True)
        self.assertEqual(first['inputs'],second['inputs'])
        self.assertEqual(first['inputs']['parcels'][0]['boundaryAllocation']['status'],'ready')
        invalid=residual_fixture();invalid['parcels'][0]['boundaryAllocation']['attributeBasis']['pnu']='mismatch'
        first=analyze(invalid,partial=True);second=analyze(first['inputs'],partial=True)
        self.assertIsNone(first['results']['land']['representativeWon']);self.assertIsNone(second['results']['land']['representativeWon'])
        self.assertEqual(first['inputs']['parcels'][0]['boundaryAllocation']['attributeBasis']['pnu'],'mismatch')
