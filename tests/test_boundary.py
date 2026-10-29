"""Polygon intersection / source completeness / financial allocation contracts."""
import copy
import json
import unittest
from unittest.mock import patch

from server.domain.boundary import (recompute_boundary, attribute_basis, _request_features,
                         PARCEL_LAYER, ZONE_LAYERS, collect_boundary)
from server.domain.land import parcel_area_profile
from server.domain.analysis import analyze
from test_engine import fixture


def polygon(x0, x1, y0=37., y1=37.001):
    return {'type':'Polygon','coordinates':[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}


def multi_fixture():
    data = fixture(); p = data['parcels'][0]
    geometry = polygon(127., 127.002)
    # Subdivided outer edges are also included on the parcel: identical segment
    # tessellation avoids introducing an artificial projection-chord gap.
    geometry['coordinates'][0] = [[127.,37.],[127.001,37.],[127.002,37.],
        [127.002,37.001],[127.001,37.001],[127.,37.001],[127.,37.]]
    evidence = copy.deepcopy(p['boundaryAllocation'])
    evidence['parcelGeometry'] = geometry
    evidence['parcelFeature']['geometry'] = copy.deepcopy(geometry)
    p['attributes']['landUse']['rows'] = [
        {'prposAreaDstrcCodeNm':'제3종일반주거지역','cnflcAt':'2','cnflcAtNm':'저촉'},
        {'prposAreaDstrcCodeNm':'자연녹지지역','cnflcAt':'2','cnflcAtNm':'저촉'}]
    evidence['sourceFeatures'] = [
        {'type':'Feature','id':'res','sourceLayer':ZONE_LAYERS[0],
         'properties':{'uname':'제3종일반주거지역'},'geometry':polygon(127.,127.001)},
        {'type':'Feature','id':'green','sourceLayer':ZONE_LAYERS[0],
         'properties':{'uname':'자연녹지지역'},'geometry':polygon(127.001,127.002)}]
    evidence['source']['pages'][1].update(totalCount=2,rawCount=2,uniqueCount=2)
    evidence['attributeBasis'] = attribute_basis(p)
    p['boundaryAllocation'] = recompute_boundary(p,evidence)
    data['comparables']['landCases'].append(dict(data['comparables']['landCases'][0],
        id='green',landUse='자연녹지지역',priceManwon=20000))
    return data


class OverlayTests(unittest.TestCase):
    def test_same_polygon_has_exact_one_ratio(self):
        p=fixture()['parcels'][0];a=recompute_boundary(p)
        self.assertEqual(a['status'],'ready',a['reasons'])
        self.assertEqual(a['parts'][0]['ratio'],1)
        self.assertEqual(a['parts'][0]['allocatedAreaM2'],100)
        self.assertEqual(a['policy']['areaCrs'],'EPSG:5179')
        self.assertFalse(a['policy']['gapNormalization'])

    def test_mixed_groups_split_register_area_and_prices(self):
        data=multi_fixture();p=data['parcels'][0];a=p['boundaryAllocation']
        self.assertEqual(a['status'],'ready',a['reasons'])
        self.assertAlmostEqual(sum(part['ratio'] for part in a['parts']),1)
        self.assertAlmostEqual(sum(part['allocatedAreaM2'] for part in a['parts']),100)
        self.assertNotAlmostEqual(a['parcelGeometryAreaM2'],100)
        result=analyze(data)['results']['land']
        expected=sum(part['allocatedAreaM2']*(1e6 if part['zoneCode']=='UQA123' else 2e6) for part in a['parts'])
        self.assertAlmostEqual(result['representativeWon'],expected)
        self.assertEqual(len(result['groups']),2)
        self.assertEqual(len(result['boundaryParts']),2)
        self.assertEqual({p['appliedUnitPriceWonM2'] for p in result['boundaryParts']},{1e6,2e6})
        self.assertIsNone(result['parcelProfiles'][0]['zoneMatchKey'])

    def test_gap_is_held_without_filling_or_rescaling(self):
        p=multi_fixture()['parcels'][0]
        p['boundaryAllocation']['sourceFeatures'][1]['geometry']=polygon(127.0012,127.002)
        a=recompute_boundary(p)
        self.assertEqual(a['status'],'held')
        self.assertGreater(a['gapAreaM2'],a['toleranceM2'])
        self.assertLess(sum(part['ratio'] for part in a['parts']),1)

    def test_overlapping_distinct_zones_are_held(self):
        p=multi_fixture()['parcels'][0]
        p['boundaryAllocation']['sourceFeatures'][1]['geometry']=polygon(127.0008,127.002)
        a=recompute_boundary(p)
        self.assertEqual(a['status'],'held')
        self.assertGreater(a['overlapAreaM2'],a['toleranceM2'])

    def test_duplicate_same_zone_is_union_not_double_area(self):
        p=fixture()['parcels'][0];e=p['boundaryAllocation'];extra=copy.deepcopy(e['sourceFeatures'][0]);extra['id']='duplicate'
        e['sourceFeatures'].append(extra);e['source']['pages'][1].update(totalCount=2,rawCount=2,uniqueCount=2)
        a=recompute_boundary(p)
        self.assertEqual(a['status'],'ready',a['reasons'])
        self.assertEqual(a['parts'][0]['allocatedAreaM2'],100)
        self.assertEqual(a['overlapAreaM2'],0)

    def test_holes_and_multipolygons_keep_correct_area(self):
        p=fixture()['parcels'][0];e=p['boundaryAllocation']
        shape=polygon(127.,127.002)
        hole=polygon(127.0005,127.0015,37.0003,37.0007)['coordinates'][0]
        shape['coordinates'].append(hole)
        geometry={'type':'MultiPolygon','coordinates':[shape['coordinates'],polygon(127.003,127.004)['coordinates']]}
        e['parcelGeometry']=geometry;e['parcelFeature']['geometry']=copy.deepcopy(geometry);e['sourceFeatures'][0]['geometry']=copy.deepcopy(geometry)
        a=recompute_boundary(p)
        self.assertEqual(a['status'],'ready',a['reasons']);self.assertEqual(a['parts'][0]['ratio'],1)
        self.assertEqual(a['parts'][0]['geometry']['type'],'MultiPolygon')

    def test_missing_pages_wrong_pnu_crs_and_unclosed_rings_hold(self):
        for kind in ('pages','pnu','crs','unclosed','self-cross','attribute'):
            with self.subTest(kind=kind):
                p=fixture()['parcels'][0];e=p['boundaryAllocation']
                if kind=='pages':e['source']['pages'][1]['rawCount']=0
                elif kind=='pnu':e['parcelFeature']['properties']['pnu']='1165010800100020001'
                elif kind=='crs':e['source']['crs']='EPSG:3857'
                elif kind=='unclosed':e['sourceFeatures'][0]['geometry']['coordinates'][0].pop()
                elif kind=='self-cross':e['sourceFeatures'][0]['geometry']['coordinates']=[[[127.,37.],[127.001,37.001],[127.001,37.],[127.,37.001],[127.,37.]]]
                else:p['attributes']['landUse']['rows'][0]['prposAreaDstrcCodeNm']='일반상업지역'
                self.assertEqual(recompute_boundary(p)['status'],'held')

    def test_adjacent_region_and_facility_are_not_current_zone(self):
        p=fixture()['parcels'][0]
        for label,code in [('완충녹지','UQT310'),('개발제한구역','UDC001')]:
            e=copy.deepcopy(p['boundaryAllocation']);e['sourceFeatures'][0]['properties']['uname']=label
            self.assertEqual(recompute_boundary(p,e)['status'],'held')
        p['attributes']['landUse']['rows'].append({'prposAreaDstrcCodeNm':'일반상업지역','cnflcAt':'3','cnflcAtNm':'접함'})
        p['boundaryAllocation']['attributeBasis']=attribute_basis(p)
        self.assertEqual(recompute_boundary(p)['status'],'ready')

    def test_client_ratios_and_status_never_override_raw_geometry(self):
        data=multi_fixture();e=data['parcels'][0]['boundaryAllocation']
        expected=analyze(data)['results']['land']['representativeWon']
        e['parts'][0]['ratio']=.99;e['parts'][0]['allocatedAreaM2']=999999;e['status']='held'
        self.assertAlmostEqual(analyze(data)['results']['land']['representativeWon'],expected)
        e['sourceFeatures'][1]['geometry']=polygon(127.0012,127.002);e['status']='ready';e['reasons']=[]
        self.assertIsNone(analyze(data)['results']['land']['representativeWon'])

    def test_missing_single_zone_boundary_and_changed_register_hold(self):
        # 2026-10-29 사용자 결정: 경계가 없어도 토지이용계획의 포함·저촉 용도지역이 하나뿐이면 대장 면적 전체를 그 용도지역으로 계산한다.
        data=fixture();p=data['parcels'][0];p.pop('boundaryAllocation')
        profile=parcel_area_profile(p)
        self.assertEqual((profile['status'],profile['zoneBasis']),('ready','land-use-plan-single-zone'))
        self.assertEqual([(a['ratio'],a['areaM2']) for a in profile['areaAllocations']],[(1.0,100.0)])
        self.assertIsNotNone(analyze(data)['results']['land']['representativeWon'])
        p=fixture()['parcels'][0];p.pop('boundaryAllocation');p['areaM2']=101
        self.assertEqual(parcel_area_profile(p)['status'],'missing')
        p=fixture()['parcels'][0];p['areaM2']=101
        self.assertEqual(parcel_area_profile(p)['status'],'missing')

    def test_two_zones_without_boundary_still_hold(self):
        data=multi_fixture();data['parcels'][0].pop('boundaryAllocation')
        self.assertEqual(parcel_area_profile(data['parcels'][0])['status'],'missing')
        self.assertIsNone(analyze(data)['results']['land']['representativeWon'])

    def test_empty_group_uses_marked_fallback_for_its_verified_boundary_area(self):
        data=multi_fixture();data['comparables']['landCases']=data['comparables']['landCases'][:1]
        land=analyze(data)['results']['land']
        self.assertAlmostEqual(land['representativeWon'], 1e8)
        self.assertTrue(land['completeness']['complete'])
        self.assertEqual(len(land['boundaryParts']),2)
        self.assertEqual(sum(row['fallback']['used'] for row in land['boundaryParts']),1)
        self.assertAlmostEqual(sum(row['estimatedWon'] for row in land['boundaryParts']), land['representativeWon'])

    def test_engine_dependency_failure_holds(self):
        p=fixture()['parcels'][0];p['boundaryAllocation']['queriedAt']='fresh-test-dependency'
        with patch('server.domain.boundary._geometry_engine',side_effect=RuntimeError('missing')):
            a=recompute_boundary(p)
        self.assertEqual(a['status'],'held')
        self.assertTrue(any('계산 도구' in r for r in a['reasons']))


class FeatureCollectorTests(unittest.TestCase):
    class Client:
        domain='https://example.invalid'
        def __init__(self,responses):self.responses=iter(responses);self.calls=[]
        def require(self,name):return 'test-key-never-returned'
        def request(self,url,params):self.calls.append(params);return next(self.responses)
    def response(self,rows,total,page=1):
        return {'response':{'status':'OK','record':{'total':str(total),'current':str(len(rows))},
            'page':{'current':str(page)},'result':{'featureCollection':{'features':rows}}}}
    def feature(self,id):
        return {'type':'Feature','id':id,'properties':{'uname':'제3종일반주거지역'},'geometry':polygon(127.,127.001)}
    def test_pages_collected_without_silent_truncation(self):
        c=self.Client([self.response([self.feature('a')],2),self.response([self.feature('b')],2,2)])
        rows,meta=_request_features(c,ZONE_LAYERS[0],bbox=(127,37,127.001,37.001))
        self.assertEqual(len(rows),2);self.assertTrue(meta['complete']);self.assertEqual(meta['pageCount'],2)
        self.assertNotIn('test-key',json.dumps(rows))
    def test_auth_limit_error_empty_midpage_and_repeated_page_are_not_zero_match(self):
        cases=[ [{'response':{'status':'ERROR','error':{'code':'OVER_REQUEST_LIMIT','text':'test-key-never-returned'}}}],
          [self.response([self.feature('a')],2),{'response':{'status':'NOT_FOUND'}}],
          [self.response([self.feature('a')],2),self.response([self.feature('a')],2,2)]]
        for responses in cases:
            with self.subTest(responses=len(responses)):
                with self.assertRaises(ValueError) as error:_request_features(self.Client(responses),ZONE_LAYERS[0],bbox=(127,37,127.001,37.001))
                self.assertNotIn('test-key',str(error.exception))


if __name__=='__main__':unittest.main()
