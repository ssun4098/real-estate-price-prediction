import {validateBoundaryAllocation} from './boundary-allocation.mjs';

export const boundaryNumber=(value,decimals=2)=>Number.isFinite(value)?value.toLocaleString('ko-KR',{maximumFractionDigits:decimals,minimumFractionDigits:decimals}):'—';
const colors=['#82b9dc','#b9a2df','#e1b870','#77c7ac','#ee92a9','#c9d778','#75cfdb','#c9b8a9'];
export function boundaryColor(key){let hash=0;for(const char of String(key||''))hash=(hash*31+char.charCodeAt(0))>>>0;return colors[hash%colors.length];}
export function boundaryView(parcels=[],land={}){
 const seen=new Set(),records=[];
 for(const parcel of parcels){if(!parcel||seen.has(parcel.pnu))continue;seen.add(parcel.pnu);const evidence=parcel.boundaryAllocation||{},check=validateBoundaryAllocation(parcel),pnu=String(parcel.pnu||''),number=records.length+1;
  const profile=(land.parcelProfiles||[]).find(p=>p.pnu===pnu),pricing=(land.completeness?.parcelRows||[]).find(p=>p.pnu===pnu),classificationHeld=profile&&profile.status!=='ready';
  const parts=(check.parts?.length?check.parts:Array.isArray(evidence.parts)?evidence.parts:[]).filter(p=>p&&typeof p==='object').map((part,index)=>{
   const candidates=(land.boundaryParts||land.parcelAssignments||[]).filter(row=>String(row.pnu)===pnu&&row.zoneName===part.zoneName&&(!row.zoneCode||!part.zoneCode||row.zoneCode===part.zoneCode));
   const amount=candidates.length===1?candidates[0]:null,ready=check.status==='ready',unit=ready&&Number.isFinite(amount?.appliedUnitPriceWonM2)?amount.appliedUnitPriceWonM2:null,fallback=ready&&!part.pricingExcluded&&!classificationHeld&&unit!=null&&amount?.fallback?.used?amount.fallback:{used:false};
   return {...part,id:`${pnu}:${part.zoneCode||part.zoneName}:${index}`,pnu,parcelNumber:number,address:parcel.address||pnu,color:boundaryColor(part.zoneCode||part.zoneName),status:check.status,
    allocatedAreaM2:ready&&!part.pricingExcluded&&Number.isFinite(part.allocatedAreaM2)?part.allocatedAreaM2:null,appliedUnitPriceWonM2:unit,estimatedWon:unit!=null&&Number.isFinite(amount?.estimatedWon??amount?.representativeWon)?amount.estimatedWon??amount.representativeWon:null,
    fallback,pricingStatus:!ready?'경계 검증 보류':part.pricingExcluded?'접함 미세 교차 · 금액 제외':classificationHeld?'필지 분류 검증 보류':unit==null?'비교사례 미산출':fallback.used?'동일 그룹 비교사례 없음 · 중앙값 대체':'사례 기준 · 조정 전'};
  });
  records.push({pnu,parcelNumber:number,address:parcel.address||pnu,status:check.status,reasons:check.reasons||[],pricingStatus:pricing?.status||null,pricingReasons:pricing?.reasons||profile?.reasons||[],evidence,parts});
 }
 return {records,parts:records.flatMap(p=>p.parts),readyCount:records.filter(p=>p.status==='ready').length,heldCount:records.filter(p=>p.status!=='ready').length};
}
export function boundaryPartText(part){return `${part.parcelNumber}번 · ${part.zoneName||'용도지역 미확인'} · ${part.pricingExcluded?'접함 미세 교차 · 금액 제외':Number.isFinite(part.allocatedAreaM2)?boundaryNumber(part.allocatedAreaM2)+'㎡':'배분 보류'} · ${Number.isFinite(part.ratio)?boundaryNumber(part.ratio*100)+'%':'비율 미확인'} · ${part.fallback?.used?'동일 그룹 비교사례 없음 · 중앙값 대체 단가':'사례 기준 단가'} ${part.pricingExcluded?'미적용':Number.isFinite(part.appliedUnitPriceWonM2)?boundaryNumber(part.appliedUnitPriceWonM2,0)+'원/㎡':'미산출'}`;}
