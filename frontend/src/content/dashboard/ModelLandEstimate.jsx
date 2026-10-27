import React,{useEffect,useMemo,useState} from 'react';
import {number,eok,request} from './pf-live-widgets.jsx';
import {wonM2ToEokPyeong} from './price-formula.mjs';
import {modelParcels,modelEstimateSummary} from './model-land-estimate.mjs';

// '예상 토지매입대금' 칸의 모델 예측 금액. 수지분석 표의 토지 매입대금(비교사례 기준)에는 반영하지 않는다.
// prominent: 칸의 주 내용으로 크게 보여 줄 때 (금액을 맨 위에 크게, 필지별 근거는 펼친 채로)
export function ModelLandEstimate({land,prominent=false}){
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

 if(state.status==='idle'&&!skipped.length){
  if(!prominent)return null;
  const offline=globalThis.location?.protocol==='file:';
  return <div className="v3-box-empty">모델 예측 없음<small>{offline?'저장된 HTML 파일에서는 서버의 예측 모델을 부를 수 없습니다.':'필지를 선택하면 토지 단가 예측 모델로 금액을 계산합니다.'}</small></div>;
 }
 if(state.status==='loading')return prominent
  ?<div className="live-box-value v5-land-unit-value">계산 중…<small>모델 예측</small></div>
  :<small className="v6-land-fallback-note">모델 예측 계산 중…</small>;
 if(state.status==='error')return prominent
  ?<div className="v3-box-empty">모델 예측 없음<small>{state.message}</small></div>
  :<small className="v6-land-fallback-note">모델 예측 없음 · {state.message}</small>;

 const s=modelEstimateSummary(state.data,skipped);
 const averageWonM2=s.pricedAreaM2>0&&Number.isFinite(s.amountWon)?s.amountWon/s.pricedAreaM2:null;
 const coverage=`산출 ${s.pricedCount}/${s.rowCount}필지${Number.isFinite(s.areaPct)?` · 면적 ${number(s.areaPct,0)}%`:''}`;
 const parcelRows=<details className="v5-land-completeness" open={prominent}><summary>모델 예측 필지별 근거</summary>
  <small>시군구·지목·용도지역 그룹의 6개월 뒤 월간 거래단가 중앙값(CatBoost 예측) × 필지 면적입니다. 필지별 감정가가 아닙니다.</small>
  {s.rows.map((r,i)=><small key={`${r.pnu}-${i}`}>
   …{String(r.pnu).slice(-8)} · {r.jimok||'지목 미확정'} · {r.landUse||'용도지역 미확정'} · {number(r.areaM2,1)}㎡ → {Number.isFinite(r.amountWon)
    ?`${number(wonM2ToEokPyeong(r.unitPriceKrwPerM2),5)} 억원/평 · ${eok(r.amountWon)} (기준월 ${r.forecastMonth} → ${r.targetMonth}${r.knownGroup===false?' · 학습 때 없던 그룹':''})`
    :`${r.status} · ${r.reason||'사유 미상'}`}
  </small>)}
 </details>;

 if(prominent)return <>
  <div className="live-box-value v5-land-unit-value" data-reviewed-rows>{eok(s.amountWon)}<small>{s.label}</small></div>
  <small className="v3-land-total" data-reviewed-rows>{Number.isFinite(averageWonM2)?`평균 ${number(wonM2ToEokPyeong(averageWonM2),5)} 억원/평 · `:''}{coverage}</small>
  <small className="v6-land-fallback-note" data-reviewed-rows>6개월 뒤 예측{s.targetMonths?` · 예측 대상월 ${s.targetMonths}`:''} · 수지분석 표의 토지 매입대금(비교사례 기준)과는 따로 계산됩니다</small>
  {parcelRows}
 </>;
 return <>
  <div className="v5-land-total-amount" data-reviewed-rows><span>{s.label}</span><strong>{eok(s.amountWon)}</strong></div>
  <small className="v6-land-fallback-note" data-reviewed-rows>
   6개월 뒤 예측{s.targetMonths?` · 예측 대상월 ${s.targetMonths}`:''} · {coverage} · 위 금액·수지표에는 반영하지 않음
  </small>
  {parcelRows}
 </>;
}
