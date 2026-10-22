import {parcelProfile,classifyZone} from './land-comparison.mjs';

const record=value=>value&&typeof value==='object'&&!Array.isArray(value);
const rowsOf=(p,key)=>{const value=p?.attributes?.[key]??p?.[key];return (Array.isArray(value)?value:Array.isArray(value?.rows)?value.rows:[]).filter(record);};
const text=value=>String(value??'').trim();
const first=(row,fields)=>fields.map(field=>row?.[field]).find(value=>value!=null&&text(value)!=='');
const numeric=value=>value==null||typeof value==='boolean'||!text(value)||!Number.isFinite(Number(value))?null:Number(value);
export const uniqueSurveyParcels=parcels=>[...new Map((Array.isArray(parcels)?parcels:[]).filter(record).map((p,i)=>[p.pnu||`missing-${i}`,p])).values()];

/** A chart observation is a building, not a parcel or an arbitrary source row. */
export function buildingSummary(parcels){
 const groups=new Map(),unidentified=[],mismatched=[];
 for(const [pi,p] of uniqueSurveyParcels(parcels).entries())for(const [ri,row] of rowsOf(p,'buildings').entries()){
  const pnu=text(p.pnu),rowPnu=text(row.pnu);
  const evidence={...row,selectedPnu:pnu,parcelNumber:pi+1,sourceRow:ri+1};
  if(rowPnu&&rowPnu!==pnu){mismatched.push(evidence);continue;}
  const ids=['buldIdntfcNo','gisIdntfcNo','mgmBldrgstPk','manageNo'].map(field=>[field,text(row[field])]).filter(([,value])=>value);
  if(!ids.length){unidentified.push(evidence);continue;}
  const aliases=ids.map(([field,value])=>`${field}:${value}`),hits=[...groups.values()].filter(g=>aliases.some(id=>g.aliases.has(id)));
  let group=hits[0];
  if(!group){group={id:aliases[0],aliases:new Set(),records:[],parcelNumbers:new Set()};groups.set(group.id,group);}
  for(const duplicate of hits.slice(1)){for(const id of duplicate.aliases)group.aliases.add(id);group.records.push(...duplicate.records);for(const n of duplicate.parcelNumbers)group.parcelNumbers.add(n);groups.delete(duplicate.id);}
  aliases.forEach(id=>group.aliases.add(id));group.records.push(evidence);group.parcelNumbers.add(pi+1);
 }
 const buildings=[...groups.values()].map(group=>{
  const floors=[...new Set(group.records.map(row=>numeric(first(row,['groundFloorCo','grndFlrCnt','groundFloors']))).filter(value=>value!==null&&Number.isInteger(value)&&value>=0))];
  const areas=[...new Set(group.records.map(row=>numeric(first(row,['buldTotar','totArea','grossAreaM2']))).filter(value=>value!==null&&value>=0))];
  const name=group.records.map(row=>first(row,['buldNm','bldNm'])).find(Boolean),dongNames=[...new Set(group.records.map(row=>text(first(row,['buldDongNm','dongNm']))).filter(Boolean))];
  const identifierType=group.id.slice(0,group.id.indexOf(':')),identifier=group.id.slice(group.id.indexOf(':')+1);
  const dong=dongNames.map(value=>/^\d+$/.test(value)?`${value}동`:value).join('·');
  const displayName=[name,dong||`식별자 …${identifier.slice(-8)}`].filter(Boolean).join(' · ');
  return {id:group.id,identifier,identifierType,label:`${[...group.parcelNumbers].join('·')}번 / ${displayName}`,floors:floors.length===1?floors[0]:null,area:areas.length===1?areas[0]:null,
   floorStatus:floors.length>1?'충돌':floors.length?'확인':'미확인',sourceCount:group.records.length,sourceRows:group.records};
 });
 const known=buildings.filter(b=>b.floorStatus==='확인'),counts=new Map();
 known.forEach(b=>counts.set(b.floors,(counts.get(b.floors)||0)+1));
 const distribution=[...counts].sort((a,b)=>a[0]-b[0]).map(([floors,count])=>({label:`${floors}층`,floors,count,share:count/known.length}));
 const ranked=[...distribution].sort((a,b)=>b.count-a.count||a.floors-b.floors);
 const slices=distribution.length<=5?distribution:[...ranked.slice(0,4).sort((a,b)=>a.floors-b.floors),{label:'기타',count:ranked.slice(4).reduce((n,r)=>n+r.count,0),share:ranked.slice(4).reduce((n,r)=>n+r.share,0),floorCategories:ranked.slice(4).map(r=>r.label).join(', ')}];
 return {buildings,distribution,slices,knownCount:known.length,unknownCount:buildings.filter(b=>b.floorStatus==='미확인').length,conflictCount:buildings.filter(b=>b.floorStatus==='충돌').length,
  unidentifiedCount:unidentified.length,mismatchedCount:mismatched.length,unidentified,mismatched,duplicateCount:buildings.reduce((n,b)=>n+Math.max(0,b.sourceCount-1),0)};
}

/** Count each (parcel, designation) once; retain all original relationship rows. */
export function designationSummary(parcels,kind){
 const unique=uniqueSurveyParcels(parcels),counts=new Map(),evidence=[],adjacentNames=new Set();let assignments=0,multipleParcels=0,unknownParcels=0;
 for(const [pi,p] of unique.entries()){
  const profile=parcelProfile(p),failed=['error','failed','partial','조회 실패','unavailable'].includes(profile.sourceBasis.planningStatus),names=new Set();
  for(const row of (Array.isArray(profile.zoneRawRows)?profile.zoneRawRows:[]).filter(record)){
   const name=text(row.prposAreaDstrcCodeNm),code=text(row.prposAreaDstrcCode),relation=text(row.cnflcAt),expected={'1':'포함','2':'저촉','3':'접함'}[relation],actual=text(row.cnflcAtNm);
   const matchingKind=kind==='zone'?classifyZone(name,code).status==='ready':kind==='district'?/지구$/.test(name):/구역$/.test(name);
   if(!matchingKind)continue;
   const reason=failed?'조회 상태 미확정':row.pnu&&text(row.pnu)!==text(p.pnu)?'다른 필지 원자료':!expected||actual&&actual!==expected?'관계 미확정':relation==='3'?'접함 · 집계 제외':['UQA001','UQA01X'].includes(code)?'용도 미지정 · 집계 제외':names.has(name)?'같은 필지·같은 지정 중복':'집계 포함';
   if(reason==='집계 포함')names.add(name);
   if(reason==='접함 · 집계 제외')adjacentNames.add(name);
   evidence.push({parcelNumber:pi+1,pnu:p.pnu,designation:name,code,relation:actual||expected||'미확인',decision:reason,updatedAt:row.lastUpdtDt||'미확인',source:row});
  }
  if(names.size){assignments+=names.size;if(names.size>1)multipleParcels++;for(const name of names)counts.set(name,(counts.get(name)||0)+1);}
  else{unknownParcels++;counts.set('미확인',(counts.get('미확인')||0)+1);}
 }
 const adjacent=[...adjacentNames];
 return {rows:[...counts].map(([label,value])=>({label,value})),evidence,parcelCount:unique.length,assignments,multipleParcels,unknownParcels,adjacentNames:adjacent,
  note:`선택 ${unique.length}필지 · 포함·저촉 ${assignments}건${multipleParcels?` · 복수 지정 ${multipleParcels}필지`:''}${unknownParcels?` · 미확인 ${unknownParcels}필지`:''}. 같은 필지에 여러 지정이 있으면 합계가 필지 수를 넘습니다. ${adjacent.length?`접함 제외: ${adjacent.slice(0,2).join(', ')}${adjacent.length>2?` 외 ${adjacent.length-2}개`:''}.`:'접함은 제외.'}`};
}

/** Composition denominator is each category's assignment count plus unknown
 * parcels, never the number of selected parcels or all three category totals. */
export function designationComposition(parcels){
 return [['zone','용도지역'],['district','용도지구'],['useArea','용도구역']].map(([kind,title])=>{
  const summary=designationSummary(parcels,kind),total=summary.rows.reduce((sum,row)=>sum+row.value,0);
  return {...summary,kind,title,total,rows:summary.rows.map(row=>({...row,denominator:total,percentage:total>0?row.value/total*100:null}))};
 });
}
