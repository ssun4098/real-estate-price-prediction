import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {adoptAnalyzedBoundaries} from './src/content/dashboard/boundary-adoption.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./test-v3-fixtures.json',import.meta.url),'utf8'));
const base=()=>structuredClone(fixtures[0].input);
test('verified Python boundary correction is adopted once without changing user inputs',()=>{
 const result=base(),input=base();input.parcels[0].boundaryAllocation.status='held';
 input.financeEditor={land:{mode:'amount',value:12345}};
 const updated=adoptAnalyzedBoundaries(input,result);
 assert.equal(updated.parcels[0].boundaryAllocation.status,'ready');
 assert.deepEqual(updated.financeEditor,input.financeEditor);
 assert.equal(input.parcels[0].boundaryAllocation.status,'held');
 assert.equal(adoptAnalyzedBoundaries(updated,result),updated);
});
test('stale parcel identity or changed area cannot adopt Python evidence',()=>{
 for(const mutate of [p=>p.pnu='9999999999999999999',p=>p.areaM2+=100,p=>p.attributes.landUse.rows[0].cnflcAt='3']){
  const input=base(),result=base();mutate(result.parcels[0]);assert.equal(adoptAnalyzedBoundaries(input,result),input);
 }
});
test('held or tampered recalculation evidence is not adopted',()=>{
 for(const mutate of [p=>p.boundaryAllocation.status='held',p=>p.boundaryAllocation.parts[0].allocatedAreaM2=1]){
  const input=base(),result=base();mutate(result.parcels[0]);assert.equal(adoptAnalyzedBoundaries(input,result),input);
 }
});
