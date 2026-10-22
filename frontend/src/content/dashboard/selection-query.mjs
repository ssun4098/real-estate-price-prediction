import {selectedParcelRegion} from './comparison-scope.mjs';

const identity=parcels=>JSON.stringify([...new Set((parcels||[]).map(p=>String(p.pnu||'')))].sort());
/** Deliberately memory-only: loading a saved selection never grants API access. */
export function createSelectionSession(){
 let selected=null,generation=0;
 return {
  reset(){selected=null;generation++;},
  arm(parcels){selected=parcels?.length?identity(parcels):null;generation++;},
  allows(parcels){return selected!==null&&!!parcels?.length&&selected===identity(parcels);},
  ticket(){return generation;},
  accepts(ticket,parcels){return ticket===generation&&this.allows(parcels);}
 };
}
/** An explicit query button can confirm an already saved parcel selection.
 * Loading a document alone still cannot arm a session or spend API quota.
 * Keep an existing generation so concurrent current-selection work stays valid.
 */
export function confirmSelectedQuery(parcels,session,{local=false,printing=false,parcelPending=false}={}){
 if(!local||printing||parcelPending||!parcels?.length||parcels.some(p=>!/^\d{19}$/.test(String(p.pnu||''))))return false;
 if(!session.allows(parcels))session.arm(parcels);
 return true;
}
export function canAutoQuery(input,session,{local=false,printing=false,parcelPending=false,busy=false,preparing=false,pending=false}={}){
 return local&&!printing&&!parcelPending&&!busy&&!preparing&&pending&&session.allows(input.parcels)&&selectedParcelRegion(input.parcels).status==='ready';
}
