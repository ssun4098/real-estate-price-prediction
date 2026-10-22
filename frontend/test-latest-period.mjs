import test from 'node:test';
import assert from 'node:assert/strict';
import {applyLatestPeriod,periods} from './src/content/dashboard/period-policy.mjs';
import {periodErrors} from './src/content/dashboard/ui-workflow.mjs';
import {comparisonRequest,comparisonIdentity,createComparisonRequestGate,invalidateChangedComparisons} from './src/content/dashboard/comparison-scope.mjs';
const coverage={land:{minMonth:'2006-01',maxMonth:'2026-10'},revenue:{minMonth:'2020-02',maxMonth:'2026-10',observedMaxDate:'2026-10-08'},checkedAt:'2026-10-09T00:00:00Z',status:'observed_api'};
const base=()=>({project:{asOf:'2025-01-01'},comparisonFilters:{periodMode:'latest',sgg:'11650',dong:'서초동',scope:'dong'},parcels:[{pnu:'1165010800100010000',dong:'서초동',areaM2:100}],comparables:{revenueCases:[],landCases:[]}});
test('fixed starts and latest dates replace stale settings without touching source input',()=>{
 const input=base(),next=applyLatestPeriod(input,coverage,'2026-10-09');
 assert.equal(input.project.asOf,'2025-01-01');assert.equal(next.project.asOf,'2026-10-09');
 assert.deepEqual(periods(next),{landStart:'2006-01',landEnd:'2026-10',revenueStart:'2020-02',revenueEnd:'2026-10'});
 assert.equal(next.comparisonFilters.revenueStartDate,'2020-02-04');assert.equal(next.comparisonFilters.revenueEndDate,'2026-10-08');
 assert.equal(periodErrors(next,coverage).length,0);
 const request=comparisonRequest(next);assert.equal(request.periodMode,'latest');assert.equal(request.landStart,'2006-01');
});
test('old saved manual periods are retained',()=>{const input=base();input.comparisonFilters.periodMode='common';input.comparisonFilters.start='2025-01';input.comparisonFilters.end='2025-12';assert.equal(applyLatestPeriod(input,coverage),input)});
test('latest day changing within same month rejects an older response',()=>{
 const a=applyLatestPeriod(base(),coverage,'2026-10-09'),b=applyLatestPeriod(a,{...coverage,revenue:{...coverage.revenue,observedMaxDate:'2026-10-09'}},'2026-10-09');
 assert.notEqual(comparisonIdentity(a),comparisonIdentity(b));const gate=createComparisonRequestGate(),ticket=gate.start(comparisonIdentity(a));assert.equal(gate.accepts(ticket,b),false);
 const invalid=invalidateChangedComparisons(a,b);assert.equal(invalid.comparables.collectionStatus,'재조회 필요');
});
test('next month advances land end independently of last published revenue',()=>{
 const next=applyLatestPeriod(base(),coverage,'2026-11-01');assert.equal(next.comparisonFilters.landEnd,'2026-11');assert.equal(next.comparisonFilters.revenueEndDate,'2026-10-08');
});
test('latest date is not promoted into future',()=>{const next=applyLatestPeriod(base(),{...coverage,revenue:{...coverage.revenue,observedMaxDate:'2099-01-01'}},'2026-10-09');assert.equal(next.comparisonFilters.revenueEndDate,'2026-10-09')});
test('manual 60-month limit still protects legacy requests',()=>{const input=applyLatestPeriod(base(),coverage,'2026-10-09');input.comparisonFilters.periodMode='separate';assert.throws(()=>comparisonRequest(input),/60개월/);assert.ok(periodErrors(input,coverage).some(x=>x.message.includes('60개월')))});
