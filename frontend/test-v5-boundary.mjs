import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {calculateLand,parcelAreaProfile} from './src/content/dashboard/land-comparison.mjs';
import {validateBoundaryAllocation,boundaryAttributeIdentity,createBoundaryRequestGate} from './src/content/dashboard/boundary-allocation.mjs';
import {boundaryEvidenceChecksum,boundaryEvidenceMatches} from './src/content/dashboard/boundary-binding.mjs';
import {sanitizeSnapshot} from './src/content/dashboard/v2-policy.mjs';
import {invalidateChangedComparisons} from './src/content/dashboard/comparison-scope.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./test-v3-fixtures.json',import.meta.url),'utf8'));
const base=()=>structuredClone(fixtures[0].input),parcel=()=>base().parcels[0];
test('저장된 경계에서 대장 면적을 배분하고 사례 단가·합계에 연결',()=>{
 const input=base(),p=input.parcels[0],check=validateBoundaryAllocation(p),result=calculateLand(input);
 assert.equal(check.status,'ready',check.reasons.join(' / '));
 assert.equal(result.boundaryParts.length,1);assert.equal(result.boundaryParts[0].allocatedAreaM2,1000);
 assert.equal(result.boundaryParts[0].appliedUnitPriceWonM2,1000000);assert.equal(result.boundaryParts[0].estimatedWon,1e9);
 assert.equal(result.boundaryParts[0].estimatedWon,result.representativeWon);
});
test('경계 근거가 없는 구버전 자료는 단일 용도지역도 보류',()=>{const input=base();delete input.parcels[0].boundaryAllocation;const result=calculateLand(input);assert.equal(result.representativeWon,null);assert.match(result.parcelProfiles[0].reasons.join(' '),/경계 조회 필요/);});
test('원경계의 좌표를 바꾸면 저장 계산의 일관성 검증에 실패',()=>{const p=parcel();assert(boundaryEvidenceMatches(p.boundaryAllocation));p.boundaryAllocation.sourceFeatures[0].geometry.coordinates[0][1][0]+=.00001;assert.equal(boundaryEvidenceMatches(p.boundaryAllocation),false);assert.equal(validateBoundaryAllocation(p).status,'held');});
test('비율과 배분면적을 함께 조작해도 원근거 결합 검사에 실패',()=>{const p=parcel();p.boundaryAllocation.parts[0].ratio=.8;p.boundaryAllocation.parts[0].allocatedAreaM2=800;p.boundaryAllocation.parts[0].geometryAreaM2=p.boundaryAllocation.parcelGeometryAreaM2*.8;assert.equal(validateBoundaryAllocation(p).status,'held');});
test('현재 대장 면적·용도지역이 바뀌면 저장 근거를 재사용하지 않음',()=>{
 const p=parcel();p.attributes.landRegister.rows[0].lndpclAr='2000';p.areaM2=2000;assert.equal(validateBoundaryAllocation(p).status,'held');
 const q=parcel();q.attributes.landUse.rows[0].prposAreaDstrcCodeNm='일반상업지역';q.attributes.landUse.rows[0].prposAreaDstrcCode='UQA220';assert.equal(validateBoundaryAllocation(q).status,'held');
});
test('사용자가 확인한 입력면적을 덮어쓰지 않고 불일치 보류',()=>{const p=parcel();p.areaM2=900;p.areaInputMode='manual';assert.equal(validateBoundaryAllocation(p).status,'held');assert.equal(p.areaM2,900);});
test('중복 대장 행과 누락 페이지를 허용하지 않음',()=>{
 const p=parcel();p.attributes.landRegister.rows.push(structuredClone(p.attributes.landRegister.rows[0]));assert.equal(validateBoundaryAllocation(p).status,'held');
 const q=parcel();q.boundaryAllocation.source.pages.pop();assert.equal(validateBoundaryAllocation(q).status,'held');
});
test('경계 누락·충돌을 비율 100% 재조정으로 숨기지 않음',()=>{for(const field of ['gapAreaM2','overlapAreaM2']){const p=parcel();p.boundaryAllocation[field]=1;p.boundaryAllocation.evidenceBinding.value=boundaryEvidenceChecksum(p.boundaryAllocation);assert.equal(validateBoundaryAllocation(p).status,'held');}});
test('누적 선택에서 일부 경계가 없으면 확인된 부분금액만 표시',()=>{
 const input=base(),p=structuredClone(input.parcels[0]);p.pnu='1168010100100020000';delete p.boundaryAllocation;input.parcels.push(p);
 const result=calculateLand(input);assert.equal(result.representativeWon,null);assert.equal(result.partialRepresentativeWon,1e9);assert.equal(result.coverage.unresolvedParcelCount,1);
});
test('선택 해제와 동일 PNU 재조회에서 늦은 응답을 거부',()=>{
 const p=parcel(),gate=createBoundaryRequestGate(),first=gate.start(p.pnu,boundaryAttributeIdentity(p));assert(gate.accepts(first,p));
 gate.cancel(p.pnu);assert(!gate.accepts(first,p));const second=gate.start(p.pnu,boundaryAttributeIdentity(p));assert(!gate.finish(first));assert(gate.accepts(second,p));
 p.areaM2=400;assert(!gate.accepts(second,p));
});
test('시간 초과와 선택 해제는 구분하고 재시도 가능',()=>{
 const p=parcel(),gate=createBoundaryRequestGate(),ticket=gate.start(p.pnu,boundaryAttributeIdentity(p));ticket.controller.abort();assert(!gate.accepts(ticket,p));assert(gate.current(ticket,p));assert(gate.finish(ticket));assert(!gate.has(p.pnu));
});
test('경계 결과 변경은 기존 지역 거래 원자료를 지우지 않음',()=>{
 const before=base(),next=structuredClone(before);delete next.parcels[0].boundaryAllocation;
 const result=invalidateChangedComparisons(before,next);assert.equal(result.comparables.landCases.length,before.comparables.landCases.length);
});
test('HTML 저장은 경계 근거와 계산을 보존하며 Geocoder 자료를 제거',()=>{
 const input=base();input.comparables.revenueCases=[{geocodingState:'secret-transient',lon:127.99999999,realtimeOnly:true}];
 const saved=sanitizeSnapshot({inputs:input,results:{}}),p=saved.inputs.parcels[0];assert.equal(validateBoundaryAllocation(p).status,'ready');assert.equal(saved.results.land.representativeWon,1e9);assert(!JSON.stringify(saved).includes('127.99999999'));
});
test('원문 분류만 검증한 상태와 경계 배분 검증을 분리',()=>{const p=parcel();delete p.boundaryAllocation;const profile=parcelAreaProfile(p);assert.equal(profile.status,'missing');assert.deepEqual(profile.areaAllocations,[]);});
test('한 필지의 주거·녹지 부분은 각 비교군 단가를 적용해 합산',()=>{
 const input=structuredClone(fixtures.find(f=>f.name==='boundary-mixed-single-parcel').input),result=calculateLand(input);
 assert.equal(result.groups.length,2);assert.equal(result.boundaryParts.length,2);
 assert.equal(result.parcelProfiles[0].status,'ready');assert.equal(result.parcelProfiles[0].zoneMatchKey,null);
 assert(Math.abs(result.groups.reduce((sum,g)=>sum+g.areaM2,0)-1000)<1e-6);
 const expected=result.boundaryParts.reduce((sum,p)=>sum+p.allocatedAreaM2*(p.zoneMatchKey==='일반주거지역'?1000000:1000000),0);
 assert(Math.abs(result.representativeWon-expected)<.001);
 input.comparables.landCases=input.comparables.landCases.filter(c=>c.id!=='G');const substituted=calculateLand(input),missing=substituted.groups.find(group=>group.fallback.used);
 assert(Math.abs(substituted.representativeWon-expected)<.001);assert.equal(missing.stats.n,0);assert.equal(missing.representativeUnitPriceWonM2,1000000);assert.deepEqual(missing.fallback.sourceCaseIds,['A','B','C','D']);assert.equal(substituted.completeness.pricedParcelCount,1);
});
test('같은 비교그룹의 여러 세부 용도지역은 면적만 합산하고 필지는 중복 집계하지 않음',()=>{
 const input=structuredClone(fixtures.find(f=>f.name==='boundary-same-group-split').input),result=calculateLand(input);
 assert.equal(result.groups.length,1);assert.equal(result.groups[0].parcelPnus.length,1);assert.equal(result.boundaryParts.length,2);assert(Math.abs(result.groups[0].areaM2-1000)<1e-6);assert(Math.abs(result.representativeWon-1e9)<.001);
});
