// Both parcel lookup and basic survey feed the same selected-parcel inputs.
export const hasManualArea = p => p.areaInputMode === 'manual' || !!p.areaInputNote || p.sourceStatus === '사용자 확인 입력';
export function parcelMissing(p) {
  const missing=[];
  if (!/^\d{19}$/.test(String(p.pnu||''))) missing.push('PNU');
  if (!String(p.legalDongName||p.dong||'').trim()) missing.push('법정동명');
  if (!Number.isFinite(p.areaM2)||p.areaM2<=0) missing.push('양수 대장·매입면적');
  return missing;
}
export function mergeParcelAttributes(current, incoming, year) {
  if (String(current.pnu)!==String(incoming?.pnu) || (current.attributeRequestedYear && String(current.attributeRequestedYear)!==String(year))) return current;
  const merged={...current};
  // Missing responses never erase already verified fields. Annual reference area
  // and public land price are not fallbacks for register area or purchase price.
  for (const [key,value] of Object.entries(incoming)) {
    if (['pnu','geometry','group','areaInputMode','areaInputNote','attributeState','attributeError','attributeRequestedYear','sourceStatus'].includes(key)) continue;
    if (value==null || value==='') continue;
    if (key==='areaM2' && (hasManualArea(current)||!Number.isFinite(value)||value<=0)) continue;
    merged[key]=value;
  }
  merged.attributeRequestedYear=String(year);
  if (hasManualArea(current)) {
    merged.areaInputMode='manual'; merged.areaM2=current.areaM2;
    merged.areaInputNote=current.areaInputNote;
  }
  const missing=parcelMissing(merged);
  merged.attributeState=missing.length?'partial':'ready';
  merged.attributeError=missing.length?`${missing.join('·')} 미확보 · 필지 정보를 다시 조회하거나 확인한 면적을 입력하세요.`:'';
  merged.sourceStatus=hasManualArea(merged)?'사용자 확인 입력':missing.length?'필지 정보 일부 미확보':'공개자료';
  return JSON.stringify(merged)===JSON.stringify(current)?current:merged;
}
export function mergeSurveyParcels(parcels, rows, year) {
  const byPnu=new Map((rows||[]).map(p=>[String(p.pnu),p]));
  let changed=false;
  const next=parcels.map(p=>{const row=byPnu.get(String(p.pnu));if(!row)return p;const value=mergeParcelAttributes(p,row,year);changed ||= value!==p;return value;});
  return changed?next:parcels;
}
export function failParcelLookup(parcel, message) {
  const complete=!parcelMissing(parcel).length;
  return {...parcel,attributeState:complete?'ready':'error',attributeError:message||'필지 조회에 실패했습니다. 다시 조회하세요.',sourceStatus:hasManualArea(parcel)?'사용자 확인 입력':complete?'공개자료 · 재조회 실패':'필지 조회 실패'};
}
export function setManualParcelArea(parcel, value) {
  const next={...parcel,areaM2:value,areaInputMode:'manual',sourceStatus:'사용자 확인 입력',areaInputNote:'대장 또는 매입 범위를 사용자가 확인한 면적'};
  if(!['loading','queued'].includes(next.attributeState)){
    const missing=parcelMissing(next);next.attributeState=missing.length?'partial':'ready';
    next.attributeError=missing.length?`${missing.join('·')} 미확보 · 필지 정보와 입력 면적을 확인하세요.`:'';
  }
  return next;
}
export function createTaskQueue(limit=2) {
  let active=0; const pending=[];
  const drain=()=>{while(active<limit&&pending.length){const {job,resolve,reject}=pending.shift();active++;Promise.resolve().then(job).then(resolve,reject).finally(()=>{active--;drain();});}};
  return {enqueue(job){return new Promise((resolve,reject)=>{pending.push({job,resolve,reject});drain();});}};
}
export async function retryBusy(operation,{attempts=3,wait=ms=>new Promise(r=>setTimeout(r,ms)),isCurrent=()=>true}={}) {
  for(let i=0;i<attempts;i++){
    if(!isCurrent())return null;
    try{return await operation();}catch(error){
      if(error.status!==429||i===attempts-1||!isCurrent())throw error;
      await wait(Math.min(5000,Math.max(1000,(error.retryAfterSeconds||1)*1000)*(i+1)));
    }
  }
}
