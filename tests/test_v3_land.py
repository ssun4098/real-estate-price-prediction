"""Synthetic V3 policy, evidence and storage tests. No authenticated I/O."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from pf_engine import analyze, validate_snapshot
from pf_land import classify_zone, classify_jimok, parcel_profile, ZONE_POOL, JIMOK_POOL
from pf_persistence import export_snapshot
from pf_server import SnapshotStore
from pf_api import Collector
from test_engine import fixture, parcel_evidence, add_boundary
from test_parcel_linkage import linked_fixture


def v3_fixture():
    data = linked_fixture()
    data['comparisonFilters'].update(landScope='dong', landMatchPolicy='custom-v3')
    data['comparables']['query'].update(landScope='dong', landRawScope='sgg')
    data['comparables']['landCases'][0].update(sourceEligible=True, sourceExclusionReasons=[])
    return data


class ProfileTests(unittest.TestCase):
    def test_exact_classification_and_pool_names(self):
        for name in ('보전녹지지역', '생산녹지지역', '자연녹지지역', '계획관리지역', '생산관리지역', '보전관리지역', '농림지역', '자연환경보전', '자연환경보전지역'):
            self.assertEqual(classify_zone(name)['matchKey'], ZONE_POOL, name)
        for name in ('전', '답', '과수원', '목장용지'):
            self.assertEqual(classify_jimok(name)['matchKey'], JIMOK_POOL)
        for name in ('완충녹지', '도시지역', '개발제한구역', '용도미지정', '아파트지구', ''):
            self.assertIsNone(classify_zone(name)['matchKey'], name)
        self.assertEqual(classify_jimok('대지')['name'], '대')
        self.assertEqual(classify_zone('제3종일반주거지역', 'UQA123')['matchKey'], '주거')

    def test_included_and_overlapping_apply_adjacent_and_parent_do_not(self):
        parcel = fixture()['parcels'][0]
        rows = parcel['attributes']['landUse']['rows']
        rows += [dict(prposAreaDstrcCode='UQA001', prposAreaDstrcCodeNm='도시지역', cnflcAt='1', cnflcAtNm='포함'),
                 dict(prposAreaDstrcCode='UQA220', prposAreaDstrcCodeNm='일반상업지역', cnflcAt='3', cnflcAtNm='접함'),
                 dict(prposAreaDstrcCode='UQT310', prposAreaDstrcCodeNm='완충녹지', cnflcAt='2', cnflcAtNm='저촉')]
        profile = parcel_profile(parcel)
        self.assertEqual(profile['status'], 'ready')
        self.assertEqual(profile['zoneMatchKey'], '주거')
        self.assertEqual(len(profile['adjacentRows']), 1)
        rows[-2].update(cnflcAt='2', cnflcAtNm='저촉')
        self.assertEqual(parcel_profile(parcel)['status'], 'ambiguous')

    def test_mixed_detail_resolves_only_one_normalized_match_group(self):
        parcel = fixture()['parcels'][0]
        parcel['attributes'] = parcel_evidence('자연녹지지역', '전')
        parcel['attributes']['landUse']['rows'].append(dict(prposAreaDstrcCodeNm='계획관리지역', cnflcAt='2', cnflcAtNm='저촉'))
        self.assertEqual(parcel_profile(parcel)['zoneMatchKey'], ZONE_POOL)
        self.assertEqual(parcel_profile(parcel)['jimokMatchKey'], JIMOK_POOL)

    def test_unknown_relation_conflict_and_cross_pnu_never_guess(self):
        changes = [dict(cnflcAt='9'), dict(cnflcAt='1', cnflcAtNm='접함'),
                   dict(prposAreaDstrcCode='UQA999'), dict(prposAreaDstrcCode='UQA220'),
                   dict(pnu='1165010800100010002')]
        for change in changes:
            parcel = fixture()['parcels'][0]
            parcel['attributes']['landUse']['rows'][0].update(change)
            with self.subTest(change=change):
                self.assertNotEqual(parcel_profile(parcel)['status'], 'ready')

    def test_unknown_adjacent_zone_does_not_block_inside_classification(self):
        parcel = fixture()['parcels'][0]
        row = dict(prposAreaDstrcCode='UQA999', prposAreaDstrcCodeNm='도시지역기타', cnflcAt='3', cnflcAtNm='접함')
        parcel['attributes']['landUse']['rows'].append(row)
        profile = parcel_profile(parcel)
        self.assertEqual(profile['status'], 'ready')
        self.assertEqual(profile['zoneMatchKey'], '주거')
        self.assertEqual(profile['adjacentRows'], [row])
        for relation, label in [('1', '포함'), ('2', '저촉'), ('3', '포함')]:
            row.update(cnflcAt=relation, cnflcAtNm=label)
            self.assertNotEqual(parcel_profile(parcel)['status'], 'ready')

    def test_stale_annual_characteristics_cannot_replace_missing_current_sources(self):
        parcel = fixture()['parcels'][0]
        parcel['attributes'] = {'characteristics': {'rows': [{'stdrYear':'2020', 'lndcgrCodeNm':'대', 'prposArea1Nm':'제3종일반주거지역'}]}}
        parcel['comparisonProfile'] = {'status':'ready','zoneMatchKey':'주거','jimokMatchKey':'대'}
        self.assertEqual(parcel_profile(parcel)['status'], 'missing')
        self.assertIsNone(parcel_profile(parcel)['zoneMatchKey'])

    def test_malformed_source_rows_are_preserved_but_cannot_produce_ready_profile(self):
        for component, rows in [('landRegister',[None]), ('landUse',[None]), ('landUse',{'bad':'shape'})]:
            data=v3_fixture();data['parcels'][0]['attributes'][component]['rows']=rows
            with self.subTest(component=component,rows=rows):
                snapshot=analyze(data,partial=True)
                self.assertEqual(snapshot['inputs']['parcels'][0]['attributes'][component]['rows'],rows)
                profile=snapshot['inputs']['parcels'][0]['comparisonProfile']
                self.assertEqual(profile['status'],'missing')
                self.assertTrue(any('원자료 행 형식 오류' in reason for reason in profile['reasons']))
                self.assertIsNone(snapshot['results']['land']['representativeWon'])
                self.assertEqual(profile['jimokRawRows' if component=='landRegister' else 'zoneRawRows'],rows)


class LandPolicyTests(unittest.TestCase):
    def test_adapter_keeps_source_eligibility_when_scope_excludes_row(self):
        collector=Collector()
        collector.revenue=lambda *a,**k:([],{'failures':0})
        source=[dict(id='same',dong='서초동',sggCode='11650',eligible=True,exclusionReason='',date='2025-01-03'),
                dict(id='outside',dong='방배동',sggCode='11650',eligible=True,exclusionReason='',date='2025-01-03')]
        collector.land_month=lambda *a:copy.deepcopy(source)
        dong=collector.comparables('11650','서초동','2025-01','2025-01',land_scope='dong')
        self.assertFalse(dong['landCases'][1]['eligible'])
        self.assertTrue(dong['landCases'][1]['sourceEligible'])
        self.assertEqual(dong['landQuery']['landRawScope'],'sgg')
        sgg=collector.comparables('11650','서초동','2025-01','2025-01',land_scope='sgg')
        self.assertTrue(sgg['landCases'][1]['eligible'])
        self.assertEqual(sgg['query']['scope'],'dong')
        self.assertEqual(len(sgg['landCases']),2)

    def test_both_match_conditions_required_and_exclusions_keep_raw_rows(self):
        data = v3_fixture()
        data['parcels'][0]['attributes'] = parcel_evidence('자연녹지지역','전')
        add_boundary(data['parcels'][0])
        case = data['comparables']['landCases'][0]
        case.update(landUse='농림지역',jimok='목장용지')
        data['comparables']['landCases'] += [dict(case,id='zone-wrong',landUse='일반상업지역'),
                                             dict(case,id='jimok-wrong',jimok='대'),
                                             dict(case,id='unknown',landUse='개발제한구역')]
        result = analyze(data)
        land = result['results']['land']
        self.assertEqual(land['representativeWon'],100_000_000)
        self.assertEqual(len(land['excluded']),3)
        self.assertEqual(len(result['inputs']['comparables']['landCases']),4)
        self.assertEqual(len(land['caseDecisions']),4)

    def test_sgg_is_explicit_and_can_use_same_complete_raw_population(self):
        data = v3_fixture()
        case = dict(data['comparables']['landCases'][0],id='outside-dong',dong='방배동',priceManwon=30000,eligible=False,exclusionReason='동 밖')
        data['comparables']['landCases'].append(case)
        land = analyze(data)['results']['land']
        self.assertEqual(land['representativeWon'],100_000_000)
        data['comparisonFilters']['landScope']='sgg'
        land = analyze(data)['results']['land']
        self.assertEqual(land['representativeWon'],200_000_000)
        self.assertEqual(land['comparisonScope'],'sgg')
        data['comparables']['query'].pop('landRawScope')
        self.assertIsNone(analyze(data)['results']['land']['representativeWon'])

    def test_multiple_cohorts_sum_independently_unresolved_parcel_holds_total(self):
        data = v3_fixture()
        parcel = dict(copy.deepcopy(data['parcels'][0]),pnu='1165010800100010002',areaM2=200,attributes=parcel_evidence('일반상업지역'))
        data['parcels'].append(parcel)
        add_boundary(parcel)
        data['comparables']['landCases'].append(dict(data['comparables']['landCases'][0],id='commercial',landUse='일반상업지역',priceManwon=20000))
        land=analyze(data)['results']['land']
        self.assertEqual(land['representativeWon'],500_000_000)
        self.assertEqual(len(land['groups']),2)
        data['parcels'][1]['attributes']={}
        land=analyze(data)['results']['land']
        self.assertIsNone(land['representativeWon'])
        self.assertEqual(land['partialRepresentativeWon'],100_000_000)
        self.assertAlmostEqual(land['coverage']['coveredPct'],100/3)

    def test_different_selected_dong_remains_blocked_in_sgg_mode(self):
        data=v3_fixture(); data['comparisonFilters']['landScope']='sgg'
        data['parcels'].append(dict(copy.deepcopy(data['parcels'][0]),pnu='1165010100100010001',legalDongCode='1165010100',dong='방배동'))
        self.assertIn('서로 다른 법정동',analyze(data)['results']['land']['comparisonReason'])

    def test_cancel_share_date_and_manual_exclusion_cannot_be_overridden(self):
        data=v3_fixture(); case=data['comparables']['landCases'][0]
        data['comparables']['landCases'] += [dict(case,id='cancel',cancelled=True,eligible=True),
                                            dict(case,id='share',shareDealingType='지분매매',eligible=True),
                                            dict(case,id='future',date='2027-01-01',eligible=True),
                                            dict(case,id='manual',userExcluded=True,userExclusionReason='현장 차이'),
                                            dict(case,id='source',sourceEligible=False,sourceExclusionReasons=['원자료 오류'])]
        land=analyze(data)['results']['land']
        self.assertEqual(land['representativeWon'],100_000_000)
        self.assertEqual(len(land['excluded']),5)
        self.assertIn('현장 차이',next(r['reason'] for r in land['excluded'] if r['id']=='manual'))

    def test_missing_query_and_partial_sources_hold_without_crash(self):
        data=v3_fixture(); data['comparables'].pop('query')
        self.assertIsNone(analyze(data)['results']['land']['representativeWon'])

    def test_land_query_partial_survives_missing_or_conflicting_source_receipt_and_export(self):
        for sources in ([],[{'id':'land','collectionStatus':'complete'}]):
            data=v3_fixture();data['sources']=sources
            data['comparables']['landQuery']={**data['comparables']['query'],'collectionStatus':'partial'}
            snapshot=analyze(data,partial=True)
            self.assertIsNone(snapshot['results']['land']['representativeWon'])
            self.assertIsNone(export_snapshot(snapshot)['results']['land']['representativeWon'])
        data=v3_fixture();data['comparables']['landCollectionStatus']='partial'
        self.assertIsNone(export_snapshot(analyze(data,partial=True))['results']['land']['representativeWon'])
        data=v3_fixture();data['sources']=[{'id':'land','collectionStatus':'partial'}]
        data['comparables']['landQuery']={**data['comparables']['query'],'collectionStatus':'complete'}
        snapshot=analyze(data,partial=True)
        self.assertIsNone(snapshot['results']['land']['comparableWon'])
        self.assertIsNone(snapshot['results']['land']['representativeWon'])
        self.assertTrue(all(not row['eligible'] for row in snapshot['results']['land']['caseDecisions']))

    def test_js_sanitizer_version_and_validation_mode_are_accepted_and_recomputed(self):
        snapshot=analyze(v3_fixture(),partial=True)
        snapshot['analysisVersion']='pf-study-3'
        snapshot['results']['validation']={'mode':'saved-independent-only','fieldErrors':[]}
        snapshot['results']['land']['representativeWon']=1
        self.assertEqual(validate_snapshot(snapshot)['results']['land']['representativeWon'],100_000_000)
        data=v3_fixture();data['sources']=[dict(id='land',collectionStatus='partial')]
        self.assertIsNone(analyze(data)['results']['land']['representativeWon'])

    def test_persistence_recomputes_untrusted_result_and_keeps_land_query(self):
        data=v3_fixture(); data['comparables']['query'].update(scope='radius',center={'lon':127.123456789,'lat':37})
        snapshot=analyze(data,partial=True); snapshot['results']['land']['representativeWon']=1
        exported=export_snapshot(snapshot)
        self.assertEqual(exported['results']['land']['representativeWon'],100_000_000)
        self.assertEqual(exported['inputs']['comparables']['landQuery']['landRawScope'],'sgg')
        self.assertNotIn('127.123456789',json.dumps(exported))
        snapshot['analysisVersion']='pf-study-1'; snapshot['inputs']['parcels'][0]['attributes']={}
        restored=validate_snapshot(snapshot)
        self.assertIsNone(restored['results']['land']['representativeWon'])

    def test_v6_store_never_writes_v2_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory); (path/'V2.html').write_text('KEEP V2',encoding='utf-8')
            store=SnapshotStore(path,'<html><head></head><body>V6</body></html>');store.initialize()
            saved=store.save(analyze(v3_fixture(),partial=True))
            self.assertEqual((path/'V2.html').read_text(encoding='utf-8'),'KEEP V2')
            self.assertTrue((path/'V6.html').exists())
            self.assertTrue(saved['fileName'].startswith('pf-study-v6-pf-'))


if __name__=='__main__':unittest.main()
