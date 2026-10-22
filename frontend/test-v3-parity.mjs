import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {calculateLand} from './src/content/dashboard/land-comparison.mjs';
import {projectRevision} from './src/content/dashboard/revision-model.mjs';
const directory=path.dirname(fileURLToPath(import.meta.url));
const python=process.env.PF_TEST_PYTHON||'python';
const fixtures=JSON.parse(fs.readFileSync(path.join(directory,'test-v3-fixtures.json'),'utf8'));
const base=structuredClone(fixtures[0].input);
Object.assign(base,{unitPlan:[{id:'one',units:20,supplyAreaM2:100}],linkedScenario:{enabled:true,farPct:200,farDefaultPct:200,farMaxPct:500,areaMode:'manual',supplyAreaM2:100},budgetAllocation:{trustType:'management',trustRatePct:1},costs:[]});
Object.assign(base.assumptions,{revenueMethod:'median',revenueAdjustmentPct:0,discountPct:5,finalSalesPct:90});
base.comparables.revenueCases=[{id:'r1',houseManageNo:'one',announcementNo:'1',modelNo:'01',name:'검증 단지',supplyAreaM2:100,priceManwon:100000,date:'2025-05-01',legalDongCode:'1168010100'}];
const variations=[
 ['comparable-100',{}],
 ['comparable-factor',{revenue:{mode:'comparablePct',value:120},land:{mode:'comparablePct',value:80}}],
 ['manual-both',{revenue:{mode:'amount',value:1e10},land:{mode:'amount',value:4e9}}],
 ['expense-modes',{revenue:{mode:'amount',value:1e10},expenses:{construction:{mode:'amount',value:2e9},indirect:{mode:'budgetPct',value:5},sales:{mode:'revenuePct',value:3},tax:{mode:'amount',value:0},finance:{mode:'amount',value:1e8},trust:{mode:'revenuePct',value:1}}}],
 ['trust-amount',{expenses:{trust:{mode:'amount',value:123456789}}}],
 ['zero-revenue',{revenue:{mode:'amount',value:0},land:{mode:'amount',value:0}}],
 ['invalid-pct',{revenue:{mode:'comparablePct',value:201}}],
 ['missing-value',{revenue:{mode:'amount',value:null}}],
];
const finance=variations.map(([name,editor])=>({name,input:{...structuredClone(base),financeEditor:editor}}));
finance.push({name:'null-revenue',input:{...structuredClone(base),comparables:{...structuredClone(base.comparables),revenueCases:[]}}});
finance.push({name:'partial-land',input:{...structuredClone(base),parcels:structuredClone(fixtures.find(f=>f.name==='partial-group').input.parcels),comparables:{...structuredClone(base.comparables),landCases:[base.comparables.landCases[0]]}}});
const requests=[...fixtures,...finance];
const code="import json,sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[1]).parent/'tests'));from pf_engine import analyze;data=json.load(sys.stdin);json.dump([analyze(x['input'],partial=True) for x in data],sys.stdout,ensure_ascii=False,allow_nan=False)";
const response=spawnSync(python,['-X','utf8','-c',code,path.resolve(directory,'../backend')],{input:JSON.stringify(requests),encoding:'utf8',maxBuffer:20*1024*1024});
assert.equal(response.status,0,response.stderr);
const outputs=JSON.parse(response.stdout);
function approx(a,b,label){if(a===null||b===null||typeof a!=='number'||typeof b!=='number')assert.deepEqual(a,b,label);else assert(Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-12),`${label}: ${a} != ${b}`);}
for(const [index,fixture] of fixtures.entries())test('Python/JS land parity: '+fixture.name,()=>{
 const js=calculateLand(fixture.input),py=outputs[index].results.land;
 for(const field of ['representativeWon','partialRepresentativeWon'])approx(js[field],py[field],field);
 assert.deepEqual(js.caseDecisions,py.caseDecisions);assert.deepEqual(js.parcelProfiles,py.parcelProfiles);assert.deepEqual(js.parcelAssignments,py.parcelAssignments);
 assert.equal(js.groups.length,py.groups.length);
 for(const [i,g] of js.groups.entries()){assert.deepEqual(g.caseIds,py.groups[i].caseIds);approx(g.representativeWon,py.groups[i].representativeWon,'group');for(const f of ['n','median','mean','q1','q3'])approx(g.stats[f],py.groups[i].stats[f],f);}
});
for(const [index,fixture] of finance.entries())test('Python/JS finance parity: '+fixture.name,()=>{
 const py=outputs[index+fixtures.length],js=projectRevision(fixture.input,py,{offline:true}).results;
 for(const part of ['revenue','land'])for(const field of ['representativeWon','comparableWon'])approx(js[part][field],py.results[part][field],part+'.'+field);
 for(const field of ['fullNetRevenueWon','netRevenueWon'])approx(js.revenue[field],py.results.revenue[field],field);
 for(const field of ['revenueWon','allowableWon','landWon','trustWon','allocatedWon','knownAllocatedWon','overallocatedWon','profitWon','profitMarginPct','complete','requestedTargetMarginPct','appliedTargetMarginPct','requestedAllowableWon','minimumRequiredBudgetWon','fixedExpenseWon','budgetExpensePct','targetAdjusted','targetAdjustmentStatus'])approx(js.budget[field],py.results.budget[field],'budget.'+field);
 for(const [i,row] of js.budget.allocationRows.entries())approx(row.amountWon,py.results.budget.allocationRows[i].amountWon,row.id);
 if(fixture.name==='comparable-100'){assert.equal(js.revenue.representativeWon,2e10);assert.equal(js.land.representativeWon,2e9);}
 if(fixture.name==='comparable-factor'){assert.equal(js.revenue.representativeWon,2.4e10);assert.equal(js.land.representativeWon,1.6e9);}
 if(fixture.name==='manual-both'){assert.equal(js.revenue.representativeWon,1e10);assert.equal(js.land.representativeWon,4e9);assert.equal(js.land.groups[0].representativeWon,2e9);}
 if(fixture.name==='expense-modes')assert.equal(js.budget.profitWon,5.075e9);
});
