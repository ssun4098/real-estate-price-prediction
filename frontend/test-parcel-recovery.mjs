import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mergeParcelAttributes,mergeSurveyParcels,failParcelLookup,setManualParcelArea,createTaskQueue,retryBusy} from './src/content/dashboard/parcel-recovery.mjs';
import {invalidateChangedComparisons,comparisonRequest} from './src/content/dashboard/comparison-scope.mjs';
const pnu='1165010800113240003',year='2026';
const geometry={type:'Polygon',coordinates:[[[127,37],[127.01,37],[127.01,37.01],[127,37]]]};
const pending={pnu,geometry,group:'사업지',areaM2:null,attributeRequestedYear:year,sourceStatus:'필지 속성 조회 중'};
const publicRow={pnu,address:'서울특별시 서초구 서초동 1324-3',legalDongName:'서울특별시 서초구 서초동',dong:'서초동',areaM2:171.2,referenceAreaM2:9999,sourceStatus:'공개자료'};
test('survey resolves existing selected parcel and unblocks automatic comparison parameters',()=>{
 const before={project:{asOf:'2026-10-05'},parcels:[pending],comparisonFilters:{scope:'radius',radiusKm:5,start:'2025-01',end:'2025-12'},comparables:{revenueCases:[],landCases:[]}};
 assert.throws(()=>comparisonRequest(before));
 const after=invalidateChangedComparisons(before,{...before,parcels:mergeSurveyParcels(before.parcels,[publicRow],year)});
 assert.equal(after.parcels[0].areaM2,171.2);assert.equal(after.parcels[0].attributeState,'ready');
 assert.equal(comparisonRequest(after).dong,'서초동');assert.equal(comparisonRequest(after).sgg,'11650');
 assert.equal(after.parcels[0].geometry,geometry);assert.equal(after.parcels[0].group,'사업지');
});
test('manual and legacy confirmed areas survive parcel and survey updates including explicit empty edit',()=>{
 for(const input of [setManualParcelArea(pending,100),{...pending,areaM2:100,sourceStatus:'사용자 확인 입력'}]){
  const next=mergeParcelAttributes(input,publicRow,year);assert.equal(next.areaM2,100);assert.equal(next.sourceStatus,'사용자 확인 입력');
 }
 const next=mergeParcelAttributes(setManualParcelArea(pending,null),publicRow,year);assert.equal(next.areaM2,null);assert.equal(next.attributeState,'partial');
});
test('wrong year / PNU / deselected parcel cannot hydrate or revive selection',()=>{
 assert.equal(mergeParcelAttributes(pending,publicRow,'2025'),pending);
 assert.equal(mergeParcelAttributes(pending,{...publicRow,pnu:'1165010800113240005'},year),pending);
 assert.deepEqual(mergeSurveyParcels([], [publicRow],year),[]);
});
test('partial and failed lookup keep valid data; no reference area substitution',()=>{
 const noArea=mergeParcelAttributes(pending,{...publicRow,areaM2:null},year);assert.equal(noArea.areaM2,null);assert.equal(noArea.attributeState,'partial');
 const good=mergeParcelAttributes(pending,publicRow,year),failed=failParcelLookup(good,'혼잡 · 다시 조회');
 assert.equal(failed.areaM2,171.2);assert.equal(failed.attributeState,'ready');assert.match(failed.attributeError,/혼잡/);
 const interrupted=failParcelLookup(pending,'조회 실패');assert.equal(interrupted.attributeState,'error');
 assert.equal(mergeParcelAttributes(good,{pnu,areaM2:null,address:''},year).address,publicRow.address);
});
test('bounded queue settles every request without exceeding two simultaneous jobs',async()=>{
 const queue=createTaskQueue(2);let running=0,maximum=0;
 const results=await Promise.all(Array.from({length:15},(_,i)=>queue.enqueue(async()=>{running++;maximum=Math.max(maximum,running);await new Promise(r=>setTimeout(r,2));running--;return i;})));
 assert.equal(maximum,2);assert.equal(results.length,15);
});
test('429 retry is bounded; authentication errors and superseded requests are not retried',async()=>{
 let calls=0;const busy=()=>Object.assign(new Error('혼잡'),{status:429,retryAfterSeconds:1});
 const out=await retryBusy(async()=>{if(++calls<3)throw busy();return 'ready';},{wait:async()=>{}});assert.equal(out,'ready');assert.equal(calls,3);
 calls=0;await assert.rejects(retryBusy(async()=>{calls++;throw Object.assign(new Error('인증'),{status:403});},{wait:async()=>{}}));assert.equal(calls,1);
 calls=0;assert.equal(await retryBusy(async()=>++calls,{isCurrent:()=>false}),null);assert.equal(calls,0);
});
