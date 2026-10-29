"""용도지역 8그룹 × 지목 6그룹 비교 (팀 문서 '토지실거래가 데이터 전처리 개선 내용') and explicit empty-group median fallback."""
import copy
import itertools
import unittest

from server.domain.analysis import analyze
from server.domain.land import (ZONE_OTHER, JIMOK_OTHER, JIMOK_GROUPS, ZONE_GROUPS, RULES_VERSION,
    classify_zone, classify_jimok, classify_transaction_zone, classify_transaction_jimok)
from test_engine import fixture, parcel_evidence, add_boundary

ZONES = ['제1종일반주거지역', '일반상업지역', '일반공업지역', '농림지역']
JIMOKS = ['대', '전', '임야']


def make_input(zone='농림지역', jimok='임야'):
    data = fixture()
    parcel = data['parcels'][0]
    parcel['attributes'] = parcel_evidence(zone, jimok)
    add_boundary(parcel)
    data['comparables']['landCases'] = [dict(id='case', areaM2=100, priceManwon=10000,
        landUse=zone, jimok=jimok, sourceEligible=True)]
    return data


def twelve_fixtures():
    scenarios = []
    for zone, jimok in itertools.product(ZONES, JIMOKS):
        data = make_input(zone, jimok)
        data['comparables']['landCases'] = [dict(id=f'case-{i}', areaM2=100, priceManwon=(i+1)*10000,
            landUse=z, jimok=j, sourceEligible=True) for i, (z, j) in enumerate(itertools.product(ZONES, JIMOKS))]
        scenarios.append({'name': f'matrix-{zone}-{jimok}', 'input': data})
    for method in ('median', 'mean'):
        data = make_input(jimok='도로')  # 비도시지역 · 기타 필지
        data['assumptions'].update(landMethod=method, landAdjustmentPct=10)
        source = data['comparables']['landCases'][0]
        data['comparables']['landCases'] = [dict(source, id='known'), dict(source, id='jimok-missing', jimok=None, priceManwon=80000),
            dict(source, id='zone-missing', landUse=None, priceManwon=30000), dict(source, id='both-missing', landUse='', jimok='', priceManwon=120000),
            dict(source, id='managed', landUse='계획관리지역', jimok='학교용지', priceManwon=200000)]
        scenarios.append({'name': f'missing-{method}', 'input': data})
    for patch in ({'cancelled':True},{'shareTrade':True},{'userExcluded':True},{'manualExclusion':True},
                  {'sourceEligible':False},{'priceManwon':0},{'areaM2':0},{'date':'2030-01-01'},
                  {'landUse':'주거지역'},{'landUse':'완충녹지'},{'landUse':False},{'landUse':{}},
                  {'landUse':'제1종일반주거지역','landUseCode':'UQA220'}, {'jimok':'대','jimokCode':'01'}):
        data = make_input()
        data['comparables']['landCases'][0].update(landUse=None, jimok=None)
        data['comparables']['landCases'][0].update(patch)
        scenarios.append({'name': f'invalid-{len(scenarios)}', 'input': data})
    data = make_input(jimok=None)
    scenarios.append({'name': 'selected-explicit-missing-jimok', 'input': data})
    for status in ('조회 실패', 'partial', '미확보', None):
        data = make_input(jimok=None)
        data['parcels'][0]['attributes']['landRegister']['status'] = status
        add_boundary(data['parcels'][0])
        scenarios.append({'name': f'selected-unproven-source-{status}', 'input': data})
    data = make_input(); data['parcels'][0].pop('boundaryAllocation')
    scenarios.append({'name': 'boundary-missing', 'input': data})
    data = make_input(); data['comparables']['landCases'][0].update(jimok='전')
    scenarios.append({'name': 'median-fallback', 'input': data})
    return scenarios


class TwelveGroupsTests(unittest.TestCase):
    def test_exact_six_jimok_and_eight_zone_groups(self):
        for jimok in JIMOK_GROUPS:
            self.assertEqual(classify_jimok(jimok)['matchKey'], jimok)
        self.assertEqual({classify_jimok(j)['matchKey'] for j in ('과수원','목장용지','잡종지','학교용지','도로','묘지')}, {JIMOK_OTHER})
        zones = {'전용주거지역': ('제1종전용주거지역', '제2종전용주거지역', '전용주거지역'),
                 '일반주거지역': ('제1종일반주거지역', '제2종일반주거지역', '제3종일반주거지역', '일반주거지역'),
                 '준주거지역': ('준주거지역',), '상업지역': ('중심상업지역', '일반상업지역', '근린상업지역', '유통상업지역'),
                 '공업지역': ('전용공업지역', '일반공업지역', '준공업지역'), '녹지지역': ('보전녹지지역', '생산녹지지역', '자연녹지지역'),
                 '비도시지역': ('보전관리지역', '생산관리지역', '계획관리지역', '관리지역', '농림지역', '자연환경보전지역', '자연환경보전')}
        for group, names in zones.items():
            for name in names:
                self.assertEqual(classify_transaction_zone(name)['matchKey'], group, name)
        for name in ('용도미지정', '개발제한구역', '기타'):  # 거래 자료에서만 '용도미지정 등'
            self.assertEqual(classify_transaction_zone(name)['matchKey'], ZONE_OTHER, name)
            self.assertEqual(classify_transaction_zone(name)['status'], 'ready', name)
            self.assertIsNone(classify_zone(name)['matchKey'], name)  # 필지 토지이용계획에서는 용도구역 → 분류하지 않음
        self.assertIsNone(classify_transaction_zone('주거지역')['matchKey'])  # 전용·일반·준주거 구분 불가
        self.assertEqual(list(ZONE_GROUPS[-1:]), [ZONE_OTHER])
        self.assertEqual(classify_transaction_zone(None)['matchKey'], ZONE_OTHER)
        self.assertEqual(classify_transaction_jimok(None)['matchKey'], JIMOK_OTHER)
        self.assertIsNone(classify_zone(None)['matchKey']) # boundaries remain strict

    def test_all_twelve_target_groups_use_exactly_one_matching_sample(self):
        for i, scenario in enumerate(twelve_fixtures()[:12]):
            with self.subTest(name=scenario['name']):
                result = analyze(scenario['input'])['results']['land']
                self.assertEqual(result['groups'][0]['caseIds'], [f'case-{i}'])
                self.assertEqual(result['referenceGroups'][0]['caseIds'], [f'case-{i}'])
                self.assertEqual(result['representativeWon'], (i+1)*100000000)
                self.assertEqual(result['ruleVersion'], RULES_VERSION)

    def test_missing_group_samples_change_real_and_reference_statistics_identically(self):
        for scenario in twelve_fixtures()[12:14]:
            result = analyze(scenario['input'])['results']['land']
            group, ref = result['groups'][0], result['referenceGroups'][0]
            self.assertEqual(group['caseIds'], ref['caseIds'])
            self.assertEqual(group['unitPriceStats'], ref['stats'])
            # 지목 누락은 '기타'에 들어오고, 용도지역 누락은 '용도미지정 등'으로 가서 이 그룹(비도시지역)에 섞이지 않는다.
            self.assertEqual([p['id'] for p in group['points']], ['known', 'jimok-missing', 'managed'])
            self.assertEqual(group['unknownZoneCount'], 0)
            self.assertEqual(group['unknownJimokCount'], 1)
            self.assertEqual(group['points'][1]['jimokStatus'], 'missing')
            method = scenario['input']['assumptions']['landMethod']
            self.assertAlmostEqual(result['representativeWon'], group['unitPriceStats'][method]*100*1.1, delta=0.0001)
            self.assertTrue(all(not c['classificationBasis']['fallbackUsed'] for c in result['caseDecisions']))

    def test_invalid_source_trades_never_reappear_under_missing_groups(self):
        for scenario in twelve_fixtures()[14:28]:
            result = analyze(scenario['input'], partial=True)['results']['land']
            with self.subTest(name=scenario['name']):
                self.assertIsNone(result['representativeWon'])
                self.assertFalse(result['caseDecisions'][0]['eligible'])
                self.assertFalse(result['caseDecisions'][0]['referenceEligible'])

    def test_empty_group_borrows_median_without_fabricating_direct_cases(self):
        data = make_input(); data['comparables']['landCases'][0]['jimok'] = '전'
        result = analyze(data)['results']['land']
        self.assertEqual(result['representativeWon'], 1e8)
        self.assertEqual(result['groups'][0]['stats']['n'], 0)
        self.assertTrue(result['groups'][0]['fallback']['used'])
        self.assertEqual(result['matchingPolicy']['noCasePolicy'], 'valid-other-groups-median')

    def test_missing_jimok_requires_current_successful_source_receipt(self):
        data = make_input(jimok=None)
        self.assertEqual(analyze(data)['results']['land']['representativeWon'], 1e8)
        for status in ('조회 실패', 'partial', '미확보', None):
            data['parcels'][0]['attributes']['landRegister']['status'] = status
            add_boundary(data['parcels'][0])
            self.assertIsNone(analyze(data, partial=True)['results']['land']['representativeWon'])

    def test_no_boundary_or_conflicting_jimok_still_holds(self):
        # 경계가 없어도 용도지역이 하나뿐이면 대장 면적 전체로 계산 (2026-10-29). 지목이 어긋나면 여전히 보류.
        data = make_input(); data['parcels'][0].pop('boundaryAllocation')
        result = analyze(data)['results']['land']
        self.assertIsNotNone(result['representativeWon'])
        self.assertEqual(result['referenceGroups'][0]['stats']['n'], 1)
        data = make_input()
        data['parcels'][0]['attributes']['landRegister']['rows'][0]['lndcgrCode'] = '08'
        add_boundary(data['parcels'][0])
        self.assertIsNone(analyze(data)['results']['land']['representativeWon'])

    def test_original_transaction_attributes_are_immutable(self):
        data = twelve_fixtures()[12]['input']
        original = copy.deepcopy(data)
        saved = analyze(data)
        self.assertEqual(data, original)
        self.assertEqual(saved['inputs']['comparables']['landCases'], original['comparables']['landCases'])


if __name__ == '__main__': unittest.main()
