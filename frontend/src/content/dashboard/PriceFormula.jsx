import React from 'react';
import {number} from './pf-live-widgets.jsx';
import {revenueFormula} from './price-formula.mjs';
import './price-formula.css';

export function RevenueFormula({revenue,development,assumptions}){
 const f=revenueFormula(revenue,development,assumptions);
 if(!f.ready)return null;
 return <div className="v5-price-formula" data-reviewed-rows aria-label="잠재 분양수입 계산식">
  <div className="v5-formula-term"><span>평당 가격 {f.method==='mean'?'평균':'중앙값'}{f.adjustmentPct!==0?' · 보정 후':''}</span><strong>{number(f.unitEokPyeong,5)} <small>억원/평</small></strong></div>
  <div className="v5-formula-term"><span>× 분양 적용 계획면적</span><strong>{number(f.areaPyeong,2)} <small>평</small></strong></div>
  <div className="v5-formula-result">= {number(f.totalEok,2)} 억원</div>
  <details><summary>면적 환산·적용 기준</summary><small>{number(f.areaM2,2)}㎡ ÷ 3.305785 = {number(f.areaPyeong,2)}평{f.adjustmentPct!==0?` · 가격 보정 ${number(f.adjustmentPct,1)}%`:''}</small>
  {f.remainderAreaM2>0&&<small>총 계획 {number(f.capacityAreaM2,2)}㎡ − 미배정 {number(f.remainderAreaM2,2)}㎡ · 잔여면적 수입 제외</small>}</details>
 </div>;
}
