import {boundaryAttributeIdentity,validateBoundaryAllocation} from './boundary-allocation.mjs';

// Python may revalidate retained raw boundaries without a new external query.
// Adopt only verified evidence for the unchanged parcel/attribute identity.
export function adoptAnalyzedBoundaries(input,analyzedInput){
 const byPnu=new Map((analyzedInput?.parcels||[]).map(p=>[String(p.pnu),p]));
 let changed=false;
 const parcels=(input.parcels||[]).map(parcel=>{
  const analyzed=byPnu.get(String(parcel.pnu));
  if(!analyzed||boundaryAttributeIdentity(parcel)!==boundaryAttributeIdentity(analyzed))return parcel;
  const allocation=analyzed.boundaryAllocation;
  if(allocation?.status!=='ready'||JSON.stringify(allocation)===JSON.stringify(parcel.boundaryAllocation))return parcel;
  const updated={...parcel,boundaryAllocation:allocation};
  if(validateBoundaryAllocation(updated).status!=='ready')return parcel;
  changed=true;return updated;
 });
 return changed?{...input,parcels}:input;
}
