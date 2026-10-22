import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {rollingPeriod,applyRollingPeriod,rollingPeriodValid,todayKorea} from './src/content/dashboard/period-policy.mjs';
import {createSelectionSession,canAutoQuery,confirmSelectedQuery} from './src/content/dashboard/selection-query.mjs';
import {comparisonRequest,comparisonIdentity,invalidateChangedComparisons,createComparisonRequestGate} from './src/content/dashboard/comparison-scope.mjs';
import {periodErrors,DRAFT_KEY,makeDraft,restoreDraft} from './src/content/dashboard/ui-workflow.mjs';
import {calculateLand,landLinkageContext} from './src/content/dashboard/land-comparison.mjs';
import {sanitizeSnapshot} from './src/content/dashboard/v2-policy.mjs';
import {mergeSurveyParcels} from './src/content/dashboard/parcel-recovery.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./test-v3-fixtures.json',import.meta.url),'utf8'));
const original=()=>structuredClone(fixtures.find(f=>f.name==='residential-and-jimok').input);
const selected=()=>applyRollingPeriod(original(),'2026-10-10');

test('exact 60 complete months advance together and retain exclusive first day',()=>{
 assert.deepEqual(rollingPeriod('2026-10-01'),{periodMode:'rolling60',start:'2021-10',end:'2026-09',startDate:'2021-10-01',endDate:'2026-09-30',endExclusive:'2026-10-01',asOf:'2026-10-01',timezone:'Asia/Seoul',months:60});
 const next=rollingPeriod('2026-11-01');assert.equal(next.startDate,'2021-11-01');assert.equal(next.endDate,'2026-10-31');assert.equal(next.endExclusive,'2026-11-01');
 for(const day of ['2026-01-01','2024-03-01','2025-03-31']){const p=rollingPeriod(day);assert.equal((+p.end.slice(0,4)-+p.start.slice(0,4))*12+(+p.end.slice(5)-+p.start.slice(5))+1,60);}
 assert.equal(rollingPeriod('2024-03-01').endDate,'2024-02-29');assert.equal(rollingPeriod('2025-03-31').endDate,'2025-02-28');
});
test('Korea midnight controls rollover independently of host timezone',()=>{
 assert.equal(todayKorea(new Date('2026-10-31T14:59:59Z')),'2026-10-31');assert.equal(todayKorea(new Date('2026-10-31T15:00:00Z')),'2026-11-01');
 assert.equal(rollingPeriod(todayKorea(new Date('2026-10-31T15:00:00Z'))).endExclusive,'2026-11-01');
});
test('query uses confirmed parcel PNU region and fixed dates without coverage API',()=>{
 const x=selected(),q=comparisonRequest(x);assert.equal(q.periodMode,'rolling60');assert.equal(q.endExclusive,'2026-10-01');assert.equal(q.landStart,q.revenueStart);assert.equal(q.landEnd,q.revenueEnd);assert.equal(q.selectedPnus,x.parcels[0].pnu);assert.equal(q.legalDongCode,x.parcels[0].pnu.slice(0,10));assert.equal(q.sgg,x.parcels[0].pnu.slice(0,5));assert.equal(periodErrors(x,null).length,0);
 assert.equal(periodErrors(x,{revenue:{minMonth:'2025-01',maxMonth:'2025-12'}}).length,0,'observed API range cannot truncate requested five-year window');
});
test('invalid inclusive boundary or shortened period is rejected before request',()=>{
 for(const edit of [{landEndDate:'2026-10-01'},{revenueStart:'2022-10'},{endExclusive:'2026-10-02'},{landEnd:'2026-10'}]){const x=selected();Object.assign(x.comparisonFilters,edit);assert.equal(rollingPeriodValid(x),false);assert.throws(()=>comparisonRequest(x),/60개월/);}
});
test('startup and snapshot/draft restoration never arm automatic source queries',()=>{
 const x=selected(),session=createSelectionSession(),conditions={local:true,pending:true};assert.equal(canAutoQuery(x,session,conditions),false);
 const restored=restoreDraft(makeDraft(x));assert.equal(canAutoQuery(restored,session,conditions),false);
 session.arm(x.parcels);assert.equal(canAutoQuery(x,session,conditions),true);
 session.reset();assert.equal(canAutoQuery(x,session,conditions),false);
 session.arm([]);assert.equal(canAutoQuery({...x,parcels:[]},session,conditions),false);
 assert.equal(DRAFT_KEY,'pf-study-input-draft-v5');
});
test('unknown region waits for lookup recovery; multiple dongs and wrong selection block',()=>{
 const x=selected(),session=createSelectionSession(),conditions={local:true,pending:true};const unknown={...x,parcels:[{pnu:x.parcels[0].pnu}]};session.arm(unknown.parcels);
 assert.equal(canAutoQuery(unknown,session,conditions),false);assert.equal(canAutoQuery(x,session,conditions),true);
 for(const overrides of [{local:false},{printing:true},{parcelPending:true},{busy:true},{preparing:true},{pending:false}])assert.equal(canAutoQuery(x,session,{...conditions,...overrides}),false);
 const other={...x,parcels:[...x.parcels,{pnu:'1165010800100010001',dong:'서초동'}]};assert.equal(canAutoQuery(other,session,conditions),false);session.arm(other.parcels);assert.equal(canAutoQuery(other,session,conditions),false);
});
test('restoring same parcels invalidates old survey/comparison session tickets',()=>{
 const x=selected(),session=createSelectionSession();session.arm(x.parcels);const ticket=session.ticket();assert.equal(session.accepts(ticket,x.parcels),true);session.reset();session.arm(x.parcels);assert.equal(session.accepts(ticket,x.parcels),false);
});

test('explicit query recovers saved selection without changing parcels or inputs',()=>{
 const input=selected(),before=JSON.stringify(input),session=createSelectionSession();
 assert.equal(session.allows(input.parcels),false);
 assert.equal(confirmSelectedQuery(input.parcels,session,{local:true}),true);
 assert.equal(session.allows(input.parcels),true);assert.equal(JSON.stringify(input),before);
 const ticket=session.ticket();
 assert.equal(confirmSelectedQuery(input.parcels,session,{local:true}),true);
 assert.equal(session.accepts(ticket,input.parcels),true,'same-selection retry must not invalidate other active requests');
 session.reset();assert.equal(session.accepts(ticket,input.parcels),false);
});

test('explicit confirmation is unavailable without live connection or valid selected parcels',()=>{
 const input=selected();
 for(const [parcels,state] of [[input.parcels,{}],[input.parcels,{local:true,printing:true}],[input.parcels,{local:true,parcelPending:true}],[[],{local:true}],[[{pnu:'invalid'}],{local:true}]]){
  const session=createSelectionSession();assert.equal(confirmSelectedQuery(parcels,session,state),false);assert.equal(session.allows(input.parcels),false);
 }
});

test('financial numeric adjustments do not invalidate the query identity or arm an automatic request',()=>{
 const input=selected(),session=createSelectionSession();confirmSelectedQuery(input.parcels,session,{local:true});
 const changed={...input,linkedScenario:{...input.linkedScenario,farPct:250},assumptions:{...input.assumptions,targetMarginPct:12.5}};
 assert.equal(comparisonIdentity(input),comparisonIdentity(changed));
 assert.equal(canAutoQuery(changed,session,{local:true,pending:false}),false);
});

test('successful query rows survive source replacement and same-selection survey enrichment',()=>{
 const input=selected();
 const rows=[{id:'verified-current-model',eligible:true}],source={id:'applyhome',status:'complete'};
 const received=invalidateChangedComparisons(input,{...input,comparables:{...input.comparables,revenueCases:rows,query:comparisonRequest(input)},sources:[source]});
 assert.equal(received.comparables.revenueCases,rows);
 const parcels=mergeSurveyParcels(received.parcels,received.parcels.map(p=>({...p,officialLandPrice:{status:'success',rows:[]}})),'2026');
 const enriched=invalidateChangedComparisons(received,{...received,parcels});
 assert.equal(enriched.comparables.revenueCases,rows);assert.equal(enriched.sources[0],source);
});
test('month change invalidates old rows and cannot accept prior response',()=>{
 const a=selected(),b=applyRollingPeriod(a,'2026-11-01'),gate=createComparisonRequestGate(),ticket=gate.start(comparisonIdentity(a));assert.equal(gate.accepts(ticket,b),false);
 const invalid=invalidateChangedComparisons(a,b);assert.equal(invalid.comparables.landCases.length,0);assert.equal(invalid.comparables.revenueCases.length,0);assert.equal(invalid.comparables.query,undefined);
 assert.equal(a.comparables.landCases.length,4);assert.equal(a.comparisonFilters.endExclusive,'2026-10-01');
});
test('historical saved results preserve actual evidence period until next selection',()=>{
 const old=original(),before=JSON.stringify(old),safe=sanitizeSnapshot({schemaVersion:1,inputs:old,results:{}});assert.equal(JSON.stringify(old),before);assert.equal(safe.inputs.comparables.landQuery.start,old.comparables.query.start);assert.equal(safe.inputs.comparisonFilters.start,old.comparisonFilters.start);
 const x=selected();x.comparables.query={...comparisonRequest(x),asOf:x.project.asOf};x.comparables.landQuery=x.comparables.query;
 const saved=sanitizeSnapshot({schemaVersion:1,inputs:x,results:{}});assert.equal(saved.inputs.comparables.landQuery.endExclusive,'2026-10-01');assert.equal(saved.inputs.comparisonFilters.landEndDate,'2026-09-30');assert.equal(calculateLand(saved.inputs).representativeWon,2e9);
});
test('offline land calculation checks exact boundary and retains excluded rows',()=>{
 const x=selected();x.comparables.query={...comparisonRequest(x),asOf:x.project.asOf};x.comparables.landQuery=x.comparables.query;
 x.comparables.landCases=[{...x.comparables.landCases[0],id:'in',date:'2026-09-30'},{...x.comparables.landCases[0],id:'out',date:'2026-10-01'},{...x.comparables.landCases[0],id:'early',date:'2021-09-30'}];
 assert.equal(landLinkageContext(x).reason,null);const r=calculateLand(x);assert.deepEqual(r.groups[0].caseIds,['in']);assert.equal(r.caseDecisions.length,3);
 x.comparables.landQuery={...x.comparables.query,endExclusive:'2026-11-01'};assert.match(landLinkageContext(x).reason,/60개월/);
});
