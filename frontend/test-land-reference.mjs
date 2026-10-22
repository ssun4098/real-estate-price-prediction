import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {calculateLand} from './src/content/dashboard/land-comparison.mjs';

const directory=path.dirname(fileURLToPath(import.meta.url));
const python=process.env.PF_TEST_PYTHON||'python';
const script=`import json,sys,copy
sys.path.insert(0,sys.argv[1]);from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[1]).parent/'tests'))
from test_v5_land_reference import reference_fixture
from pf_engine import analyze
base=reference_fixture()
fixtures=[base]
no_boundary=copy.deepcopy(base);no_boundary['parcels'][0].pop('boundaryAllocation');fixtures.append(no_boundary)
for changes in ({'cancelled':True},{'shareTrade':True},{'userExcluded':True},{'sourceEligible':False},{'dong':'방배동'},{'date':'2024-01-01'},{'jimok':'학교용지'},{'landUse':'개발제한구역'},{'landUse':'일반상업지역'},{'areaM2':0},{'manualExclusion':True,'manualExclusionReason':'현장 검토 제외'},{'landUse':False},{'landUse':0},{'landUse':[]},{'landUse':{}}):
 data=copy.deepcopy(base);data['comparables']['landCases']=[dict(data['comparables']['landCases'][1],**changes)];fixtures.append(data)
for changes in ({'jimok':'임야'},{'landUse':'제3종'},{'landScope':'sgg'}):
 data=copy.deepcopy(base);data['comparisonFilters'].update(changes);fixtures.append(data)
json.dump([{'input':data,'land':analyze(data,partial=True)['results']['land']} for data in fixtures],sys.stdout,ensure_ascii=False,allow_nan=False)`;
const response=spawnSync(python,['-X','utf8','-c',script,path.resolve(directory,'../backend')],{encoding:'utf8',maxBuffer:5e6});
assert.equal(response.status,0,response.stderr);
const fixtures=JSON.parse(response.stdout);
for(const [i,fixture] of fixtures.entries())test('reference distribution Python/HTML parity '+i,()=>{
 const js=calculateLand(fixture.input),py=fixture.land;
 assert.deepEqual(js.caseDecisions,py.caseDecisions);
 assert.deepEqual(js.referenceGroups,py.referenceGroups);
 assert.equal(js.representativeWon,py.comparableWon);
});
test('unknown zones do not enter residential reference distributions',()=>{
 const result=calculateLand(fixtures[0].input),ref=result.referenceGroups[0];
 assert.equal(ref.stats.n,3);assert.equal(ref.unknownZoneCount,0);assert.deepEqual([ref.stats.q1,ref.stats.median,ref.stats.q3],[2e6,3e6,3.5e6]);
 assert.deepEqual(result.groups[0].caseIds,['r1','r3','r4']);assert.equal(result.representativeWon,3e8);
});
test('missing boundary does not discard valid reference rows',()=>{
 const result=calculateLand(fixtures[1].input);assert.equal(result.representativeWon,null);assert.equal(result.groups.length,0);assert.equal(result.referenceGroups[0].stats.n,3);
});
test('clearing a filter reassesses source rows without reviving invalid trades',()=>{
 const input=structuredClone(fixtures[0].input);input.comparables.landCases[3].cancelled=true;input.comparisonFilters.landUse='제3종';
 assert.deepEqual(calculateLand(input).referenceGroups[0].caseIds,['r1','r3']);
 input.comparisonFilters.landUse='';assert.deepEqual(calculateLand(input).referenceGroups[0].caseIds,['r1','r3']);
});
