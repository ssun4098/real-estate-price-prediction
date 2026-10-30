// 수지분석 지출 계산식 (2026-10-29): 공사비 = 계획 공급면적÷3.3×평당 단가, 나머지는 공사비%·지출%·수입%·금액.
// 목표 수익률 = (총수입 − 총지출) ÷ 총수입 × 100 (입력이 아니라 결과). 같은 예시를 서버 tests/test_budget_parity.py 도 검사한다.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {calculateBudget} from './src/content/dashboard/revision-model.mjs';
import {sanitizeSnapshot} from './src/content/dashboard/v2-policy.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./test-budget-priority-fixtures.json',import.meta.url),'utf8'));
const input=f=>({assumptions:{},budgetAllocation:{trustType:f.trustType??'',trustRatePct:1},financeEditor:{expenses:f.expenses||{}}});
const close=(a,b)=>b===null?assert.equal(a,null):assert(Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-12),`${a} != ${b}`);
for(const f of fixtures)test(`수지 계산: ${f.name}`,()=>{
 const x=input(f),before=JSON.stringify(x),r=calculateBudget(x,f.revenue,f.land,f.supply),e=f.expected;
 assert.equal(r.complete,e.complete);assert.equal(r.targetAdjustmentStatus,e.state);
 close(r.totalExpenseWon,e.total);close(r.targetMarginPct,e.complete?e.margin:null);
 if(e.complete){close(r.allocatedWon,e.total);close(r.allocationRows[0].amountWon,e.construction);close(r.profitWon,f.revenue-e.total);
  const sum=f.land+r.allocationRows.reduce((s,row)=>s+row.amountWon,0)+r.trustWon;close(sum,e.total);}
 if(e.constructionShown!==undefined)close(r.allocationRows[0].amountWon,e.constructionShown);
 assert.equal(JSON.stringify(x),before);
});
test('예전 목표 수익률 입력과 예전 배분 비율(60/4/4/3/4)은 수지 계산에 쓰지 않는다',()=>{
 const base=calculateBudget(input({}),1e10,2e9,330);
 const legacy=calculateBudget({assumptions:{targetMarginPct:15},budgetAllocation:{constructionPct:60,indirectPct:4,salesPct:4,taxPct:3,financePct:4,trustType:'',trustRatePct:1}},1e10,2e9,330);
 close(legacy.totalExpenseWon,base.totalExpenseWon);close(legacy.targetMarginPct,base.targetMarginPct);
 assert.deepEqual(legacy.allocationRows.map(r=>[r.mode,r.value]),[['areaUnit',1000],['constructionPct',7],['constructionPct',6],['constructionPct',5],['constructionPct',6.5]]);
});
test('잘못된 입력은 목표 수익률·이익을 만들지 않고 나머지 항목 금액은 보여 준다',()=>{
 const r=calculateBudget(input({expenses:{indirect:{mode:'constructionPct',value:101}}}),1e10,2e9,330);
 assert.equal(r.complete,false);assert.equal(r.targetMarginPct,null);assert.equal(r.profitWon,null);assert(r.fieldErrors.length);
 assert.equal(r.allocationRows[1].amountWon,null);close(r.allocationRows[0].amountWon,1e9);close(r.allocationRows[2].amountWon,6e7);
 const wrong=calculateBudget(input({expenses:{indirect:{mode:'areaUnit',value:10}}}),1e10,2e9,330);
 assert(wrong.fieldErrors.some(e=>e.path==='financeEditor.expenses.indirect.value'));
});
test('저장(내보내기)할 때 실시간 분양수입에 기대는 수지 결과는 비운다',()=>{
 const x={...input({}),parcels:[],comparables:{landCases:[],revenueCases:[{id:'live',realtimeOnly:true,lon:127.1234567}]},financeEditor:{land:{mode:'amount',value:300},expenses:{construction:{mode:'amount',value:0}}}};
 const live=calculateBudget(x,1000,300,0),snapshot={inputs:x,results:{budget:live}},saved=sanitizeSnapshot(snapshot).results.budget;
 assert.equal(live.complete,true);
 for(const key of ['appliedTargetMarginPct','targetMarginPct','allowableWon','totalExpenseWon','profitWon'])assert.equal(saved[key],null,key);
 x.financeEditor.revenue={mode:'amount',value:1000};
 const manual=sanitizeSnapshot(snapshot).results.budget;
 close(manual.totalExpenseWon,310);close(manual.targetMarginPct,1000/310*100-100);assert.equal(manual.complete,true);
});
