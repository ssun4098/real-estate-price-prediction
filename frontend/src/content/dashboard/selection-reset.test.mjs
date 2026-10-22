import test from 'node:test';
import assert from 'node:assert/strict';
import {cancelSelectionWork,clearedSelectionInputs} from './selection-reset.mjs';
import {createSelectionSession,canAutoQuery} from './selection-query.mjs';
import {comparisonIdentity,createComparisonRequestGate,invalidateChangedComparisons} from './comparison-scope.mjs';
import {createBoundaryRequestGate} from './boundary-allocation.mjs';

test('clear invalidates pending parcel, comparison, survey and analysis responses before emptying selection',()=>{
 const parcels=[{pnu:'4127110100100010000',areaM2:100}],input={parcels,project:{asOf:'2026-10-11'},comparisonFilters:{},comparables:{revenueCases:[{id:'old'}],landCases:[{id:'old-land'}]},assumptions:{targetMarginPct:15},financeEditor:{construction:{mode:'budgetPct',value:60}}};
 const session=createSelectionSession();session.arm(parcels);const sessionTicket=session.ticket();
 const comparisons=createComparisonRequestGate(),comparisonTicket=comparisons.start(comparisonIdentity(input));
 const boundaries=createBoundaryRequestGate(),boundaryTicket=boundaries.start(parcels[0].pnu,'pending');
 const refs={comparisonGate:{current:comparisons},selectionToken:{current:new Map([[parcels[0].pnu,'old-token']])},boundaryGate:{current:boundaries},boundaryAttempts:{current:new Map([[parcels[0].pnu,'attempt']])},selectionSession:{current:session},surveySequence:{current:5},coverageSequence:{current:3},requestVersion:{current:8},runSequence:{current:2},casePreparing:{current:true},autoQueryPending:{current:true}};
 cancelSelectionWork(refs);
 const cleared=invalidateChangedComparisons(input,clearedSelectionInputs(input));
 assert.deepEqual(cleared.parcels,[]);assert.deepEqual(cleared.comparables.revenueCases,[]);assert.deepEqual(cleared.comparables.landCases,[]);
 assert.equal(cleared.assumptions,input.assumptions);assert.equal(cleared.financeEditor,input.financeEditor);
 assert.equal(comparisonTicket.controller.signal.aborted,true);assert.equal(boundaryTicket.controller.signal.aborted,true);
 assert.equal(comparisons.accepts(comparisonTicket,input),false);assert.equal(session.accepts(sessionTicket,parcels),false);assert.equal(refs.selectionToken.current.size,0);
 assert.equal(refs.surveySequence.current,6);assert.equal(refs.requestVersion.current,9);assert.equal(refs.casePreparing.current,false);assert.equal(refs.autoQueryPending.current,false);
 assert.equal(canAutoQuery(cleared,session,{local:true,pending:true}),false);
 assert.equal(input.parcels.length,1);assert.equal(input.comparables.revenueCases.length,1);
});
