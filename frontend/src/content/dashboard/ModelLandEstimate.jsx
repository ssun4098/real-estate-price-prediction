import React,{useEffect,useMemo,useState} from 'react';
import {number,eok,request} from './pf-live-widgets.jsx';
import {wonM2ToEokPyeong} from './price-formula.mjs';
import {modelParcels,modelEstimateSummary} from './model-land-estimate.mjs';

// '예상 토지매입대금' 칸 아래에 붙는 모델 예측 금액. 기존 금액·수지 계산에는 반영하지 않는다.
export function ModelLandEstimate({land}){
 const {parcels,skipped}=useMemo(()=>modelParcels(land),[land]);
 const body=JSON.stringify({parcels});
 const [state,setState]=useState({status:'idle'});
 useEffect(()=>{
  if(!parcels.length||globalThis.location?.protocol==='file:'){setState({status:'idle'});return}
  let alive=true;setState({status:'loading'});
  request('/api/model/land-estimate',{method:'POST',body})
   .then(data=>{if(alive)setState({status:'ready',data})})
   .catch(error=>{if(alive)setState({status:'error',message:error.status===503?'학습 모델이 꺼져 있습니다 (서버의 MODEL_ENTRYPOINT·model.cbm 확인).':error.message})});
  return()=>{alive=false};
 },[body]);

 if(state.status==='idle'&&!skipped.length)return null;
 if(state.status==='loading')return <small className="v6-land-fallback-note">모델 예측 계산 중…</small>;
 if(state.status==='error')return <small className="v6-land-fallback-note">모델 예측 없음 · {state.message}</small>;
 const s=modelEstimateSummary(state.data,skipped);
 return <>
  <div className="v5-land-total-amount" data-reviewed-rows><span>{s.label}</span><strong>{eok(s.amountWon)}</strong></div>
  <small className="v6-land-fallback-note" data-reviewed-rows>
   6개월 뒤 예측{s.targetMonths?` · 예측 대상월 ${s.targetMonths}`:''} · 산출 {s.pricedCount}/{s.rowCount}필지{Number.isFinite(s.areaPct)?` · 면적 ${number(s.areaPct,0)}%`:''} · 위 금액·수지표에는 반영하지 않음
  </small>
  <details className="v5-land-completeness"><summary>모델 예측 필지별 근거</summary>
   <small>시군구·지목·용도지역 그룹의 6개월 뒤 월간 거래단가 중앙값(CatBoost 예측) × 필지 면적입니다. 필지별 감정가가 아닙니다.</small>
   {s.rows.map((r,i)=><small key={`${r.pnu}-${i}`}>
    …{String(r.pnu).slice(-8)} · {r.jimok||'지목 미확정'} · {r.landUse||'용도지역 미확정'} · {number(r.areaM2,1)}㎡ → {Number.isFinite(r.amountWon)
     ?`${number(wonM2ToEokPyeong(r.unitPriceKrwPerM2),5)} 억원/평 · ${eok(r.amountWon)} (기준월 ${r.forecastMonth} → ${r.targetMonth}${r.knownGroup===false?' · 학습 때 없던 그룹':''})`
     :`${r.status} · ${r.reason||'사유 미상'}`}
   </small>)}
  </details>
 </>;
}
