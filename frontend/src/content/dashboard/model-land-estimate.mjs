// 모델 예측 토지매입대금: 분석 결과(land)에서 서버 /api/model/land-estimate 에 보낼 필지 목록을 만들고,
// 서버 응답을 화면에 보여 줄 요약으로 정리한다. (화면 코드와 분리해 node --test 로 검사)

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

// 서버 응답 + 보내지 못한 필지 → 화면 요약. 하나라도 못 구하면 총액 대신 '산출분 소계'.
export function modelEstimateSummary(data,skipped=[]){
 const rows=[...(data?.rows||[]),...skipped];
 const priced=rows.filter(r=>Number.isFinite(r.amountWon));
 const area=rows.reduce((s,r)=>s+(r.areaM2>0?r.areaM2:0),0),pricedArea=priced.reduce((s,r)=>s+r.areaM2,0);
 const subtotal=priced.length?priced.reduce((s,r)=>s+r.amountWon,0):null;
 const complete=rows.length>0&&priced.length===rows.length;
 const months=[...new Set(priced.map(r=>r.targetMonth).filter(Boolean))].sort();
 return {
  complete,
  amountWon:subtotal,
  label:complete?'모델 예측 토지매입대금':'모델 예측 · 산출분 소계',
  pricedCount:priced.length,rowCount:rows.length,pricedAreaM2:pricedArea,
  areaPct:area>0?pricedArea/area*100:null,
  targetMonths:months.length?(months.length===1?months[0]:`${months[0]} ~ ${months[months.length-1]}`):null,
  rows,
 };
}
