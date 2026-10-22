import {isRolling,rollingPeriodValid} from './period-policy.mjs';
// Query geography belongs to the selected parcel geometry, never the map viewport.
export function selectedParcelCenter(parcels=[]){
 if(!parcels.length)return null;
 let minLon=Infinity,maxLon=-Infinity,minLat=Infinity,maxLat=-Infinity;
 for(const parcel of parcels){
  const geometry=parcel.geometry;
  const rings=geometry?.type==='Polygon'?geometry.coordinates:geometry?.type==='MultiPolygon'?geometry.coordinates?.flat(1):null;
  if(!Array.isArray(rings)||!rings.length)return null;
  let count=0;
  for(const ring of rings){
   if(!Array.isArray(ring)||ring.length<4)return null;
   for(const coordinate of ring){
    if(!Array.isArray(coordinate))return null;
    const [lon,lat]=coordinate;
    if(!Number.isFinite(lon)||!Number.isFinite(lat)||lon < -180||lon > 180||lat < -90||lat > 90)return null;
    minLon=Math.min(minLon,lon);maxLon=Math.max(maxLon,lon);minLat=Math.min(minLat,lat);maxLat=Math.max(maxLat,lat);count++;
   }
  }
  if(!count)return null;
 }
 return {lon:(minLon+maxLon)/2,lat:(minLat+maxLat)/2,bbox:[minLon,minLat,maxLon,maxLat]};
}

export function revenueScope(input){return input.comparisonFilters?.scope==='radius'?'radius':'dong';}
export function landScope(input){return input.comparisonFilters?.landScope==='sgg'?'sgg':'dong';}

export function parcelSelectionIdentity(parcels=[]){
 return JSON.stringify(parcels.map(p=>[String(p.pnu||''),p.geometry||null,p.legalDongName||'',p.dong||'']).sort((a,b)=>a[0].localeCompare(b[0])));
}

// PNU identifies the legal dong; names keep 읍·면·리 together for the land API.
export function selectedParcelRegion(parcels=[]){
 if(!parcels.length)return {status:'none',message:'개발 대상 필지를 선택하세요.'};
 const regions=parcels.map(p=>{
  const pnu=String(p.pnu||''),code=/^\d{19}$/.test(pnu)?pnu.slice(0,10):'';
  const full=String(p.legalDongName||'').trim().replace(/\s+/g,' '),parts=full.split(' ');
  let dong=full;
  const districtIndex=parts.findLastIndex(part=>/[시군구]$/.test(part));
  if(districtIndex>=0)dong=parts.slice(districtIndex+1).join(' ');
  if(!dong)dong=String(p.dong||'').trim();
  return {code,sgg:code.slice(0,5),dong,fullName:full||dong};
 });
 if(regions.some(r=>!r.code||!r.dong))return {status:'unknown',message:'선택 필지의 PNU·법정동명을 확인한 뒤 비교사례를 조회할 수 있습니다.'};
 const codes=[...new Set(regions.map(r=>r.code))];
 if(codes.length!==1)return {status:'multiple',message:'여러 법정동의 필지가 선택됐습니다. 현재 모델은 같은 법정동의 필지끼리 선택해야 비교사례를 조회할 수 있습니다.',names:[...new Set(regions.map(r=>r.fullName))]};
 if(new Set(regions.map(r=>r.dong)).size!==1)return {status:'unknown',message:'같은 PNU 법정동의 명칭이 서로 다릅니다. 필지 속성을 다시 확인하세요.'};
 return {status:'ready',legalDongCode:regions[0].code,sgg:regions[0].sgg,dong:regions[0].dong,fullName:regions[0].fullName};
}

export function synchronizeParcelSelection(previous,next){
 if(parcelSelectionIdentity(previous.parcels)===parcelSelectionIdentity(next.parcels))return next;
 const region=selectedParcelRegion(next.parcels);
 const filters={...next.comparisonFilters,sgg:region.sgg||'',dong:region.dong||'',legalDongCode:region.legalDongCode||'',selectionLinked:true};
 const currentSources=(next.parcels||[]).flatMap(p=>(p.sources||[]).map(s=>({...s,pnu:p.pnu,parcelAddress:p.address||p.legalDongName||p.pnu})));
 const oldParcelSources=new Set((previous.parcels||[]).flatMap(p=>(p.sources||[]).map(s=>JSON.stringify(s))));
 const retained=(next.sources||[]).filter(s=>!s.pnu&&!String(s.id||'').startsWith('ned-')&&!oldParcelSources.has(JSON.stringify(s))&&!['applyhome','land'].includes(s.id));
 return {...next,comparisonFilters:filters,sources:[...retained,...currentSources],
  comparables:{...next.comparables,geocodingStats:undefined,geocodingCollectionStatus:undefined,geocodingOutcomes:[],revenueCases:[],landCases:[],query:undefined,landQuery:undefined,collectionStatus:'필지 변경 · 재조회 필요'},
  collectionStatus:region.status==='ready'?'필지 변경 · 자동 조회 대기':region.message,
  selectionReviewRequired:true};
}

export function comparisonIdentity(input){
 const f=input.comparisonFilters||{},scope=revenueScope(input);
 const center=scope==='radius'?selectedParcelCenter(input.parcels):null;
 return JSON.stringify([f.sgg||'',f.dong||'',f.start||'',f.end||'',f.periodMode||'common',f.landStart||'',f.landEnd||'',f.revenueStart||'',f.revenueEnd||'',input.project?.asOf||'',f.landStartDate||'',f.landEndDate||'',f.revenueStartDate||'',f.revenueEndDate||'',f.endExclusive||'',scope,landScope(input),
  scope==='radius'?Number(f.radiusKm??5):null,
  f.legalDongCode||'',parcelSelectionIdentity(input.parcels),
  center?.lon??null,center?.lat??null]);
}
export function revenueComparisonIdentity(input){
 const f=input.comparisonFilters||{};
 return comparisonIdentity({...input,comparisonFilters:{...f,landScope:'dong',landStart:'',landEnd:''}});
}

export function invalidateChangedComparisons(previous,next){
 next=synchronizeParcelSelection(previous,next);
 if(comparisonIdentity(previous)===comparisonIdentity(next))return next;
 const before=previous.comparisonFilters||{},after=next.comparisonFilters||{};
 const selectionChanged=parcelSelectionIdentity(previous.parcels)!==parcelSelectionIdentity(next.parcels);
 const both=selectionChanged||previous.project?.asOf!==next.project?.asOf||['sgg','dong','legalDongCode','start','end','periodMode','landStart','landEnd','revenueStart','revenueEnd','landStartDate','landEndDate','revenueStartDate','revenueEndDate','endExclusive'].some(k=>(before[k]||'')!==(after[k]||''));
 const onlyLandScope=!both&&revenueScope(previous)===revenueScope(next)&&(before.radiusKm??5)===(after.radiusKm??5)&&landScope(previous)!==landScope(next);
 // The collector retains the entire district response. Switching the explicit
 // land scope can therefore reassess raw records without another network read.
 if(onlyLandScope&&(next.comparables?.landQuery||next.comparables?.query)?.landRawScope==='sgg')return {...next,comparables:{...next.comparables,query:{...next.comparables.query,landScope:landScope(next)},...(next.comparables.landQuery?{landQuery:{...next.comparables.landQuery,landScope:landScope(next)}}:{})}};
 const affected=new Set(both?['applyhome','land']:onlyLandScope?['land']:['applyhome']);
 const comparables={...next.comparables,...(!onlyLandScope?{geocodingStats:undefined,geocodingCollectionStatus:undefined,geocodingOutcomes:[],revenueCases:[]}:{}),...((both||onlyLandScope)?{landCases:[]}:{}),collectionStatus:'재조회 필요'};
 if(both){delete comparables.query;delete comparables.landQuery;}
 else if(onlyLandScope)delete comparables.landQuery;
 else if(comparables.query)comparables.query={...comparables.query,...(onlyLandScope?{landScope:undefined}:{scope:undefined})};
 return {...next,comparables,sources:(next.sources||[]).filter(s=>!affected.has(s.id)),
  collectionStatus:selectionChanged?next.collectionStatus:both?'지역·기간 변경 · 재조회 필요':'분양사례 범위 변경 · 재조회 필요'};
}

export function replaceComparisonSources(previous=[],incoming=[]){
 return [...previous.filter(s=>!['applyhome','land'].includes(s.id)),...incoming];
}

// One request per selection identity. Aborted/late responses never become current.
export function createComparisonRequestGate(){
 let active=null,version=0;
 return {
  cancel(){version++;active?.controller.abort();active=null;},
  start(identity){if(active?.identity===identity)return null;this.cancel();active={identity,controller:new AbortController(),version};return active;},
  accepts(ticket,input){return active===ticket&&!ticket.controller.signal.aborted&&ticket.version===version&&ticket.identity===comparisonIdentity(input);},
  finish(ticket){if(active!==ticket)return false;active=null;return true;}
 };
}

export function comparisonRequest(input,refresh=false){
 const f=input.comparisonFilters||{},scope=revenueScope(input);
 const region=selectedParcelRegion(input.parcels);
 if(region.status!=='ready')throw new Error(region.message);
 if(f.sgg!==region.sgg||f.dong!==region.dong||(f.legalDongCode&&f.legalDongCode!==region.legalDongCode))throw new Error('선택 필지와 조회 법정동이 다릅니다. 필지 선택을 다시 확인하세요.');
 const rolling=isRolling(input),automatic=f.periodMode==='latest',split=rolling||automatic||f.periodMode==='separate',rs=split?f.revenueStart:f.start,re=split?f.revenueEnd:f.end,ls=split?f.landStart:f.start,le=split?f.landEnd:f.end;
 if(!/^\d{5}$/.test(f.sgg||'')||!f.dong||!rs||!re||!ls||!le)
  throw new Error('토지거래 기준 시군구 코드 5자리·법정동명과 비교 시작·종료월을 입력하세요.');
 for(const [a,b] of [[rs,re],[ls,le]]){if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(a)||!/^\d{4}-(0[1-9]|1[0-2])$/.test(b)||a>b)throw new Error('비교 시작·종료월을 올바른 순서로 입력하세요.');const n=(+b.slice(0,4)-+a.slice(0,4))*12+(+b.slice(5)-+a.slice(5))+1;if(!automatic&&n>60)throw new Error('비교기간은 최대 60개월입니다.');}
 if(automatic&&(ls!=='2006-01'||rs!=='2020-02'))throw new Error('자동 조회의 고정 시작일을 다시 확인하세요.');
 if(rolling&&!rollingPeriodValid(input))throw new Error('최근 60개월의 시작일·종료일·제외 경계를 다시 확인하세요.');
 const parameters={sgg:f.sgg,dong:f.dong,legalDongCode:region.legalDongCode,selectedPnus:[...new Set(input.parcels.map(p=>String(p.pnu)))].sort().join(','),start:rs,end:re,scope,landScope:landScope(input),refresh:refresh?'1':'0'};
 if(automatic)parameters.periodMode='latest';
 if(rolling)Object.assign(parameters,{periodMode:'rolling60',endExclusive:f.endExclusive,landStartDate:f.landStartDate,landEndDate:f.landEndDate,revenueStartDate:f.revenueStartDate,revenueEndDate:f.revenueEndDate});
 if(split||input.project?.asOf)Object.assign(parameters,{landStart:ls,landEnd:le,revenueStart:rs,revenueEnd:re,...(input.project?.asOf?{asOf:input.project.asOf}:{})});
 if(scope==='radius'){
  const center=selectedParcelCenter(input.parcels),radius=Number(f.radiusKm??5);
  if(!center)throw new Error('반경 분양사례 조회에는 선택 필지의 확인된 도형이 필요합니다. 지도에서 개발 대상 필지를 선택하세요.');
  if(!Number.isFinite(radius)||radius<=0||radius>10)throw new Error('분양 비교 반경은 0km 초과 10km 이하로 선택하세요.');
  Object.assign(parameters,{lon:String(center.lon),lat:String(center.lat),radiusKm:String(radius)});
 }
 return parameters;
}
