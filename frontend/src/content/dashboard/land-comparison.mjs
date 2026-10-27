import {rollingQueryValid} from './period-policy.mjs';
// V4 keeps source evidence separate from the current comparison decision.
export const LAND_RULE_VERSION='land-match-v7-48-groups-1';
import {ZONE_OTHER,JIMOK_OTHER,ZONE_GROUPS,JIMOK_GROUPS,classifyZone,classifyJimok,classifyTransactionZone,classifyTransactionJimok,landGroupLabel} from './land-classification.mjs';
import {validateBoundaryAllocation} from './boundary-allocation.mjs';
import {landReferenceTargets,addLandReferenceCase} from './land-reference.mjs';
import {landCompleteness} from './land-completeness.mjs';
export {ZONE_OTHER,JIMOK_OTHER,ZONE_GROUPS,JIMOK_GROUPS,classifyZone,classifyJimok,landGroupLabel};
const clone=x=>JSON.parse(JSON.stringify(x)),unique=x=>[...new Set(x)],positive=x=>typeof x!=='boolean'&&x!==null&&x!==''&&Number.isFinite(Number(x))&&Number(x)>0?Number(x):null;
export function parcelProfile(parcel){
 const reasons=[],zones=[],adjacent=[],categories=[];
 const isRecord=value=>!!value&&typeof value==='object'&&!Array.isArray(value),rawAttrs=parcel.attributes,attrs=isRecord(rawAttrs)?rawAttrs:{};
 if(rawAttrs!=null&&!isRecord(rawAttrs))reasons.push('필지 속성 원자료 형식 오류');
 const component=(name,label)=>{const raw=attrs[name],source=isRecord(raw)?raw:{},rawRows=Object.hasOwn(source,'rows')?source.rows:[],malformed=(raw!=null&&!isRecord(raw))||!Array.isArray(rawRows)||rawRows.some(row=>!isRecord(row));if(malformed)reasons.push(label+' 원자료 행 형식 오류');return [source,Array.isArray(rawRows)?rawRows.filter(isRecord):[],clone(rawRows)];};
 const [register,regRows,regRaw]=component('landRegister','토지임야대장'),[planning,zoneRows,zoneRaw]=component('landUse','토지이용계획');
 if(!/^\d{19}$/.test(String(parcel.pnu||'')))reasons.push('19자리 필지고유번호 미확정');
 if([...regRows,...zoneRows].some(r=>r.pnu&&String(r.pnu)!==String(parcel.pnu||'')))reasons.push('선택 필지와 속성 원자료 PNU 불일치');
 if(['조회 실패','failed','partial'].includes(register.status)||!regRows.length)reasons.push('현재 토지임야대장 지목 미확보');
 else for(const row of regRows){const category=classifyTransactionJimok(row.lndcgrCodeNm,row.lndcgrCode);categories.push(category);if(!['ready','missing'].includes(category.status))reasons.push('대장 지목 코드·명칭 미확정');if(category.status==='missing'&&!['호출 확인','complete','ready','success'].includes(register.status))reasons.push('지목 누락을 확인할 현재 대장 조회 완료 근거 미확보');}
 if(['조회 실패','failed','partial'].includes(planning.status)||!zoneRows.length)reasons.push('현재 토지이용계획 용도지역 미확보');
 else for(const row of zoneRows){
  const zone=classifyZone(row.prposAreaDstrcCodeNm,row.prposAreaDstrcCode);
  if(zone.status==='unknown'){if(/^(UQA|UQB|UQC|UQD)/.test(String(row.prposAreaDstrcCode||''))&&!['UQA01X','UQA001'].includes(row.prposAreaDstrcCode)){
   if(String(row.cnflcAt||'')==='3'&&['','접함'].includes(String(row.cnflcAtNm||'').trim()))adjacent.push(clone(row));
   else reasons.push('분류되지 않은 용도지역 코드');
  }continue;}
  const relation=String(row.cnflcAt||''),relationName=String(row.cnflcAtNm||'').trim(),expected={'1':'포함','2':'저촉','3':'접함'}[relation];
  if(!expected||(relationName&&relationName!==expected)){reasons.push('용도지역 포함·저촉·접함 관계 미확정');continue;}
  if(relation==='3'){adjacent.push(clone(row));continue;}
  if(zone.status!=='ready')reasons.push('용도지역 코드·명칭 불일치');else zones.push(zone);
 }
 const zoneKeys=unique(zones.map(z=>z.matchKey).filter(Boolean)).sort(),categoryNames=unique(categories.map(j=>j.name).filter(Boolean)).sort();
 const categoryKeys=unique(categories.map(j=>j.matchKey).filter(Boolean)).sort(),missingCategory=categories.some(j=>j.status==='missing');
 if(!zoneKeys.length)reasons.push('선택 필지의 적용 용도지역 미확정');if(zoneKeys.length>1)reasons.push('혼합 용도지역·면적 배분 미확인');
 if(!categoryKeys.length)reasons.push('선택 필지의 지목 미확정');if(categoryNames.length>1||(missingCategory&&categoryNames.length))reasons.push('대장 지목이 여러 값으로 확인됨');
 const allReasons=unique(reasons),status=!allReasons.length?'ready':zoneKeys.length>1||categoryNames.length>1||allReasons.some(x=>x.includes('불일치'))?'ambiguous':'missing',pnu=String(parcel.pnu||'');
 return {pnu,status,ruleVersion:LAND_RULE_VERSION,zoneMatchKey:zoneKeys.length===1&&!allReasons.length?zoneKeys[0]:null,jimokMatchKey:categoryKeys.length===1&&!allReasons.length?categoryKeys[0]:null,zoneBroadClasses:unique(zones.map(z=>z.broadClass)).sort(),jimokRaw:categoryNames,jimokStatus:missingCategory?'missing':categoryNames.length?'known':'unclassified',jimokGroupKeys:categoryKeys,zoneRawRows:zoneRaw,jimokRawRows:regRaw,adjacentRows:adjacent,sourceBasis:{zoning:'current-land-use-plan',jimok:'current-land-register',historicalReconstruction:false,planningStatus:Object.hasOwn(planning,'status')?planning.status:'미확보',registerStatus:Object.hasOwn(register,'status')?register.status:'미확보',planningQueriedAt:planning.queriedAt??null,registerQueriedAt:register.queriedAt??null,planningUpdatedAt:unique(zoneRows.map(r=>r.lastUpdtDt).filter(Boolean).map(String)).sort(),registerUpdatedAt:unique(regRows.map(r=>r.lastUpdtDt).filter(Boolean).map(String)).sort()},reasons:allReasons,fingerprint:JSON.stringify([LAND_RULE_VERSION,pnu,status,zoneKeys,categoryNames,allReasons])};
}
export function parcelAreaProfile(parcel){
 const base=parcelProfile(parcel),boundary=validateBoundaryAllocation(parcel);
 const reasons=unique([...base.reasons.filter(reason=>reason!=='혼합 용도지역·면적 배분 미확인'),...(boundary.status==='ready'?[]:boundary.reasons)]);
 const categories=base.jimokGroupKeys,status=reasons.length?'missing':'ready';
 const jimokMatchKey=categories.length===1?categories[0]:null;
 const allocations=status==='ready'?boundary.parts.filter(part=>!part.pricingExcluded).map((part,index)=>({allocationId:part.allocationId||`${parcel.pnu}:${part.zoneCode||part.zoneName}:${index}`,zoneMatchKey:part.zoneMatchKey,zoneName:part.zoneName,zoneCode:part.zoneCode,ratio:part.ratio,areaM2:part.allocatedAreaM2,geometryAreaM2:part.geometryAreaM2,geometry:part.geometry})):[];
 return {...base,status,reasons,jimokMatchKey:status==='ready'?jimokMatchKey:null,zoneMatchKey:status==='ready'&&new Set(allocations.map(part=>part.zoneMatchKey)).size===1?allocations[0].zoneMatchKey:null,boundaryStatus:boundary.status,areaAllocations:allocations};
}
function stats(values){
 const x=values.filter(Number.isFinite).sort((a,b)=>a-b),n=x.length,q=p=>{const k=(n-1)*p,i=Math.floor(k);return x[i]+(x[Math.min(i+1,n-1)]-x[i])*(k-i);};
 if(!n)return {n:0,min:null,q1:null,median:null,mean:null,q3:null,max:null,iqr:null,whiskerLow:null,whiskerHigh:null,outliers:[],showBox:false,status:'비교사례 없음'};
 const q1=q(.25),median=q(.5),q3=q(.75),iqr=q3-q1,inside=x.filter(v=>v>=q1-1.5*iqr&&v<=q3+1.5*iqr);
 return {n,min:x[0],q1,median,mean:x.reduce((a,b)=>a+b/n,0),q3,max:x.at(-1),iqr,whiskerLow:inside[0],whiskerHigh:inside.at(-1),outliers:x.filter(v=>v<inside[0]||v>inside.at(-1)),showBox:n>=5,status:n<5?'사례 부족':x[0]===x.at(-1)?'동일 금액 관측':'산출 완료'};
}
function canonicalDong(value){const parts=String(value||'').trim().split(/\s+/).filter(Boolean);return /리$/.test(parts.at(-1)||'')&&parts.length>1&&/[읍면]$/.test(parts.at(-2))?parts.slice(-2).join(' '):parts.at(-1)||'';}
function sameDong(a,b){a=canonicalDong(a);b=canonicalDong(b);return !!(a&&b&&a===b&&!(/리$/.test(a)&&!a.includes(' ')));}
const period=record=>[record.landStart||record.start,record.landEnd||record.end],validMonth=x=>/^\d{4}-(0[1-9]|1[0-2])$/.test(x||'');
export function landLinkageContext(input){
 const f=input.comparisonFilters||{},comp=input.comparables||{},query=comp.landQuery||comp.query||{},active=Object.keys(query).length||['sgg','dong','start','end','landStart','revenueStart','selectionLinked'].some(k=>k in f);
 if(!active)return null;
 const result={reason:null,query,legalDongCode:null},parcels=input.parcels||[],fail=reason=>({...result,reason});
 if(!parcels.length)return fail('개발 대상 필지를 선택해야 비교사례와 예상 금액을 계산할 수 있습니다.');
 const codes=new Set(),names=new Set();
 for(const p of parcels){const pnu=String(p.pnu||''),code=String(p.legalDongCode||'');if(!/^\d{19}$/.test(pnu)||(code&&(!/^\d{10}$/.test(code)||code!==pnu.slice(0,10))))return fail('선택 필지의 PNU·법정동코드를 확인한 뒤 비교사례를 다시 조회하세요.');codes.add(pnu.slice(0,10));const name=canonicalDong(p.dong||p.legalDongName);if(name)names.add(name);}
 if(codes.size!==1)return fail('선택 필지가 서로 다른 법정동에 걸쳐 있습니다. 현재는 같은 법정동의 필지만 함께 분석할 수 있습니다.');
 const code=[...codes][0];result.legalDongCode=code;
 const expected=['sgg','dong','start','end','landStart','revenueStart'].some(k=>k in f)?f:query,sgg=String(expected.sgg||''),dong=expected.dong,expectedCode=String(expected.legalDongCode||'');
 if(sgg!==code.slice(0,5)||(expectedCode&&expectedCode!==code)||[...names].some(name=>!sameDong(name,dong)))return fail('선택 필지와 비교 지역이 다릅니다. 필지의 시군구·법정동으로 비교사례를 다시 조회하세요.');
 if(!Object.keys(query).length)return fail('선택 필지·지역·기간에 맞는 비교사례를 다시 조회하세요.');
 if(!sameDong(expected.dong,query.dong)||String(expected.sgg||'')!==String(query.sgg||'')||JSON.stringify(period(expected))!==JSON.stringify(period(query)))return fail('비교 지역·기간이 변경되었습니다. 현재 조건으로 비교사례를 다시 조회하세요.');
 if(!period(query).every(validMonth)||period(query)[0]>period(query)[1])return fail('비교사례의 조회 기간을 확인하고 다시 조회하세요.');
 if(f.periodMode==='latest'&&(query.periodMode!=='latest'||query.landStartDate!=='2006-01-01'||['landStartDate','landEndDate'].some(k=>f[k]&&f[k]!==query[k])))return fail('최신 범위의 시작·종료일이 변경되었습니다. 비교사례를 다시 조회하세요.');
 if((f.periodMode==='rolling60'||query.periodMode==='rolling60')&&(!rollingQueryValid(query,'land')||['landStartDate','landEndDate','endExclusive'].some(k=>f[k]&&f[k]!==query[k])))return fail('완료된 60개월의 시작·종료 경계가 변경되었습니다. 필지 선택 후 비교사례를 다시 조회하세요.');
 if(query.asOf&&String(query.asOf)!==String(expected.asOf||input.project?.asOf||''))return fail('분석 기준일이 변경되었습니다. 현재 기준일로 비교사례를 다시 조회하세요.');
 if((f.landScope||'dong')!==(query.landScope||'dong')&&query.landRawScope!=='sgg')return fail('토지 비교 범위가 변경되었습니다. 시군구 원자료를 다시 조회하세요.');
 return result;
}
function dateReason(row,input,context){
 const value=row.date;if(!value)return context?'거래일 미확정':null;
 if(!/^\d{4}-\d{2}-\d{2}$/.test(value)||Number.isNaN(Date.parse(value))||new Date(value+'T00:00:00Z').toISOString().slice(0,10)!==value)return '거래일 미확정';
 if(input.project?.asOf&&value>input.project.asOf)return '분석 기준일 이후 거래';
 if(context){const q=context.query;if((q.landStartDate&&value<q.landStartDate)||(q.landEndDate&&value>q.landEndDate)||(q.endExclusive&&value>=q.endExclusive)||(q.periodMode==='latest'&&value<'2006-01-01'))return '조회 일자 범위 밖 사례';const [start,end]=period(context.query);if(!start||!end||value.slice(0,7)<start||value.slice(0,7)>end)return '조회 기간 밖 토지거래';}
 return null;
}
function isIncomplete(input){
 const bad=['partial','failed','수집 미완료','조회 실패'],statuses=[input.comparables?.landQuery?.collectionStatus,input.comparables?.landCollectionStatus,...(input.sources||[]).filter(s=>s?.id==='land').flatMap(s=>[s.collectionStatus,s.status])];
 if(statuses.some(s=>bad.includes(s)))return true;if(statuses.includes('complete')||statuses.includes('최신 조회 완료'))return false;
 return [input.collectionStatus,input.comparables?.landCollectionStatus,input.comparables?.collectionStatus].some(s=>bad.includes(s));
}
export function calculateLand(input){
 const ac=input.assumptions||{},method=ac.landMethod||'median',filters=input.comparisonFilters||{},context=landLinkageContext(input),query=context?.query||{},scope=filters.landScope||query.landScope||'dong';
 const fieldErrors=[],rawAdjustment=ac.landAdjustmentPct??0,adjustment=Number.isFinite(rawAdjustment)&&rawAdjustment>-100?1+rawAdjustment/100:null;
 if(!['median','mean'].includes(method))fieldErrors.push({section:'land',path:'assumptions.landMethod',message:'토지 대표값은 중앙값 또는 평균을 선택하세요.'});
 if(!['dong','sgg'].includes(scope))fieldErrors.push({section:'land',path:'comparisonFilters.landScope',message:'토지 비교 범위를 확인하세요.'});
 if(adjustment===null)fieldErrors.push({section:'land',path:'assumptions.landAdjustmentPct',message:'토지가격 보정률은 -100%보다 커야 합니다.'});
 const reason=context?.reason||null,incomplete=isIncomplete(input),profiles=[],groups=new Map(),assignments=[],seenParcels=new Set();
 let totalArea=0,missingArea=false;
 for(const p of input.parcels||[]){
  const pnu=String(p.pnu||'');if(seenParcels.has(pnu))continue;seenParcels.add(pnu);
  const profile=parcelAreaProfile(p),area=positive(p.areaM2);profiles.push(profile);if(area===null)missingArea=true;else totalArea+=area;
  if(profile.status!=='ready'){assignments.push({pnu,groupId:null,areaM2:area,status:profile.status,reasons:profile.reasons});continue;}
  for(const part of profile.areaAllocations){
   const groupId=`${part.zoneMatchKey}|${profile.jimokMatchKey}`;
   assignments.push({pnu,groupId,areaM2:part.areaM2,status:'ready',reasons:[],allocationId:part.allocationId,zoneName:part.zoneName,zoneCode:part.zoneCode,zoneMatchKey:part.zoneMatchKey,jimokMatchKey:profile.jimokMatchKey,ratio:part.ratio,geometryAreaM2:part.geometryAreaM2,geometry:part.geometry});
   if(!groups.has(groupId))groups.set(groupId,{id:groupId,label:landGroupLabel(part.zoneMatchKey,profile.jimokMatchKey),zoneMatchKey:part.zoneMatchKey,jimokMatchKey:profile.jimokMatchKey,areaM2:0,missingArea:false,parcelPnus:[],points:[],caseIds:[],unknownZoneCount:0,knownZoneCount:0,unknownJimokCount:0,knownJimokCount:0});
   const g=groups.get(groupId);if(!g.parcelPnus.includes(pnu))g.parcelPnus.push(pnu);g.areaM2+=part.areaM2;
  }
 }
 const referenceGroups=landReferenceTargets((input.parcels||[]).map(parcelProfile));
 const decisions=[],excluded=[],seenCases=new Set(),fallbackDonors=[];
 for(const [i,c] of (input.comparables?.landCases||[]).entries()){
  const id=String(c.id||`land-${i}`),reasons=[];if(reason)reasons.push(reason);if(incomplete)reasons.push('부분 수집: 전체 표본 판정 보류');if(seenCases.has(id))reasons.push('같은 거래 식별자 중복');seenCases.add(id);
  if(c.cancelled===true||c.cancellationDate)reasons.push('취소 거래');if(c.shareTrade===true||!['','전체','전체거래','전체 거래','N','0','-'].includes(String(c.shareDealingType||'').trim()))reasons.push('지분 거래 또는 거래 범위 확인 필요');
  if(c.sourceEligible===false)reasons.push(...(c.sourceExclusionReasons?.length?c.sourceExclusionReasons:['수집 검증 제외']));
  else if(!('sourceEligible' in c)&&(c.apiEligible===false||(!c.manualExclusion&&(c.baseEligible??c.eligible)===false)))reasons.push(c.baseExclusionReason||c.exclusionReason||'수집 검증 제외');
  if(c.userExcluded||c.manualExclusion)reasons.push(c.userExclusionReason||c.manualExclusionReason||c.baseExclusionReason||c.exclusionReason||'사용자 제외');
  const area=positive(c.areaM2),price=positive(c.priceManwon),unit=area&&price?price*10000/area:null;if(!area||!price)reasons.push('양수 금액·거래면적 미확보');const dateIssue=reason?null:dateReason(c,input,context);if(dateIssue)reasons.push(dateIssue);
  if(context){if(String(c.sggCode||'')!==String(query.sgg||''))reasons.push('선택 필지의 시군구 밖 거래 또는 지역 미확정');else if(scope==='dong'&&!sameDong(c.dong,query.dong))reasons.push('선택 필지의 법정동 밖 토지거래 또는 거래 지역 미확정');}
  if(String(filters.jimok||'').trim()&&String(c.jimok||'').trim()!==String(filters.jimok).trim())reasons.push('사용자 지목 필터 불일치');
  if(String(filters.landUse||'').trim()&&!String(c.landUse||'').includes(String(filters.landUse).trim()))reasons.push('사용자 용도지역 필터 불일치');
  const baseReasons=[...reasons],zone=classifyTransactionZone(c.landUse,c.landUseCode),jimok=classifyTransactionJimok(c.jimok,c.jimokCode);if(!['ready','missing'].includes(zone.status))reasons.push('거래 용도지역 코드·명칭 미확정');if(!['ready','missing'].includes(jimok.status))reasons.push('거래 지목 코드·명칭 미확정');if(!Number.isFinite(unit)||unit<=0)reasons.push('유효한 거래 단가 미확보');const groupId=zone.matchKey&&jimok.matchKey?`${zone.matchKey}|${jimok.matchKey}`:null,fallbackEligible=!reasons.length&&!!groupId;
  // Keep donor admission independent of whether its group is a selected target.
  // Direct group eligibility and observed case counts retain their original meaning.
  if(fallbackEligible)fallbackDonors.push({id,groupId,unitPriceWonM2:unit});
  if(!groups.has(groupId))reasons.push('선택 필지의 용도지역·지목 비교군과 불일치');
  const issues=unique(reasons),decision={id,eligible:!issues.length,groupId:groups.has(groupId)?groupId:null,fallbackEligible,fallbackGroupIds:[],reasons:issues,exclusionReason:issues.join(' · '),zoneMatchKey:zone.matchKey,jimokMatchKey:jimok.matchKey,classificationBasis:{ruleVersion:LAND_RULE_VERSION,zone:clone(zone),jimok:clone(jimok),missingPolicy:'missing-zone-fourth-group;missing-jimok-other-group',fallbackUsed:false}};decisions.push(decision);
  addLandReferenceCase(referenceGroups,c,decision,baseReasons);
  if(issues.length)excluded.push({id,reason:decision.exclusionReason,reasons:issues});else{const g=groups.get(groupId),unit=price*10000/area,base=g.missingArea?null:unit*g.areaM2,value=base!==null&&adjustment!==null?base*adjustment:null;g.points.push({id,label:String(c.date||id),unitPriceWonM2:unit,baseValueWon:Number.isFinite(base)?base:null,valueWon:Number.isFinite(value)?value:null,caseIds:[id],zoningStatus:decision.zoningStatus,jimokStatus:decision.jimokStatus,landUse:String(c.landUse||''),jimok:String(c.jimok||'')});g.caseIds.push(id);g[zone.status==='missing'?'unknownZoneCount':'knownZoneCount']++;g[jimok.status==='missing'?'unknownJimokCount':'knownJimokCount']++;}
 }
 for(const g of groups.values()){
  if(g.missingArea)g.areaM2=null;delete g.missingArea;g.stats=stats(g.points.map(p=>p.valueWon));g.baseStats=stats(g.points.map(p=>p.baseValueWon));g.unitPriceStats=stats(g.points.map(p=>p.unitPriceWonM2));
  g.fallback={used:false};g.representativeUnitPriceWonM2=g.unitPriceStats[method]??null;
  if(!g.points.length&&g.areaM2!==null&&!reason&&!incomplete&&!fieldErrors.length){
   const donors=fallbackDonors.filter(row=>row.groupId!==g.id),median=stats(donors.map(row=>row.unitPriceWonM2)).median;
   if(Number.isFinite(median)){
    const sourceGroupIds=unique(donors.map(row=>row.groupId));
    g.fallback={used:true,policy:'valid-other-groups-median',reason:'동일 그룹 비교사례 없음 · 중앙값 대체',sourceCaseCount:donors.length,sourceGroupCount:sourceGroupIds.length,sourceGroupIds,sourceCaseIds:donors.map(row=>row.id),unitPriceWonM2:median};
    g.representativeUnitPriceWonM2=median;
   }
  }
  const value=Number.isFinite(g.representativeUnitPriceWonM2)&&g.areaM2!==null&&adjustment!==null?g.representativeUnitPriceWonM2*g.areaM2*adjustment:null;
  g.representativeWon=Number.isFinite(value)?value:null;g.status=reason?'토지사례 재조회 필요':g.areaM2===null?'대장 면적 미확보':g.fallback.used?g.fallback.reason:g.stats.status;
 }
 for(const decision of decisions){
  decision.fallbackGroupIds=[...groups.values()].filter(group=>group.fallback.used&&group.fallback.sourceCaseIds.includes(decision.id)&&decision.fallbackEligible).map(group=>group.id);
  decision.classificationBasis.fallbackUsed=decision.fallbackGroupIds.length>0;
 }
 for(const assignment of assignments){
  if(!assignment.groupId)continue;
  const group=groups.get(assignment.groupId),unit=group?.representativeUnitPriceWonM2,applied=Number.isFinite(unit)&&adjustment!==null?unit*adjustment:null;
  assignment.fallback=clone(group?.fallback||{used:false});assignment.representativeUnitPriceWonM2=unit??null;assignment.appliedUnitPriceWonM2=applied;assignment.representativeWon=applied===null?null:applied*assignment.areaM2;
 }
 const boundaryParts=assignments.filter(assignment=>assignment.allocationId).map(assignment=>({...assignment,allocatedAreaM2:assignment.areaM2,estimatedWon:assignment.representativeWon,pricingStatus:assignment.representativeWon===null?'비교사례 확인 필요':assignment.fallback?.used?'동일 그룹 비교사례 없음 · 중앙값 대체':'산출 완료'}));
 const referenceRows=[...referenceGroups.values()].map(group=>{const directStats=stats(group.points.map(p=>p.unitPriceWonM2)),priced=groups.get(group.id);return {...group,stats:directStats,representativeUnitPriceWonM2:priced?.representativeUnitPriceWonM2??directStats[method]??null,fallback:clone(priced?.fallback||{used:false})};});
 const rows=[...groups.values()],complete=!!profiles.length&&profiles.every(p=>p.status==='ready')&&!!rows.length&&rows.every(g=>g.representativeWon!==null)&&!reason&&!incomplete&&!fieldErrors.length,partial=rows.reduce((n,g)=>n+(g.representativeWon??0),0),covered=rows.filter(g=>g.representativeWon!==null).reduce((n,g)=>n+(g.areaM2||0),0),total=missingArea||!profiles.length?null:totalArea;
 const fallbackGroups=rows.filter(group=>group.fallback.used),sourceCaseIds=unique(fallbackGroups.flatMap(group=>group.fallback.sourceCaseIds)),sourceGroupIds=unique(fallbackGroups.flatMap(group=>group.fallback.sourceGroupIds));
 const fallback={used:fallbackGroups.length>0,policy:'valid-other-groups-median',groupCount:fallbackGroups.length,parcelCount:unique(assignments.filter(row=>row.fallback?.used).map(row=>row.pnu)).length,sourceCaseCount:sourceCaseIds.length,groupIds:fallbackGroups.map(group=>group.id),sourceCaseIds,sourceGroupIds,sourceGroupCount:sourceGroupIds.length};
 const completeness=landCompleteness(profiles,rows,assignments,complete,[reason,incomplete?'토지거래 수집 미완료':null,...fieldErrors.map(e=>e.message)]);
 return {groups:rows,referenceGroups:referenceRows,fallback,referencePolicy: 'same-48-groups-v1',representativeWon:complete?partial:null,partialRepresentativeWon:rows.some(g=>g.representativeWon!==null)?partial:null,completeness,excluded,caseDecisions:decisions,parcelProfiles:profiles,parcelAssignments:assignments,boundaryParts,coverage:{coveredAreaM2:covered,totalAreaM2:total,coveredPct:total?covered/total*100:null,unresolvedParcelCount:profiles.filter(p=>p.status!=='ready').length},comparisonReason:reason,comparisonScope:scope,ruleVersion:LAND_RULE_VERSION,matchingMode:'custom-48-groups',method,matchingPolicy:{zoneGroups:[...ZONE_GROUPS],jimokGroups:[...JIMOK_GROUPS,JIMOK_OTHER],missingZoneGroup:ZONE_OTHER,missingJimokGroup:JIMOK_OTHER,noCasePolicy:'valid-other-groups-median',boundaryPolicy:'hold-missing-or-conflicting-evidence'},label:rows.length>1?'사용자 지정 비교군 대표액 합계':'예상 토지매입대금',status:reason?'토지사례 재조회 필요':incomplete?'부분 수집 · 판정 보류':complete?(fallback.used?'산출 완료 · 중앙값 대체 포함':'산출 완료'):'필지 분류·비교사례 확인 필요',sourceStatus:'공개자료 기반 추정',assumption:'같은 지역·용도지역·지목 비교군 우선. 동일 그룹 사례가 없으면 다른 유효 그룹 거래 단가 중앙값 대체. 경제적 동질성·개발 가능성 보장이 아님',fieldErrors};
}
export function assessLandCases(input){const decisions=calculateLand(input).caseDecisions;return (input.comparables?.landCases||[]).map((row,i)=>({...row,...decisions[i]}));}
