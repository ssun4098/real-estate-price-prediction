import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {calculateBudget} from './src/content/dashboard/revision-model.mjs';
import {sanitizeSnapshot} from './src/content/dashboard/v2-policy.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./test-budget-priority-fixtures.json',import.meta.url),'utf8'));
const input=f=>({assumptions:{targetMarginPct:f.target??15},budgetAllocation:{trustType:f.trustType??'management',trustRatePct:Object.hasOwn(f,'trustRate')?f.trustRate:1},financeEditor:{expenses:f.expenses||{}}});
const close=(a,b)=>b===null?assert.equal(a,null):assert(Math.abs(a-b)<=Math.max(1e-7,Math.abs(b)*1e-12),`${a} != ${b}`);
for(const f of fixtures)test(`expense priority: ${f.name}`,()=>{
 const x=input(f),before=JSON.stringify(x),r=calculateBudget(x,f.revenue,f.land),e=f.expected;
 assert.equal(r.complete,e.complete);close(r.appliedTargetMarginPct,e.applied);close(r.allowableWon,e.allowable);close(r.allocatedWon,e.allocated);assert.equal(r.targetAdjusted,e.adjusted);if(e.state)assert.equal(r.targetAdjustmentStatus,e.state);
 assert.equal(r.requestedTargetMarginPct,f.target??15);assert.equal(JSON.stringify(x),before);
 if(r.complete){close(r.profitWon,f.revenue-r.allocatedWon);assert(r.overallocatedWon<=1e-7);for(const row of r.allocationRows)if(row.mode==='budgetPct')close(row.amountWon,r.allowableWon*row.value/100);}
});
test('automatic lowering recovers only to the retained request when costs fall',()=>{
 const x=input({}),low=calculateBudget(x,1000,300),recovered=calculateBudget(x,1000,100);
 close(low.appliedTargetMarginPct,-24);close(recovered.appliedTargetMarginPct,15);assert.equal(x.assumptions.targetMarginPct,15);assert.equal(recovered.targetAdjusted,false);
});
test('invalid cost input cannot yield an adjusted target or complete profit',()=>{
 const x=input({expenses:{construction:{mode:'amount',value:-1}}}),r=calculateBudget(x,1000,300);
 assert.equal(r.complete,false);assert.equal(r.appliedTargetMarginPct,null);assert.equal(r.profitWon,null);assert(r.fieldErrors.length);
});
test('exports recalculate priority fields without retaining live revenue-derived values',()=>{
 const x={...input({}),parcels:[],comparables:{landCases:[],revenueCases:[{id:'live',realtimeOnly:true,lon:127.1234567}]},financeEditor:{land:{mode:'amount',value:300}}};
 const live=calculateBudget(x,1000,300),snapshot={inputs:x,results:{budget:live}},saved=sanitizeSnapshot(snapshot).results.budget;
 assert.equal(live.targetAdjusted,true);
 for(const key of ['appliedTargetMarginPct','requestedAllowableWon','minimumRequiredBudgetWon','fixedExpenseWon','budgetExpensePct','allowableWon','profitWon'])assert.equal(saved[key],null,key);
 assert.equal(saved.requestedTargetMarginPct,15);assert.equal(saved.targetAdjustmentStatus,'pending');assert.equal(saved.targetAdjusted,false);
 x.financeEditor.revenue={mode:'amount',value:1000};
 const manual=sanitizeSnapshot(snapshot).results.budget;
 close(manual.appliedTargetMarginPct,-24);close(manual.fixedExpenseWon,310);assert.equal(manual.complete,true);
});
