import {classifyZone} from './land-classification.mjs';
import {boundaryEvidenceMatches} from './boundary-binding.mjs';

export const BOUNDARY_VERSION='boundary-overlay-v1';
const finite=Number.isFinite,positive=value=>finite(value)&&value>0;
const unique=values=>[...new Set(values)];
const clone=value=>JSON.parse(JSON.stringify(value));

export function toleratedAdjacentZones(areas,expected,adjacent,tolerance){
 const extra=Object.keys(areas).filter(code=>!expected.has(code));
 if(!expected.size||!extra.length||extra.some(code=>!adjacent.has(code)||!finite(areas[code])||areas[code]<0))return new Set();
 return extra.reduce((sum,code)=>sum+areas[code],0)<=tolerance?new Set(extra):new Set();
}

// Public cadastral/plan boundaries are retained separately from Geocoder results.
// The browser validates saved area evidence. Python repeats the actual polygon
// overlay from the raw geometries before accepting a live or saved analysis.
export function validBoundaryGeometry(geometry){
 if(!geometry||!['Polygon','MultiPolygon'].includes(geometry.type))return false;
 const polygons=geometry.type==='Polygon'?[geometry.coordinates]:geometry.coordinates;
 return Array.isArray(polygons)&&polygons.length>0&&polygons.every(polygon=>Array.isArray(polygon)&&polygon.length>0&&polygon.every(ring=>Array.isArray(ring)&&ring.length>=4&&ring.every(point=>Array.isArray(point)&&point.length>=2&&finite(point[0])&&finite(point[1])&&point[0]>=120&&point[0]<=134&&point[1]>=30&&point[1]<=40)&&ring[0][0]===ring.at(-1)[0]&&ring[0][1]===ring.at(-1)[1]));
}
const canonical=value=>JSON.stringify(value&&typeof value==='object'?Array.isArray(value)?value.map(v=>JSON.parse(canonical(v))):Object.fromEntries(Object.keys(value).sort().map(key=>[key,JSON.parse(canonical(value[key]))])):value??null);
export function boundaryAttributeBasis(parcel={}){
 const attrs=parcel.attributes||{},rows=(key,fields)=>(Array.isArray(attrs[key]?.rows)?attrs[key].rows:[]).filter(row=>row&&typeof row==='object'&&!Array.isArray(row)).map(row=>Object.fromEntries(fields.map(key=>[key,row[key]??null]))).sort((a,b)=>canonical(a)<canonical(b)?-1:canonical(a)>canonical(b)?1:0);
 return {pnu:String(parcel.pnu||''),landUse:rows('landUse',['pnu','prposAreaDstrcCode','prposAreaDstrcCodeNm','cnflcAt','cnflcAtNm','lastUpdtDt']),landRegister:rows('landRegister',['pnu','lndpclAr','lndcgrCode','lndcgrCodeNm','lastUpdtDt'])};
}
export function boundaryAttributeIdentity(parcel){
 return canonical([boundaryAttributeBasis(parcel),parcel?.areaM2??null,parcel?.attributes?.landRegister?.status,parcel?.attributes?.landUse?.status]);
}
export function validateBoundaryAllocation(parcel={}){
 const allocation=parcel.boundaryAllocation;
 if(!allocation||typeof allocation!=='object')return {status:'held',reasons:['필지·용도지역 경계 조회 필요'],parts:[]};
 const reasons=[],pnu=String(parcel.pnu||''),rawParts=Array.isArray(allocation.parts)?allocation.parts:[];
 const fail=message=>reasons.push(message);
 if(allocation.version!==BOUNDARY_VERSION||!/^\d{19}$/.test(pnu)||String(allocation.pnu||'')!==pnu)fail('경계 자료의 버전 또는 PNU 불일치');
 if(allocation.status!=='ready')reasons.push(...(Array.isArray(allocation.reasons)&&allocation.reasons.length?allocation.reasons:['경계 누락·충돌 확인 필요']));
 const source=allocation.source||{},register=parcel.attributes?.landRegister||{},registerRows=Array.isArray(register.rows)?register.rows:[];
 const layers=['LT_C_UQ111','LT_C_UQ112','LT_C_UQ113','LT_C_UQ114'];
 if(source.crs!=='EPSG:4326'||source.parcelLayer!=='LP_PA_CBND_BUBUN')fail('경계 출처 또는 좌표계 미확인');
 if(source.complete!==true||canonical([...(source.zoningLayers||[])].sort())!==canonical(layers))fail('필지·용도지역 경계 페이지 수집 미완료');
 const pages=source.pages;
 if(!Array.isArray(pages)||canonical(unique(pages.map(row=>row?.layer)).sort())!==canonical(['LP_PA_CBND_BUBUN',...layers].sort()))fail('경계 페이지 검증 근거 미확보');
 else if(pages.some(row=>!row||row.complete!==true||row.totalCount!==row.rawCount||!Number.isInteger(row.pageCount)||row.pageCount<1))fail('경계 페이지 누락 또는 건수 불일치');
 if(canonical(allocation.attributeBasis)!==canonical(boundaryAttributeBasis(parcel)))fail('경계 조회 당시와 현재 필지 속성 불일치: 재조회 필요');
 if(!allocation.parcelFeature||String(allocation.parcelFeature.properties?.pnu)!==pnu||canonical(allocation.parcelFeature.geometry)!==canonical(allocation.parcelGeometry))fail('필지 경계 원자료의 PNU·도형 불일치');
 if(Array.isArray(pages)&&Array.isArray(allocation.sourceFeatures)&&pages.some(row=>layers.includes(row?.layer)&&row.uniqueCount!==allocation.sourceFeatures.filter(f=>f.sourceLayer===row.layer).length))fail('저장된 용도지역 경계 건수 불일치');
 if(allocation.status!=='ready')return {...allocation,status:'held',reasons:unique(reasons),parts:rawParts};
 if(!boundaryEvidenceMatches(allocation))fail('저장된 원경계와 면적 계산 근거 불일치: Python 재조회 필요');
 if(!validBoundaryGeometry(allocation.parcelGeometry)||!Array.isArray(allocation.sourceFeatures)||!allocation.sourceFeatures.length||allocation.sourceFeatures.some(f=>!validBoundaryGeometry(f?.geometry)))fail('경계 원도형 미확보 또는 좌표 형식 오류');
 if(!source.queriedAt||!['EPSG:4326','urn:ogc:def:crs:EPSG::4326'].includes(source.crs))fail('경계 출처·시점·좌표계 미확정');
 const registerAreas=registerRows.map(row=>Number(String(row?.lndpclAr??'').replaceAll(',',''))),registerArea=registerAreas.length===1&&positive(registerAreas[0])?registerAreas[0]:null;
 if(register.status==='failed'||register.status==='partial'||register.status==='조회 실패'||registerArea===null)fail('현재 대장 면적 미확보 또는 충돌');
 if(registerRows.some(row=>row?.pnu&&String(row.pnu)!==pnu))fail('선택 필지와 대장 면적 PNU 불일치');
 if(!positive(allocation.registerAreaM2)||registerArea===null||Math.abs(allocation.registerAreaM2-registerArea)>1e-6)fail('경계 계산 당시와 현재 대장 면적 불일치');
 if(!positive(parcel.areaM2)||registerArea===null||Math.abs(parcel.areaM2-registerArea)>Math.max(.01,registerArea*1e-8))fail('계산용 면적과 현재 대장 면적 불일치');
 const geometryArea=allocation.parcelGeometryAreaM2,tolerance=positive(geometryArea)?Math.max(.01,geometryArea*1e-8):.01;
 if(!positive(geometryArea))fail('필지 도형 면적 미확정');
 if(!finite(allocation.gapAreaM2)||allocation.gapAreaM2<0||allocation.gapAreaM2>tolerance)fail('필지 내부 용도지역 경계 누락');
 if(!finite(allocation.overlapAreaM2)||allocation.overlapAreaM2<0||allocation.overlapAreaM2>tolerance)fail('서로 다른 용도지역 경계 중복·충돌');
 if(!finite(allocation.coverageRatio)||!positive(geometryArea)||Math.abs(1-allocation.coverageRatio)*geometryArea>tolerance)fail('용도지역 경계가 필지 전체를 덮지 않음');
 const planning=parcel.attributes?.landUse||{},planRows=Array.isArray(planning.rows)?planning.rows:[],expected=new Set(),adjacent=new Set();
 if(!planRows.length||['failed','partial','조회 실패'].includes(planning.status))fail('현재 토지이용계획 용도지역 미확보');
 for(const row of planRows){
  const zone=classifyZone(row?.prposAreaDstrcCodeNm,row?.prposAreaDstrcCode),relation=String(row?.cnflcAt||'');
  const relationName=String(row?.cnflcAtNm||'').trim(),validRelation=!relationName||relationName===({'1':'포함','2':'저촉','3':'접함'})[relation];
  if(zone.status==='ready'&&validRelation){if(['1','2'].includes(relation))expected.add(zone.code);else if(relation==='3')adjacent.add(zone.code);}
 }
 const tolerated=toleratedAdjacentZones(Object.fromEntries(rawParts.map(part=>[part?.zoneCode,part?.geometryAreaM2])),expected,adjacent,tolerance);
 const actual=new Set(),parts=[];let sumRatio=0,sumArea=0;
 if(!rawParts.length)fail('필지 안 용도지역 교차 면적 미확보');
 for(const part of rawParts){
  const zone=classifyZone(part?.zoneName,part?.zoneCode);
  // 비교그룹(zoneMatchKey)은 저장값을 믿지 않고 지금 규칙으로 코드에서 다시 정한다 (그룹 규칙이 바뀌어도 예전 저장 경계를 그대로 검증).
  if(zone.status!=='ready')fail('경계 용도지역 코드·명칭 불일치');
  if(!expected.has(zone.code)&&!tolerated.has(zone.code))fail('경계 용도지역과 현재 토지이용계획 불일치');
  if((part?.pricingExcluded===true)!==tolerated.has(zone.code))fail('접함 경계 미세 교차 제외 근거 불일치: Python 재계산 필요');
  if(actual.has(zone.code))fail('같은 용도지역 교차 면적 중복');
  actual.add(zone.code);
  if(!validBoundaryGeometry(part?.geometry)||!positive(part?.geometryAreaM2)||!positive(part?.ratio)||part.ratio>1+1e-10)fail('용도지역 교차 도형·비율 미확정');
  if(!positive(geometryArea)||Math.abs(part.geometryAreaM2-part.ratio*geometryArea)>tolerance)fail('교차 면적과 비율 불일치');
  const area=registerArea===null?null:registerArea*part.ratio;
  if(!positive(part?.allocatedAreaM2)||!positive(area)||Math.abs(part.allocatedAreaM2-area)>Math.max(.000001,registerArea*1e-10))fail('대장 면적 배분값 불일치');
  sumRatio+=finite(part?.ratio)?part.ratio:0;sumArea+=finite(part?.geometryAreaM2)?part.geometryAreaM2:0;
  parts.push({...clone(part),zoneMatchKey:zone.matchKey,ratio:part?.ratio,allocatedAreaM2:area,areaM2:area});
 }
 if([...expected].some(code=>!actual.has(code)))fail('현재 적용 용도지역의 경계 누락');
 if(!positive(geometryArea)||Math.abs(1-sumRatio)*geometryArea>tolerance||Math.abs(sumArea-geometryArea)>tolerance)fail('면적 비율 합계 미완결');
 return {...allocation,status:reasons.length?'held':'ready',reasons:unique(reasons),parts,registerAreaM2:registerArea,validationMode:'저장된 경계 근거 검증 · Python에서 도형 재계산',toleranceAreaM2:tolerance};
}

// Track each parcel independently; deselection, reload and new requests invalidate
// old tickets even when a late response arrives for the same PNU.
export function createBoundaryRequestGate(){
 let version=0;const tickets=new Map();
 return {
  start(pnu,identity){const key=String(pnu);tickets.get(key)?.controller.abort();const ticket={pnu:key,identity,version:++version,controller:new AbortController()};tickets.set(key,ticket);return ticket;},
  current(ticket,parcel){return tickets.get(ticket.pnu)===ticket&&!!parcel&&boundaryAttributeIdentity(parcel)===ticket.identity;},
  accepts(ticket,parcel){return this.current(ticket,parcel)&&!ticket.controller.signal.aborted;},
  finish(ticket){if(tickets.get(ticket.pnu)!==ticket)return false;tickets.delete(ticket.pnu);return true;},
  has(pnu){return tickets.has(String(pnu));},
  cancel(pnu){if(pnu==null){for(const ticket of tickets.values())ticket.controller.abort();tickets.clear();return;}tickets.get(String(pnu))?.controller.abort();tickets.delete(String(pnu));},
 };
}
