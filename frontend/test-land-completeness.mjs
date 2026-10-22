import {fileURLToPath} from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {calculateLand,parcelProfile} from './src/content/dashboard/land-comparison.mjs';
import {landAmountStatus} from './src/content/dashboard/land-completeness.mjs';
import {toleratedAdjacentZones,validateBoundaryAllocation} from './src/content/dashboard/boundary-allocation.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./test-v3-fixtures.json',import.meta.url),'utf8'));
const fixture=name=>structuredClone(fixtures.find(f=>f.name===name).input);

test('adjacent slivers use aggregate existing tolerance, never a per-part threshold',()=>{
 for(const [a,b,allow] of [[.004,.005,true],[.006,.004,true],[.006,.004001,false]])assert.deepEqual([...toleratedAdjacentZones({inside:100,a,b},new Set(['inside']),new Set(['a','b']),.01)],allow?['a','b']:[]);
 assert.equal(toleratedAdjacentZones({inside:100,unknown:.001},new Set(['inside']),new Set(['other']),.01).size,0);
 assert.equal(toleratedAdjacentZones({adjacent:.001},new Set(),new Set(['adjacent']),.01).size,0);
});
test('retained Python residual exclusion is validated by standalone HTML without repricing it',()=>{
 const python=process.env.PF_TEST_PYTHON||'python';
 const code="import json,sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[1]).parent/'tests'));from pf_engine import analyze;from test_boundary_residual import residual_fixture;json.dump(analyze(residual_fixture(),partial=True),sys.stdout,ensure_ascii=False,allow_nan=False)";
 const response=spawnSync(python,['-X','utf8','-c',code,fileURLToPath(new URL('../backend',import.meta.url))],{encoding:'utf8',maxBuffer:20*1024*1024});assert.equal(response.status,0,response.stderr);
 const snapshot=JSON.parse(response.stdout),p=snapshot.inputs.parcels[0],check=validateBoundaryAllocation(p),land=calculateLand(snapshot.inputs);
 assert.equal(check.status,'ready',check.reasons.join(' / '));assert.equal(check.parts.filter(p=>p.pricingExcluded).length,1);
 assert.equal(land.boundaryParts.length,1);assert.equal(land.representativeWon,snapshot.results.land.representativeWon);
 assert(land.groups[0].areaM2<p.areaM2);assert.deepEqual(land.completeness,snapshot.results.land.completeness);
 p.boundaryAllocation.parts.find(p=>p.pricingExcluded).pricingExcluded=false;assert.equal(validateBoundaryAllocation(p).status,'held');
});

test('unknown zoning code explicitly adjacent does not block current inside zoning',()=>{
 const p=fixture('residential-and-jimok').parcels[0],row={prposAreaDstrcCode:'UQA999',prposAreaDstrcCodeNm:'도시지역기타',cnflcAt:'3',cnflcAtNm:'접함'};
 p.attributes.landUse.rows.push(row);assert.equal(parcelProfile(p).status,'ready');assert.deepEqual(parcelProfile(p).adjacentRows,[row]);
 for(const [cnflcAt,cnflcAtNm] of [['1','포함'],['2','저촉'],['3','포함']]){Object.assign(row,{cnflcAt,cnflcAtNm});assert.notEqual(parcelProfile(p).status,'ready');}
});

test('fully priced groups expose complete totals and no hold reason',()=>{
 const result=calculateLand(fixture('multi-group')),s=landAmountStatus(result);
 assert.equal(result.completeness.complete,true);assert.equal(result.completeness.pricedParcelCount,2);
 assert.equal(result.completeness.unpricedParcelCount,0);assert.deepEqual(s.reasons,[]);assert.equal(s.status,'complete');
});
test('empty direct group completes its amount with an explicitly identified substitute median',()=>{
 const result=calculateLand(fixture('partial-group')),s=landAmountStatus(result);
 assert.equal(result.representativeWon,1.5e9);assert.equal(result.partialRepresentativeWon,1.5e9);
 assert.equal(result.completeness.pricedParcelCount,2);assert.equal(result.completeness.unpricedParcelCount,0);
 assert.equal(result.completeness.unpricedGroupCount,0);assert.deepEqual(s.reasons,[]);
 assert.equal(s.appliedWon,1.5e9);assert.equal(s.label,'전체 산출 · 중앙값 대체 포함');assert.match(s.summary,/2\/2필지/);
 const substituted=result.groups.find(group=>group.fallback.used);assert.equal(substituted.stats.n,0);assert.equal(substituted.representativeUnitPriceWonM2,1e6);assert.deepEqual(substituted.fallback.sourceCaseIds,['A']);
});
test('held boundary is distinguished from missing transaction price',()=>{
 const input=fixture('multi-group');delete input.parcels[1].boundaryAllocation;
 const result=calculateLand(input),c=result.completeness;
 assert.equal(c.classificationHeldParcelCount,1);assert.equal(c.unpricedGroupCount,0);
 assert.equal(c.pricedParcelCount,1);assert.match(c.reasons.join(' '),/경계 조회 필요/);assert.equal(result.representativeWon,null);
});
test('mixed parcel retains separate direct and substituted parts and counts the parcel once',()=>{
 const input=fixture('boundary-mixed-single-parcel');input.comparables.landCases=input.comparables.landCases.filter(c=>c.id!=='G');
 const result=calculateLand(input),c=result.completeness;
 assert.equal(c.classificationReadyParcelCount,1);assert.equal(c.partiallyPricedParcelCount,0);assert.equal(c.pricedParcelCount,1);assert.equal(c.unpricedParcelCount,0);
 assert(result.representativeWon>0);assert.equal(result.partialRepresentativeWon,result.representativeWon);
 assert.equal(result.fallback.groupCount,1);assert.equal(result.fallback.parcelCount,1);assert.equal(result.groups.find(group=>group.fallback.used).stats.n,0);
});
test('manual amount remains visibly manual and does not turn evidence complete',()=>{
 const input=fixture('partial-group');delete input.parcels[1].boundaryAllocation;
 const result=calculateLand(input);
 const manual=landAmountStatus({...result,representativeWon:3e9,comparableWon:null,appliedSetting:{mode:'amount',value:3e9}});
 assert.equal(manual.status,'manual');assert.equal(manual.appliedWon,3e9);assert.equal(manual.completeness.complete,false);assert.equal(manual.adjustedSubtotalWon,null);
 const ratio=landAmountStatus({...result,appliedSetting:{mode:'comparablePct',value:80}});
 assert.equal(ratio.adjustedSubtotalWon,result.partialRepresentativeWon*.8);assert.equal(ratio.appliedWon,null);
});
test('Python and standalone HTML report identical completeness for saved fixtures',()=>{
 const python=process.env.PF_TEST_PYTHON||'python';
 const code="import json,sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[1]).parent/'tests'));from pf_engine import analyze;data=json.load(sys.stdin);json.dump([analyze(x['input'],partial=True)['results']['land']['completeness'] for x in data],sys.stdout,ensure_ascii=False,allow_nan=False)";
 const response=spawnSync(python,['-X','utf8','-c',code,fileURLToPath(new URL('../backend',import.meta.url))],{input:JSON.stringify(fixtures),encoding:'utf8',maxBuffer:20*1024*1024});
 assert.equal(response.status,0,response.stderr);const outputs=JSON.parse(response.stdout);
 for(const [i,f] of fixtures.entries())assert.deepEqual(calculateLand(f.input).completeness,outputs[i],f.name);
});
