import React from 'react';
import {number,eok} from './pf-live-widgets.jsx';
import {wonM2ToEokPyeong} from './price-formula.mjs';
import {landAmountStatus} from './land-completeness.mjs';

// '예상 토지매입대금' 칸: 분석 결과의 모델 토지매입대금(land.modelEstimate)을 보여 준다.
// 수지분석 표의 '예상 토지매입대금'은 이 금액 × 모델%(기본 100%)라서 기본값이면 두 값이 같다.
// 모델% 를 바꾸거나 직접 금액을 넣었으면, 표에 실제로 들어간 금액(적용액)을 한 줄 더 보여 준다.
// 모델 값이 없으면(저장 당시 결과·모델 꺼짐) 표가 쓰는 비교사례 금액을 그대로 보여 줘서 표와 어긋나지 않게 한다.
// 금액은 서버(server/domain/analysis/land_price.py)와 화면 미리보기(model-land-estimate.mjs)가 같은 식으로 계산한다.
export function ModelLandEstimate({land}){
 const m=land?.modelEstimate,status=landAmountStatus(land||{});
 const applied=status.appliedWon,setting=land?.appliedSetting||{mode:land?.editMode,value:land?.editValue};
 const appliedNote=setting.mode==='amount'?'직접 입력한 금액':Number.isFinite(setting.value)?`모델 예측의 ${number(setting.value,1)}%`:'';

 if(m?.used!==true){
  const reason=!m
   ?(globalThis.location?.protocol==='file:'?'저장된 HTML 파일에서는 서버의 예측 모델을 부를 수 없습니다.':'저장 당시 결과라 모델 예측이 없습니다. 입력을 하나라도 바꾸면 모델 예측으로 다시 계산됩니다.')
   :(m.reason||'모델 예측을 쓰지 못했습니다.');
  return <>
   <div className="live-box-value v5-land-unit-value" data-reviewed-rows>{eok(applied)}<small>{status.status==='manual'?'사용자 가정 적용액':'비교사례 기준 토지매입대금'}</small></div>
   <small className="v6-land-fallback-note" data-reviewed-rows>모델 예측 없음 · {reason} 수지분석 표에도 이 금액이 쓰입니다.</small>
  </>;
 }

 const months=m.targetMonths||[],target=months.length?(months.length===1?months[0]:`${months[0]} ~ ${months[months.length-1]}`):null;
 const adjusted=Number.isFinite(m.adjustmentFactor)&&Math.abs(m.adjustmentFactor-1)>1e-12;
 const differs=Number.isFinite(applied)&&Number.isFinite(m.totalWon)&&Math.abs(applied-m.totalWon)>0.5;
 return <>
  <div className="live-box-value v5-land-unit-value" data-reviewed-rows>{eok(m.totalWon)}<small>모델 예측 토지매입대금{m.preview?' · 미리보기':''}</small></div>
  <small className="v3-land-total" data-reviewed-rows>
   평균 {number(wonM2ToEokPyeong(m.averageUnitPriceKrwPerM2),5)} 억원/평 · 모델 예측 {m.pricedCount}필지{m.filledCount?` · 평균 단가로 ${m.filledCount}필지 채움`:''}{adjusted?` · 가격 보정 ${number((m.adjustmentFactor-1)*100,1)}%`:''}
  </small>
  {differs
   ?<div className="v5-land-total-amount" data-reviewed-rows><span>수지분석 적용액 ({appliedNote})</span><strong>{eok(applied)}</strong></div>
   :<small className="v6-land-fallback-note" data-reviewed-rows>6개월 뒤 예측{target?` · 예측 대상월 ${target}`:''} · 수지분석 표의 예상 토지매입대금과 같은 금액</small>}
  {differs&&<small className="v6-land-fallback-note" data-reviewed-rows>6개월 뒤 예측{target?` · 예측 대상월 ${target}`:''}</small>}
  <details className="v5-land-completeness" open><summary>필지별 근거</summary>
   <small>{m.basis}</small>
   {(m.rows||[]).map((r,i)=><small key={`${r.pnu}-${i}`}>
    …{String(r.pnu).slice(-8)} · {r.jimok||'지목 미확정'} · {r.landUse||'용도지역 미확정'} · {number(r.areaM2,1)}㎡ → {number(wonM2ToEokPyeong(r.appliedUnitPriceKrwPerM2),5)} 억원/평 · {eok(r.amountWon)}
    {r.basis==='모델 예측'
     ?` (기준월 ${r.forecastMonth} → ${r.targetMonth}${r.knownGroup===false?' · 학습 때 없던 그룹':''})`
     :` (평균 단가로 채움 · ${r.reason||r.status||'모델 단가 없음'})`}
   </small>)}
  </details>
 </>;
}
