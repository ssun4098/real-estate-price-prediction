import test from 'node:test';
import assert from 'node:assert/strict';
import {modelParcels,modelEstimateSummary} from './model-land-estimate.mjs';

const land={
 parcelProfiles:[{pnu:'4127111400100820000',jimokRaw:['전']},{pnu:'4127111400100830000',jimokRaw:['대']},{pnu:'4127111400100840000',jimokRaw:['대','전']}],
 parcelAssignments:[
  {pnu:'4127111400100820000',status:'ready',zoneName:'자연녹지지역',areaM2:100},
  {pnu:'4127111400100830000',status:'ready',zoneName:'제1종일반주거지역',areaM2:50},
  {pnu:'4127111400100840000',status:'ready',zoneName:'제1종일반주거지역',areaM2:30},  // 지목 두 개 → 보내지 않음
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

test('하나라도 못 구하면 총액이 아니라 산출분 소계로 표시한다',()=>{
 const {skipped}=modelParcels(land);
 const data={rows:[
  {pnu:'a',areaM2:100,amountWon:1e8,targetMonth:'2027-02'},
  {pnu:'b',areaM2:50,amountWon:null,status:'자료 없음'},
 ]};
 const s=modelEstimateSummary(data,skipped);
 assert.equal(s.complete,false);
 assert.equal(s.label,'모델 예측 · 산출분 소계');
 assert.equal(s.amountWon,1e8);
 assert.equal(s.pricedCount,1);assert.equal(s.rowCount,4);
 assert.equal(Math.round(s.areaPct),50);  // 100 / (100+50+30+20)
 assert.equal(s.targetMonths,'2027-02');
});

test('모두 구하면 총액이고, 예측 대상월이 다르면 범위로 보여 준다',()=>{
 const s=modelEstimateSummary({rows:[{areaM2:1,amountWon:1,targetMonth:'2027-02'},{areaM2:1,amountWon:2,targetMonth:'2026-11'}]});
 assert.equal(s.complete,true);assert.equal(s.label,'모델 예측 토지매입대금');assert.equal(s.amountWon,3);
 assert.equal(s.targetMonths,'2026-11 ~ 2027-02');
});
