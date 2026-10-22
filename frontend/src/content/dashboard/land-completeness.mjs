// A confirmed subtotal never stands in for the acquisition price of all parcels.
export function landCompleteness(profiles=[],groups=[],assignments=[],complete=false,extraReasons=[]){
 const priced=new Set(groups.filter(g=>Number.isFinite(g.representativeWon)).map(g=>g.id));
 const parcelRows=profiles.map(profile=>{
  const parts=assignments.filter(a=>a.pnu===profile.pnu&&a.groupId),pricedParts=parts.filter(a=>priced.has(a.groupId));
  const full=profile.status==='ready'&&parts.length>0&&pricedParts.length===parts.length;
  return {pnu:profile.pnu,status:full?'priced':pricedParts.length?'partial':'held',reasons:[...(profile.reasons||[]),...parts.filter(a=>!priced.has(a.groupId)).map(a=>`${a.groupId.replace('|',' · ')} 비교사례 단가 미산출`)]};
 });
 return {complete,parcelCount:profiles.length,classificationReadyParcelCount:profiles.filter(p=>p.status==='ready').length,classificationHeldParcelCount:profiles.filter(p=>p.status!=='ready').length,
  pricedParcelCount:parcelRows.filter(p=>p.status==='priced').length,partiallyPricedParcelCount:parcelRows.filter(p=>p.status==='partial').length,unpricedParcelCount:parcelRows.filter(p=>p.status!=='priced').length,
  groupCount:groups.length,pricedGroupCount:priced.size,unpricedGroupCount:groups.length-priced.size,parcelRows,
  reasons:[...new Set([...extraReasons.filter(Boolean),...parcelRows.flatMap(p=>p.reasons),...(!profiles.length?['개발 대상 필지 미선택']:[])])]};
}

export function landAmountStatus(land={}){
 const c=land.completeness||landCompleteness(land.parcelProfiles,land.groups,land.parcelAssignments,Number.isFinite(land.comparableWon??land.representativeWon),[land.comparisonReason]);
 const manual=land.appliedSetting?.mode==='amount'||land.editMode==='amount';
 const value=land.representativeWon,applied=Number.isFinite(value),partial=Number.isFinite(land.partialRepresentativeWon)?land.partialRepresentativeWon:null;
 const rawPct=land.appliedSetting?.value??land.editValue??100,pct=Number.isFinite(rawPct)&&rawPct>=0?rawPct:null;
 const fallbackUsed=!manual&&land.fallback?.used===true,fallbackSummary=fallbackUsed?`${land.fallback.groupCount}개 그룹 · ${land.fallback.parcelCount}필지 중앙값 대체`:'';
 return {status:applied?(manual?'manual':'complete'):'held',label:applied?(manual?'사용자 가정':fallbackUsed?'전체 산출 · 중앙값 대체 포함':'전체 산출'):'전체 산정 보류',appliedWon:applied?value:null,fallbackUsed,fallbackSummary,
  confirmedSubtotalWon:partial,adjustedSubtotalWon:!manual&&partial!==null&&pct!==null?partial*pct/100:null,
  summary:`${c.pricedParcelCount}/${c.parcelCount}필지 산출 · ${c.unpricedParcelCount}필지 미완료`,reasons:c.reasons,completeness:c};
}
