import {classifyZone,classifyTransactionZone,classifyTransactionJimok,landGroupLabel,classificationStatus} from './land-classification.mjs';
export {missingTransactionZone} from './land-classification.mjs';

// Reference distributions use the same 12 comparison groups as acquisition.
// They remain visible when boundary evidence prevents an amount calculation.
export function landReferenceTargets(profiles){
 const groups=new Map();
 for(const profile of profiles){
  if(profile.reasons.some(r=>r!=='혼합 용도지역·면적 배분 미확인')||profile.jimokGroupKeys.length!==1)continue;
  const jimokKey=profile.jimokGroupKeys[0];
  for(const row of profile.zoneRawRows){
   const zone=classifyZone(row.prposAreaDstrcCodeNm,row.prposAreaDstrcCode);
   if(zone.status!=='ready'||!['1','2'].includes(String(row.cnflcAt)))continue;
   const id=`${zone.matchKey}|${jimokKey}`;
   if(!groups.has(id))groups.set(id,{id,label:landGroupLabel(zone.matchKey,jimokKey),zoneMatchKey:zone.matchKey,jimokMatchKey:jimokKey,points:[],caseIds:[],unknownZoneCount:0,knownZoneCount:0,unknownJimokCount:0,knownJimokCount:0,referenceOnly:true});
  }
 }
 return groups;
}
export function addLandReferenceCase(groups,caseRow,decision,baseReasons){
 const zone=classifyTransactionZone(caseRow.landUse,caseRow.landUseCode),jimok=classifyTransactionJimok(caseRow.jimok,caseRow.jimokCode),missingZone=zone.status==='missing',reasons=[...baseReasons];
 if(!['ready','missing'].includes(jimok.status))reasons.push('거래 지목 코드·명칭 미확정');
 if(!['ready','missing'].includes(zone.status))reasons.push('거래 용도지역 분류 미확정 · 단순 누락과 구분');
 const matches=[...groups.values()].filter(g=>g.jimokMatchKey===jimok.matchKey&&g.zoneMatchKey===zone.matchKey);
 if(!matches.length)reasons.push(groups.size?'선택 필지의 용도지역·지목 참고군과 불일치':'선택 필지의 현재 분류 확인 필요');
 const unit=Number(caseRow.priceManwon)*10000/Number(caseRow.areaM2);
 if(!Number.isFinite(unit)||unit<=0)reasons.push('유효한 거래 단가 미확보');
 decision.referenceEligible=!reasons.length;decision.referenceGroupIds=decision.referenceEligible?matches.map(g=>g.id):[];decision.referenceReasons=[...new Set(reasons)];decision.zoningStatus=classificationStatus(zone);decision.jimokStatus=classificationStatus(jimok);
 if(!decision.referenceEligible)return;
 for(const group of matches){
  group.points.push({id:decision.id,label:String(caseRow.date||decision.id),unitPriceWonM2:unit,zoningStatus:decision.zoningStatus,jimokStatus:decision.jimokStatus,landUse:String(caseRow.landUse||''),jimok:String(caseRow.jimok||''),referenceOnly:true,caseIds:[decision.id]});
  group.caseIds.push(decision.id);group[missingZone?'unknownZoneCount':'knownZoneCount']++;
  group[jimok.status==='missing'?'unknownJimokCount':'knownJimokCount']++;
 }
}
