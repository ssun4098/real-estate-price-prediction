import test from 'node:test';
import assert from 'node:assert/strict';
import {calculateBudget,financeRowSetting,restoreTrustDefaults,needsTrustDefaultRestore,projectRevision} from './src/content/dashboard/revision-model.mjs';
import {sanitizeSnapshot} from './src/content/dashboard/v2-policy.mjs';
const input=()=>({assumptions:{targetMarginPct:15},budgetAllocation:{trustType:'',trustRatePct:null}});

test('new and old unset trust rates use 1% without selecting a product',()=>{
 for(const budgetAllocation of [undefined,{}, {trustType:'',trustRatePct:null},{trustType:null,trustRatePct:' ' }]){
  const source={assumptions:{targetMarginPct:15},budgetAllocation},before=structuredClone(source),budget=calculateBudget(source,1000,230,0);
  assert.equal(financeRowSetting(source,'trust').value,1);
  assert.equal(budget.trustWon,10);assert.equal(budget.trustRatePct,1);
  assert.equal(budget.complete,true);assert.equal(budget.allowableWon,240);  // 공급면적 0 → 공사비 0: 토지 230 + 신탁 10
  assert.deepEqual(source,before);
 }
});

test('restored defaults preserve zero, custom rates, and non-revenue bases',()=>{
 const old=input();old.financeEditor={expenses:{trust:{mode:'revenuePct',value:null}}};
 const normalized=restoreTrustDefaults(old);
 assert.equal(needsTrustDefaultRestore(old),true);assert.equal(needsTrustDefaultRestore(normalized),false);
 assert.equal(normalized.budgetAllocation.trustType,'');assert.equal(normalized.budgetAllocation.trustRatePct,1);
 assert.equal(financeRowSetting(normalized,'trust').value,1);assert.equal(old.financeEditor.expenses.trust.value,null);
 for(const rate of [0,2.3]){
  const oldRate={...old,budgetAllocation:{trustType:'',trustRatePct:rate}};
  assert.equal(financeRowSetting(restoreTrustDefaults(oldRate),'trust').value,rate);
 }
 for(const setting of [{mode:'revenuePct',value:0},{mode:'revenuePct',value:2.3},{mode:'amount',value:25},{mode:'budgetPct',value:3},{mode:'amount',value:null}]){
  const source={...input(),budgetAllocation:{trustType:'management',trustRatePct:0},financeEditor:{expenses:{trust:setting}}};
  const restored=restoreTrustDefaults(source);
  assert.equal(restored.budgetAllocation.trustRatePct,0);assert.deepEqual(financeRowSetting(restored,'trust'),setting);
 }
});

test('in-session clearing is held, while explicit zero and user values recalculate',()=>{
 const x=restoreTrustDefaults(input());x.financeEditor={expenses:{trust:{mode:'revenuePct',value:null}}};
 assert.equal(calculateBudget(x,1000,230,0).trustWon,null);
 x.financeEditor.expenses.trust.value=0;
 assert.equal(calculateBudget(x,1000,230,0).trustWon,0);
 x.financeEditor.expenses.trust.value=3;
 x.financeEditor.expenses.construction={mode:'amount',value:600};
 const changed=calculateBudget(x,1000,230,0);
 assert.equal(changed.trustWon,30);assert(Math.abs(changed.allowableWon-1007)<1e-9);  // 230 + 600 + 600×24.5% + 30
 assert(Math.abs(changed.appliedTargetMarginPct+.7)<1e-9);
 assert.equal(changed.allocationRows.find(r=>r.id==='construction').amountWon,600);
});

test('live preview updates fee, expenses, and profit when revenue changes',()=>{
 const x={...restoreTrustDefaults(input()),parcels:[],comparables:{landCases:[],revenueCases:[]},financeEditor:{revenue:{mode:'amount',value:1000},land:{mode:'amount',value:230},expenses:{construction:{mode:'amount',value:600}}}};
 const before=projectRevision(x,null).results.budget;
 x.financeEditor.revenue.value=2000;
 const after=projectRevision(x,null).results.budget;
 assert.equal(before.trustWon,10);assert.equal(after.trustWon,20);
 assert(Math.abs(before.allowableWon-987)<1e-9);assert(Math.abs(after.allowableWon-997)<1e-9);  // 230 + 600 + 147 + 신탁
 assert(Math.abs(after.allocatedWon-997)<1e-9);assert(Math.abs(after.profitWon-1003)<1e-9);
 assert(Math.abs(after.appliedTargetMarginPct-50.15)<1e-9);
});

test('saved results held by the former product gate are recalculated for explicit rates',()=>{
 for(const rate of [0,2]){
  const inputs={...input(),budgetAllocation:{trustType:'',trustRatePct:rate},parcels:[],comparables:{landCases:[],revenueCases:[]},financeEditor:{revenue:{mode:'amount',value:1000},land:{mode:'amount',value:230},expenses:{construction:{mode:'amount',value:0}}}};
  const saved={inputs,results:{budget:{trustWon:null,allocatedWon:null,complete:false}}};
  const restored=sanitizeSnapshot(saved);
  assert.equal(needsTrustDefaultRestore(restored.inputs),false);
  assert.equal(restored.results.budget.trustWon,1000*rate/100);
  assert.equal(restored.results.budget.complete,true);
  assert.equal(saved.results.budget.trustWon,null);
 }
});
