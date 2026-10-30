// 수지분석 총지출·목표 수익률 (2026-10-29 요청). 서버 costs._expense_priority_basis 와 같은 계산.
// 총지출 T = 토지비 + 각 항목. 공사비%는 허용 공사비, 지출%는 T 자신이 기준이라
// T = (토지비 + 금액·수입%·평당 항목 + 공사비% 몫) ÷ (1 − 지출% 합계) 로 풀린다.
// 목표 수익률 = (총수입 − T) ÷ 총수입 × 100 (입력값이 아니라 결과, 음수일 수 있음). 입력은 이미 검증된 값.
export const PYEONG_M2=3.3;
export function expensePriorityBasis(revenueWon,landWon,supplyM2,rows,ready){
 const finite=Number.isFinite;
 const result={requestedTargetMarginPct:null,appliedTargetMarginPct:null,requestedAllowableWon:null,allowableWon:null,totalExpenseWon:null,constructionWon:null,supplyAreaM2:finite(supplyM2)?supplyM2:null,rowAmounts:{},minimumRequiredBudgetWon:null,fixedExpenseWon:null,budgetExpensePct:null,targetAdjusted:false,targetAdjustmentStatus:'pending',adjustmentError:null};
 // 총지출과 관계없이 정해지는 금액 (근거가 없으면 null)
 const direct=r=>!finite(r.value)?null:r.mode==='amount'?r.value:r.mode==='revenuePct'?(finite(revenueWon)?revenueWon*(r.value/100):null):r.mode==='areaUnit'?(finite(supplyM2)&&supplyM2>=0?supplyM2/PYEONG_M2*r.value*10000:null):null;
 const construction=rows.find(r=>r.id==='construction');
 if(!ready){
  // 입력이 덜 됐어도 다른 항목에 의존하지 않는 금액은 보여 준다 (지출%는 총지출이 필요해 보류).
  const known=direct(construction),partial=rows.map(r=>[r.id,r.mode==='constructionPct'&&finite(known)&&finite(r.value)?known*r.value/100:direct(r)]);
  return {...result,rowAmounts:Object.fromEntries(partial.filter(([,v])=>finite(v)))};
 }
 const fail=(status,message)=>({...result,targetAdjustmentStatus:status,adjustmentError:message});
 if(construction.mode==='areaUnit'&&!(finite(supplyM2)&&supplyM2>=0))return fail('missing-supply','계획 공급면적이 없어 평당 공사비를 계산할 수 없습니다. 개발규모의 공급계획(호수·호당 면적)을 확인하세요.');
 let share=rows.reduce((s,r)=>s+(r.mode==='budgetPct'?r.value:0),0)/100;
 const constructionShare=rows.reduce((s,r)=>s+(r.mode==='constructionPct'?r.value:0),0)/100;
 let fixed=landWon+rows.reduce((s,r)=>s+(['amount','revenuePct','areaUnit'].includes(r.mode)?direct(r):0),0);
 if(construction.mode==='budgetPct')share+=constructionShare*construction.value/100;else fixed+=constructionShare*direct(construction);
 result.fixedExpenseWon=finite(fixed)?fixed:null;result.budgetExpensePct=share*100;
 if(!finite(fixed))return fail('overflow','지출 합계가 계산 범위를 초과했습니다. 금액·비율의 입력 단위를 확인하세요.');
 if(share>=1&&(fixed>0||share>1))return fail('infeasible','지출% 합계가 100% 이상이어서 토지비와 다른 지출을 함께 충당할 수 없습니다. 지출 비율 또는 입력 기준을 확인하세요.');
 const total=share<1?fixed/(1-share):0,constructionWon=construction.mode==='budgetPct'?total*construction.value/100:direct(construction);
 const rowAmounts=Object.fromEntries(rows.map(r=>[r.id,r.mode==='budgetPct'?total*r.value/100:r.mode==='constructionPct'?constructionWon*r.value/100:direct(r)]));
 // 목표 수익률 = 예상 총수입 ÷ 예상 총지출 × 100 (2026-10-30 사용자 요청; 100% = 손익분기). 서버 costs._expense_priority_basis 와 같은 식.
 const margin=revenueWon>0&&total>0?revenueWon/total*100:null;
 if(!finite(total)||!Object.values(rowAmounts).every(finite)||(margin!==null&&!finite(margin)))return fail('overflow','지출 합계가 계산 범위를 초과했습니다. 입력 금액과 지출 비율을 확인하세요.');
 return {...result,allowableWon:total,totalExpenseWon:total,minimumRequiredBudgetWon:total,constructionWon,rowAmounts,appliedTargetMarginPct:margin,targetAdjustmentStatus:revenueWon===0?'zero-revenue':'computed'};
}
