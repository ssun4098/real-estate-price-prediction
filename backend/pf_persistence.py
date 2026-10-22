"""V5 exports retain inputs/independent land evidence, never geocoder results."""
from __future__ import annotations
import copy
from pf_engine import analyze

# This explicit, dated portfolio capture is separate from ordinary exports.
# It retains the verified values shown at capture time without claiming that
# the saved API evidence is current or relaxing the legacy requery policy.
PORTFOLIO_POLICY = 'portfolio_frozen_v1'
_PORTFOLIO_PRIVATE_FIELDS = {
    'key', 'keys', 'apikey', 'servicekey', 'confmkey', 'credentials',
    'authorization', 'password', 'secret', 'token', 'accesskey',
    'vworldapikey', 'datagokrapikey', 'jusoapikey', 'vworldgeocoderapikey',
    'vworldsearchapikey', 'kosisapikey', 'consumerkey', 'consumersecret',
    'accesstoken', 'sgissecret', 'headers', 'requestheaders', 'responseheaders',
    'cookie', 'cookies', 'setcookie', 'rawresponse', 'rawresponses',
    'geocoderresponse', 'geocoderresponses', 'request', 'rawrequest',
}


def portfolio_capture_tree(value):
    """Retain display evidence, omitting credentials and transport payloads."""
    if isinstance(value, dict):
        return {key: portfolio_capture_tree(child) for key, child in value.items()
                if isinstance(key, str) and
                ''.join(c for c in key.lower() if c not in '_- ') not in _PORTFOLIO_PRIVATE_FIELDS}
    if isinstance(value, list):
        return [portfolio_capture_tree(child) for child in value]
    return value

NOTE = 'Geocoder 실시간 위치·반경 분양사례 및 의존 수지는 저장에서 제외했습니다. Python 연결 후 다시 조회하세요.'
DROP = {'geocodingstats','geocodingoutcomes','refinedaddress','refined','rawresponse','geocoderresponse',
        'geocodingstate','coordinatebasis','coordinatesourceurl','coordinateverified','coordinatereturned',
        'geocodingmethod','geocodingerrors','distancekm'}

def _clean(value):
    if isinstance(value,list): return [cleaned for v in value if (cleaned:=_clean(v)) is not _OMIT]
    if isinstance(value,dict):
        if value.get('realtimeOnly') or value.get('persistencePolicy')=='session_only':return _OMIT
        return {k:cleaned for k,v in value.items() if k.lower() not in DROP and k not in ('siteSurvey','survey','realtimeOnly','persistencePolicy') and (cleaned:=_clean(v)) is not _OMIT}
    return value

_OMIT=object()

def export_inputs(inputs):
    safe=copy.deepcopy(inputs)
    comp=safe.get('comparables') if isinstance(safe.get('comparables'),dict) else {}
    raw_query = comp.get('landQuery') or comp.get('query') or {}
    land_query = {k: v for k, v in raw_query.items() if k in {
        'sgg','dong','legalDongCode','start','end','landStart','landEnd','asOf','landEndDate',
        'landScope','landRawScope','landMatchPolicy','landRulesVersion','collectionStatus','queriedAt','periodMode','landStartDate',
        'startDate','endDate','endExclusive','months','timezone','selectedPnus'}}
    safe['comparables']={'landCases':comp.get('landCases',[]),'revenueCases':[],
                        'query':land_query,'landQuery':land_query,'revenueNeedsRefresh':True,
                        'landCollectionStatus':comp.get('landCollectionStatus') or land_query.get('collectionStatus'),
                        'exportPolicy':'v5-geocoder-requery'}
    sources=[]
    for s in safe.get('sources',[]):
        if not isinstance(s,dict): continue
        kind=' '.join(str(s.get(k,'')) for k in ('id','dataset','name','title','url','sourceUrl')).lower()
        if s.get('realtimeOnly') or any(t in kind for t in ('applyhome','revenue','geocod','분양','req/address')): continue
        sources.append(s)
    safe['sources']=sources
    safe.pop('map',None)
    progress=safe.get('uiProgress')
    if isinstance(progress,dict):
        for k in list(progress):
            if 'revenue' in k.lower(): progress.pop(k,None)
    return _clean(safe)

def export_snapshot(snapshot):
    """Never trust caller-computed results or a caller's storage-policy flag."""
    safe=analyze(export_inputs(snapshot.get('inputs',{})),partial=True)
    for key in ('id','createdAt'):
        if key in snapshot: safe[key]=snapshot[key]
    safe['exportPolicy']='v5-geocoder-requery'
    safe['warnings']=list(dict.fromkeys([*safe.get('warnings',[]),NOTE]))
    return safe
