/** Invalidate every selection-dependent response before changing the parcels. */
export function cancelSelectionWork(refs){
 refs.comparisonGate.current.cancel();
 refs.selectionToken.current.clear();
 refs.boundaryGate.current.cancel();
 refs.boundaryAttempts.current.clear();
 refs.selectionSession.current.reset();
 for(const key of ['surveySequence','coverageSequence','requestVersion','runSequence'])refs[key].current++;
 refs.casePreparing.current=false;
 refs.autoQueryPending.current=false;
}

/** Keep manually entered development/finance assumptions for the next selection. */
export function clearedSelectionInputs(input){
 return {...input,parcels:[],comparables:{revenueCases:[],landCases:[]}};
}
