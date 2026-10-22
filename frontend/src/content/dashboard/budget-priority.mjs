// Expense settings take precedence over the requested target margin. Matching
// implementation: pf_engine._expense_priority_basis. Inputs are already validated.
export function expensePriorityBasis(revenueWon,landWon,targetMarginPct,rows,ready){
 const finite=Number.isFinite;
 const requestedAllowableWon=finite(revenueWon)&&finite(targetMarginPct)?revenueWon*(1-targetMarginPct/100):null;
 const result={requestedTargetMarginPct:targetMarginPct,appliedTargetMarginPct:null,requestedAllowableWon,allowableWon:requestedAllowableWon,minimumRequiredBudgetWon:null,fixedExpenseWon:null,budgetExpensePct:null,targetAdjusted:false,targetAdjustmentStatus:'pending',adjustmentError:null};
 if(!ready)return result;
 const share=rows.reduce((s,r)=>s+(r.mode==='budgetPct'?r.value:0),0)/100;
 const fixed=landWon+rows.reduce((s,r)=>s+(r.mode==='amount'?r.value:r.mode==='revenuePct'?revenueWon*(r.value/100):0),0);
 result.fixedExpenseWon=finite(fixed)?fixed:null;result.budgetExpensePct=share*100;
 const fail=(status,message)=>({...result,allowableWon:null,targetAdjustmentStatus:status,adjustmentError:message});
 if(!finite(fixed)||!finite(requestedAllowableWon))return fail('overflow','지출 합계가 계산 범위를 초과했습니다. 금액·비율의 입력 단위를 확인하세요.');
 // 100% or more cannot leave room for positive fixed expense, irrespective of
 // the target margin. The all-zero case is well-defined at a zero budget.
 if(share>=1&&(fixed>0||(share>1&&requestedAllowableWon>0)))return fail('infeasible','지출% 합계가 100% 이상이어서 토지비·금액·수입% 비용을 함께 충당할 수 없습니다. 지출 비율 또는 입력 기준을 확인하세요.');
 const required=share<1?fixed/(1-share):0,allowable=Math.max(requestedAllowableWon,required);
 const tolerance=Math.max(1e-7,Number.EPSILON*Math.max(1,Math.abs(allowable),Math.abs(requestedAllowableWon))*32);
 const adjusted=allowable-requestedAllowableWon>tolerance;
 const applied=revenueWon>0?(adjusted?(1-allowable/revenueWon)*100:targetMarginPct):null;
 if(!finite(required)||!finite(allowable)||(revenueWon>0&&!finite(applied)))return fail('overflow','지출 설정을 유지하는 목표 수익률 계산이 숫자 범위를 초과했습니다. 입력 금액과 지출 비율을 확인하세요.');
 return {...result,allowableWon:allowable,minimumRequiredBudgetWon:required,appliedTargetMarginPct:applied,targetAdjusted:adjusted,targetAdjustmentStatus:revenueWon===0?'zero-revenue':adjusted?'lowered':'unchanged'};
}
