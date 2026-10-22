import test from 'node:test';
import assert from 'node:assert/strict';
import {revenueDiagnostics,landDiagnostics} from './src/content/dashboard/comparison-diagnostics.mjs';
import {linkedDevelopment} from './src/content/dashboard/revision-model.mjs';
test('unverified positions and missing supply are independent blockers',()=>{
 const rows=revenueDiagnostics({linkedScenario:{enabled:true,areaMode:'median'},sources:[{id:'applyhome',queryScope:'radius',collectionStatus:'complete',locatedCount:17,withinRadiusCount:0,unresolvedLocationCount:43}]},{results:{development:{supplyAreaM2:null,areaStats:{n:0,median:null}}}});
 assert.deepEqual(rows.map(r=>r.code),['radius','supply']);assert.match(rows[0].message,/43건/);assert.match(rows[0].message,/없다는 뜻은 아닙니다/);
});
test('source errors are not reported as no nearby sales',()=>{
 const rows=revenueDiagnostics({sources:[{id:'applyhome',collectionStatus:'failed',withinRadiusCount:0}]},{results:{development:{supplyAreaM2:100}}});assert.deepEqual(rows.map(r=>r.code),['collection']);
});
test('saved parcel without live revenue explains missing session data and explicit requery',()=>{
 const rows=revenueDiagnostics({parcels:[{pnu:'4136025321107100000'}],comparables:{revenueCases:[]}}, {results:{development:{supplyAreaM2:100}}});
 assert.equal(rows[0].code,'query');assert.match(rows[0].message,/선택 필지.*조회/);assert.match(rows[0].message,/저장본/);
 assert.doesNotMatch(rows[0].message,/주변.*없|실패/);
});
test('valid computed zero is distinct from missing revenue',()=>assert.deepEqual(revenueDiagnostics({}, {results:{revenue:{representativeWon:0}}}),[]));
test('manual supply action appears with verified cases',()=>{
 const rows=revenueDiagnostics({comparables:{revenueCases:[{eligible:true}]},sources:[{id:'applyhome',withinRadiusCount:3}]},{results:{development:{supplyAreaM2:null}}});assert.equal(rows[0].code,'supply');assert.equal(rows[0].target,'live-development');
});
test('land collection count remains separate from classification hold',()=>{
 const state=landDiagnostics({sources:[{id:'land',rawCount:22383,collectedMonths:Array(60),requestedMonths:Array(60),collectionStatus:'complete'}]}, {results:{land:{caseDecisions:[],parcelProfiles:[{reasons:['혼합 용도지역·면적 배분 미확인']}]}}});
 assert.equal(state.rawCount,22383);assert.equal(state.collectedMonths,60);assert.equal(state.includedCount,0);assert.equal(state.mixed,true);
});
test('latest source evidence wins after retry',()=>{
 const rows=revenueDiagnostics({sources:[{id:'applyhome',collectionStatus:'failed'},{id:'applyhome',collectionStatus:'complete',withinRadiusCount:2}],comparables:{revenueCases:[{eligible:true}]}},{results:{development:{supplyAreaM2:200},revenue:{status:'가격 입력 오류'}}});assert.equal(rows[0].code,'validation');
});
test('dong collection never reports radius zero even if the current filter is radius',()=>{
 const rows=revenueDiagnostics({comparisonFilters:{scope:'radius'},sources:[{id:'applyhome',queryScope:'dong',collectionStatus:'complete',withinRadiusCount:0}],comparables:{revenueCases:[]}},{results:{development:{supplyAreaM2:100}}});
 assert.deepEqual(rows.map(row=>row.code),['cases']);assert.doesNotMatch(rows[0].message,/반경/);
});
test('confirmed zero dong search explains explicit radius option without changing scope',()=>{
 const input={comparisonFilters:{scope:'dong',landScope:'dong',dong:'진접읍 장현리'},comparables:{query:{scope:'dong',dong:'진접읍 장현리'},revenueCases:[]},sources:[{id:'applyhome',queryScope:'dong',collectionStatus:'complete',queriedBasicCount:0,basicCount:0,withinRadiusCount:0}]};
 const before=JSON.stringify(input),rows=revenueDiagnostics(input,{results:{development:{supplyAreaM2:100}}});
 assert.equal(rows[0].code,'dong-empty');assert.match(rows[0].message,/진접읍 장현리.*원문 검색 공고가 0건/);assert.match(rows[0].message,/반경/);assert.match(rows[0].message,/토지 조회 범위는 유지/);assert.equal(rows[0].target,'live-conditions');assert.equal(JSON.stringify(input),before);
});
test('dong API failure and returned but unusable notices are not reported as zero search results',()=>{
 for(const [source,expected] of [[{collectionStatus:'failed',queriedBasicCount:0},'collection'],[{collectionStatus:'complete',queriedBasicCount:3,basicCount:3},'cases']]){
  const rows=revenueDiagnostics({comparisonFilters:{scope:'dong'},sources:[{id:'applyhome',queryScope:'dong',...source}],comparables:{revenueCases:[]}},{results:{development:{supplyAreaM2:100}}});assert.equal(rows[0].code,expected);
 }
});
test('older sources use stored query scope, then explicit filter scope',()=>{
 for(const context of [{comparables:{query:{scope:'radius'}}},{comparisonFilters:{scope:'radius'}}]){
  const rows=revenueDiagnostics({...context,sources:[{id:'applyhome',withinRadiusCount:0}]},{results:{development:{supplyAreaM2:100}}});
  assert.equal(rows[0].code,'radius');
 }
});
const configured={linkedScenario:{enabled:true,areaMode:'median',farPct:200,farDefaultPct:200,farMaxPct:500},parcels:[{pnu:'1111010100100010001',areaM2:1000}]};
const complexes=[{id:'c1',label:'사례',medianSupplyAreaM2:100,caseIds:['m1']}];
const supplyMessage=(input,development,other={})=>revenueDiagnostics(input,{results:{...other,development}}).find(row=>row.code==='supply')?.message;
test('valid median with missing parcel area reports parcel verification, not missing cases',()=>{
 const input={...configured,parcels:[{pnu:'1111010100100010001',areaM2:null}]},development=linkedDevelopment(input,complexes);
 assert.equal(development.areaStats.median,100);assert.equal(development.supplyAreaM2,null);
 const message=supplyMessage(input,development);assert.match(message,/대지면적 미확보/);assert.doesNotMatch(message,/중앙값.*없/);
});
test('valid median with invalid FAR reports actual FAR error',()=>{
 const input={...configured,linkedScenario:{...configured.linkedScenario,farPct:600}},development=linkedDevelopment(input,complexes);
 assert.equal(development.areaStats.median,100);
 const message=supplyMessage(input,development);assert.match(message,/용적률 600%/);assert.doesNotMatch(message,/중앙값.*없/);
});
test('Python linked errors and validation errors are read and deduplicated',()=>{
 const error={path:'parcels',message:'선택 필지 확인 면적 미확보 → 대장 면적을 확인하세요.'};
 const message=supplyMessage(configured,{supplyAreaM2:null,unitSupplyAreaM2:100,areaStats:{n:1,median:100}},{linkedScenario:{fieldErrors:[error]},validation:{fieldErrors:[error,{path:'costs',message:'금융비 입력 오류'}]}});
 assert.equal(message,error.message);
});
test('missing median is identified from real zero-sample statistics',()=>{
 const development=linkedDevelopment(configured,[]),message=supplyMessage(configured,development);
 assert.match(message,/면적 중앙값이 없습니다/);
 const withoutErrors={...development,fieldErrors:[]};
 assert.match(supplyMessage(configured,withoutErrors),/중앙값이 없어/);
 assert.doesNotMatch(supplyMessage(configured,{supplyAreaM2:null}),/중앙값이 없어/);
});
test('zero-unit scenario remains distinct from unknown supply',()=>{
 const input={...configured,linkedScenario:{...configured.linkedScenario,farPct:0}},development=linkedDevelopment(input,complexes);
 assert.equal(development.supplyAreaM2,0);assert.equal(development.units,0);
 assert.match(supplyMessage(input,development),/1호 미만.*0㎡/);
 const missing={...development,supplyAreaM2:null,capacitySupplyAreaM2:null,units:null};
 assert.doesNotMatch(supplyMessage(input,missing),/1호 미만/);
});
