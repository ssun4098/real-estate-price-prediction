// 모델 예측 토지매입대금 (서버 server/domain/analysis/land_price.py 와 같은 계산)
//
//   토지매입대금 = Σ(모델이 구한 필지: 그룹 단가 × 면적) + 구한 필지들의 평균 단가 × 못 구한 필지 면적
//                 × 토지가격 보정률
//
// 서버가 분석할 때 모델을 불러 필지별 단가를 정하고, 화면은 값을 바꾸는 동안(미리보기)
// 서버가 마지막으로 준 필지별 단가를 지금 필지 목록에 다시 적용해 같은 금액을 보여 준다.

export const MODEL_BASIS='시군구·지목·용도지역 그룹의 6개월 뒤 월간 거래단가 중앙값(학습 모델 예측) × 필지 면적. 모델이 못 구한 필지는 구한 필지들의 평균 단가로 채움.';

// 분석 결과의 필지 배분(parcelAssignments) 한 줄 = 필지 하나(또는 용도지역별로 나눈 조각 하나).
// 지목은 같은 필지의 토지대장 원문(parcelProfiles.jimokRaw)을 쓴다.
export function modelParcels(land){
 const profiles=new Map((land?.parcelProfiles||[]).map(p=>[String(p.pnu),p]));
 const parcels=[],skipped=[];
 for(const row of land?.parcelAssignments||[]){
  const pnu=String(row.pnu||''),profile=profiles.get(pnu);
  const jimok=profile?.jimokRaw?.length===1?profile.jimokRaw[0]:null;
  const reason=row.status!=='ready'?'필지 분류·경계 미확정'
   :!jimok?'지목 미확정'
   :!row.zoneName?'용도지역 미확정'
   :!(row.areaM2>0)?'면적 미확정'
   :!/^\d{19}$/.test(pnu)?'필지 번호(PNU) 확인 필요':null;
  if(reason)skipped.push({pnu,areaM2:row.areaM2,status:'분류 불가',reason});
  else parcels.push({pnu,jimok,landUse:row.zoneName,areaM2:row.areaM2});
 }
 return {parcels,skipped};
}

// 한 필지도 못 구했거나, 면적을 모르는 필지가 있으면 null (평균으로도 채울 수 없음).
export function combineLandModel(rows,adjustment=1){
 const positive=v=>typeof v==='number'&&Number.isFinite(v)&&v>0;
 const ok=rows.map(r=>positive(r.unitPriceKrwPerM2)&&positive(r.areaM2));
 if(!ok.some(Boolean)||rows.some(r=>!positive(r.areaM2)))return null;
 let pricedArea=0,pricedWon=0;
 rows.forEach((r,i)=>{if(ok[i]){pricedArea+=r.areaM2;pricedWon+=r.unitPriceKrwPerM2*r.areaM2;}});
 const average=pricedWon/pricedArea;
 let totalArea=0;for(const r of rows)totalArea+=r.areaM2;
 const filledWon=average*(totalArea-pricedArea),pricedCount=ok.filter(Boolean).length;
 return {used:true,totalWon:(pricedWon+filledWon)*adjustment,pricedWon,filledWon,averageUnitPriceKrwPerM2:average,adjustmentFactor:adjustment,
  pricedCount,filledCount:rows.length-pricedCount,rowCount:rows.length,pricedAreaM2:pricedArea,totalAreaM2:totalArea,
  targetMonths:[...new Set(rows.filter((r,i)=>ok[i]&&r.targetMonth).map(r=>r.targetMonth))].sort(),
  rows:rows.map((r,i)=>{const unit=ok[i]?r.unitPriceKrwPerM2:average;return {...r,appliedUnitPriceKrwPerM2:unit,amountWon:unit*r.areaM2,basis:ok[i]?'모델 예측':'평균 단가로 채움'};}),
  basis:MODEL_BASIS};
}

export const landAdjustmentFactor=input=>{const pct=input?.assumptions?.landAdjustmentPct??0;return Number.isFinite(pct)&&pct>-100?1+pct/100:1;};

// 미리보기: 서버가 마지막으로 준 모델 결과(previous)의 필지별 단가를 지금 필지 목록에 다시 적용한다.
// 서버 결과에 없던 새 필지는 '서버 예측 전'으로 두고 평균 단가로 채운다 (서버 결과가 오면 바로 바뀐다).
export function applyLandModel(land,previous,adjustment=1){
 const base={...land,comparablesRepresentativeWon:land.representativeWon,amountBasis:'comparables'};
 if(!previous)return base;
 if(previous.used!==true||!Array.isArray(previous.rows))return {...base,modelEstimate:{used:false,reason:previous.reason||'모델 예측 없음'}};
 const key=r=>`${r.pnu}|${r.jimok}|${r.landUse}`;
 const known=new Map(previous.rows.filter(r=>r.jimok&&r.landUse).map(r=>[key(r),r]));
 const {parcels,skipped}=modelParcels(land);
 const rows=[...parcels.map(p=>{const m=known.get(key(p));
  if(!m)return {...p,status:'서버 예측 전',reason:'새로 선택한 필지 · 서버 계산 후 반영'};
  return m.basis==='모델 예측'
   ?{...p,unitPriceKrwPerM2:m.unitPriceKrwPerM2,status:'산출',reason:null,landGroupKey:m.landGroupKey,forecastMonth:m.forecastMonth,targetMonth:m.targetMonth,knownGroup:m.knownGroup}
   :{...p,status:m.status,reason:m.reason};
 }),...skipped];
 const combined=combineLandModel(rows,adjustment);
 if(!combined)return {...base,modelEstimate:{used:false,reason:'모델이 단가를 구한 필지가 없어 비교사례 금액을 씁니다.',rows}};
 return {...base,representativeWon:combined.totalWon,amountBasis:'model',modelEstimate:{...combined,preview:true}};
}
