import test from 'node:test';
import assert from 'node:assert/strict';
import {modelParcels,combineLandModel,applyLandModel,landAdjustmentFactor} from './model-land-estimate.mjs';
import {landAmountStatus} from './land-completeness.mjs';

const land={
 representativeWon:9e9,
 parcelProfiles:[{pnu:'4127111400100820000',jimokRaw:['전']},{pnu:'4127111400100830000',jimokRaw:['대']},{pnu:'4127111400100840000',jimokRaw:['대','전']}],
 parcelAssignments:[
  {pnu:'4127111400100820000',status:'ready',zoneName:'자연녹지지역',areaM2:100},
  {pnu:'4127111400100830000',status:'ready',zoneName:'제1종일반주거지역',areaM2:50},
  {pnu:'4127111400100840000',status:'ready',zoneName:'제1종일반주거지역',areaM2:30},  // 지목 두 개 → 모델에 못 보냄
  {pnu:'4127111400100850000',status:'missing',areaM2:20},                          // 분류 미확정
 ],
};

test('분석 결과에서 모델 요청 필지를 만들고, 못 보내는 필지는 사유와 함께 남긴다',()=>{
 const {parcels,skipped}=modelParcels(land);
 assert.deepEqual(parcels,[
  {pnu:'4127111400100820000',jimok:'전',landUse:'자연녹지지역',areaM2:100},
  {pnu:'4127111400100830000',jimok:'대',landUse:'제1종일반주거지역',areaM2:50},
 ]);
 assert.deepEqual(skipped.map(s=>s.reason),['지목 미확정','필지 분류·경계 미확정']);
});

test('못 구한 필지는 구한 필지들의 평균 단가로 채운다',()=>{
 // 구한 필지: 100㎡×1백만 + 50㎡×4백만 = 3억, 평균 2백만/㎡ → 못 구한 50㎡ 는 1억
 const m=combineLandModel([{areaM2:100,unitPriceKrwPerM2:1e6},{areaM2:50,unitPriceKrwPerM2:4e6},{areaM2:30},{areaM2:20,status:'분류 불가'}]);
 assert.equal(m.totalWon,4e8);assert.equal(m.pricedWon,3e8);assert.equal(m.filledWon,1e8);
 assert.equal(m.averageUnitPriceKrwPerM2,2e6);assert.equal(m.pricedCount,2);assert.equal(m.filledCount,2);
 assert.deepEqual(m.rows.map(r=>r.basis),['모델 예측','모델 예측','평균 단가로 채움','평균 단가로 채움']);
 assert.equal(combineLandModel([{areaM2:100,unitPriceKrwPerM2:1e6},{areaM2:50}],1.1).totalWon,1.5e8*1.1);
});

test('한 필지도 못 구했거나 면적을 모르면 모델 금액을 만들지 않는다',()=>{
 assert.equal(combineLandModel([{areaM2:100},{areaM2:50}]),null);
 assert.equal(combineLandModel([{areaM2:100,unitPriceKrwPerM2:1e6},{areaM2:null}]),null);
});

test('미리보기는 서버가 준 필지별 단가를 다시 적용해 서버와 같은 금액을 낸다',()=>{
 const server={used:true,rows:[
  {pnu:'4127111400100820000',jimok:'전',landUse:'자연녹지지역',areaM2:100,unitPriceKrwPerM2:1e6,basis:'모델 예측',targetMonth:'2027-02'},
  {pnu:'4127111400100830000',jimok:'대',landUse:'제1종일반주거지역',areaM2:50,status:'자료 없음',basis:'평균 단가로 채움'},
 ]};
 const preview=applyLandModel(land,server,1);
 assert.equal(preview.amountBasis,'model');
 assert.equal(preview.comparablesRepresentativeWon,9e9);
 // 1백만 × 100 + 평균(1백만) × (50+30+20)
 assert.equal(preview.representativeWon,2e8);
 assert.equal(preview.modelEstimate.preview,true);
 // 모델 결과가 없거나 쓰지 못했으면 비교사례 금액 그대로
 assert.equal(applyLandModel(land,undefined).representativeWon,9e9);
 assert.equal(applyLandModel(land,{used:false,reason:'꺼짐'}).representativeWon,9e9);
 assert.equal(landAdjustmentFactor({assumptions:{landAdjustmentPct:10}}),1.1);
});

test('수지분석 표 적용액과 모델% 를 화면 칸이 알 수 있다',()=>{
 const model={used:true,pricedCount:1,filledCount:0};
 const base={amountBasis:'model',modelEstimate:model,completeness:{complete:true,parcelCount:1,pricedParcelCount:1,unpricedParcelCount:0,reasons:[]}};
 const full=landAmountStatus({...base,representativeWon:2e8,appliedSetting:{mode:'comparablePct',value:100}});
 assert.equal(full.modelUsed,true);assert.equal(full.appliedPct,100);assert.equal(full.appliedWon,2e8);
 assert.equal(landAmountStatus({...base,representativeWon:1.8e8,editMode:'comparablePct',editValue:90}).appliedPct,90);
 const manual=landAmountStatus({...base,representativeWon:5e8,appliedSetting:{mode:'amount',value:5e8}});
 assert.equal(manual.modelUsed,false);assert.equal(manual.appliedPct,null);assert.equal(manual.status,'manual');
});
