export const FACILITY_CATEGORIES=[
 {id:'school',label:'학교',color:'#76b8ee'},
 {id:'mountain',label:'산',color:'#c2d579'},
 {id:'river',label:'하천',color:'#dc8ad4'},
 {id:'industrial',label:'산업단지',color:'#b89aff'},
 {id:'sewage',label:'하수처리장',color:'#55d9d0'},
];
const FACILITY_IDS=new Set(FACILITY_CATEGORIES.map(row=>row.id));
const rowOf=value=>({...value,...value?.properties});
const facilityGroup=value=>{const row=rowOf(value),group=row.group||row.groups?.[0]||String(row.sourceId||'').replace(/^vworld-place-/,'');return group==='nationalIndustrialZone'?'industrial':group;};
export function hasFacilityTypeEvidence(value){
 const row=rowOf(value),group=facilityGroup(value),parts=new Set(String(row.category||'').split(/[>,/;|]/).map(part=>part.trim()).filter(Boolean));
 const any=names=>names.some(name=>parts.has(name));
 if(row.group==='nationalIndustrialZone'||row.sourceId==='vworld-layer-nationalIndustrialZone')return true;
 if(group==='school')return !/(학원|주차장|도서관|스포츠|체육관|유치원)/.test(String(row.category||''))&&any(['학교','초등학교','중학교','고등학교','대학교','대학','전문대학','특수학교','각종학교','초등교육기관','중등교육기관','고등교육기관']);
 if(group==='mountain')return parts.has('자연지명')&&any(['산','산지','산맥','봉','산봉','산봉우리']);
 if(group==='river')return parts.has('자연지명')&&any(['하천','강','천','계곡']);
 if(group==='industrial')return any(['산업단지구역','산업단지','국가산업단지','일반산업단지','농공단지','공업단지']);
 if(group==='sewage')return any(['환경기초시설','하수처리','하수처리장','하수처리시설','하수종말처리장','물재생','물재생센터','수질정화','수질정화센터']);
 return false;
}
export function isOutOfScopeFacility(value){
 if(isRetailFacility(value))return true;
 const row=rowOf(value),ids=[row.id,row.group,...(Array.isArray(row.groups)?row.groups:[]),row.sourceId,row.serviceId,row.indicatorId];
 return ids.some(id=>/(?:retail|hospital|factory|park|schoolDistrict|naturalParkZone)/i.test(String(id||'')));
}

// Apply to live responses and older saved survey objects alike. Do not mutate
// source records or confuse a name such as 스마트병원 with a supermarket.
export function isRetailFacility(value){
 if(!value||typeof value!=='object')return false;
 const row={...value,...value.properties},ids=[row.id,row.group,...(Array.isArray(row.groups)?row.groups:[]),row.sourceId,row.serviceId,row.indicatorId];
 if(ids.some(id=>/(?:^|[-_:])(?:retail|마트)(?:$|[-_:])/i.test(String(id||''))))return true;
 return [row.label,row.name,row.category,row.keyword,row.title].some(text=>/(?:^|[^스])마트|슈퍼마켓|supermarket/i.test(String(text||'')));
}
export function visibleFacilities(rows=[]){return Array.isArray(rows)?rows.filter(value=>{
 if(!value||typeof value!=='object'||isOutOfScopeFacility(value)||!FACILITY_IDS.has(facilityGroup(value))||!hasFacilityTypeEvidence(value))return false;
 const row=rowOf(value);
 if(row.included===false||row.candidateKind==='subsidiary'||row.candidateKind==='excluded')return false;
 // Old session objects do not carry server grouping evidence: hide obvious
 // accessory points until refreshed; never promote an entrance to a mountain.
 return !/(?:입구|주차장|등산로|매표소|관리사무소|관리소|방문자센터|안내소|정문|후문|화장실|정류장|운동장|체육관|강당|도서관|기숙사)(?:\([^)]*\))?$/.test(String(row.name||'').replace(/\s+/g,''));
}):[];}
export function withoutRetailSurvey(survey){
 if(!survey||typeof survey!=='object')return survey;
 const facilities=survey.facilities||{},services=Object.fromEntries(Object.entries(facilities.services||{}).filter(([id])=>FACILITY_IDS.has(id)).map(([id,row])=>[id,{...row,rows:visibleFacilities(row.rows)}]));
 const referenceLayers=Object.fromEntries(Object.entries(facilities.referenceLayers||{}).filter(([id])=>id==='nationalIndustrialZone'));
 return {...survey,indicators:(survey.indicators||[]).filter(row=>!isOutOfScopeFacility(row)),sources:(survey.sources||[]).filter(row=>!isOutOfScopeFacility(row)),facilities:{...facilities,items:visibleFacilities(facilities.items),services,referenceLayers,
  ...(facilities.featureCollection?{featureCollection:{...facilities.featureCollection,features:visibleFacilities(facilities.featureCollection.features)}}:{}),
  ...(facilities.referenceFeatureCollection?{referenceFeatureCollection:{...facilities.referenceFeatureCollection,features:visibleFacilities(facilities.referenceFeatureCollection.features)}}:{})}};
}

export function facilityCategory(facility){
 const id=facilityGroup(facility);
 return FACILITY_CATEGORIES.find(category=>category.id===id)||{id:'other',label:'범위 외',color:'#c4cbd2'};
}

export function nearestFacilitySummary(survey){
 const facilities=survey?.facilities||{},items=visibleFacilities(facilities.items);
 return FACILITY_CATEGORIES.map(category=>{
  const rows=items.filter(row=>facilityGroup(row)===category.id&&Number.isFinite(row.distanceKm)&&row.distanceKm>=0).sort((a,b)=>a.distanceKm-b.distanceKm||String(a.id).localeCompare(String(b.id)));
  const nearest=rows[0],service=facilities.services?.[category.id];
  return {group:category.id,label:nearest?`${category.label} · ${nearest.name||'본시설 후보'}`:category.label,
   value:nearest?.distanceKm??null,candidateCount:rows.length,sourceCandidateCount:service?.candidateCount??null,
   status:service?.status||'not_requested',representative:nearest||null};
 });
}

export const FACILITY_DISTANCE_BANDS=[
 {id:'within1',title:'1km 내 주요시설',range:'1km 이하',min:null,max:1},
 {id:'over1to3',title:'3km 내 주요시설',range:'1km 초과~3km 이하',min:1,max:3},
 {id:'over3to5',title:'5km 내 주요시설',range:'3km 초과~5km 이하',min:3,max:5},
];
export function facilityDistanceBands(survey){
 const facilities=survey?.facilities||{},seen=new Set(),items=visibleFacilities(facilities.items).filter(row=>{
  const group=facilityGroup(row),id=row.entityId||row.id||row.sourceRecordId,key=`${group}:${id}`;
  if(id==null||!Number.isFinite(row.distanceKm)||row.distanceKm<0||seen.has(key))return false;
  seen.add(key);return true;
 });
 return FACILITY_DISTANCE_BANDS.map(band=>({...band,categories:FACILITY_CATEGORIES.map(category=>{
  const service=facilities.services?.[category.id],status=service?.status||'not_requested',radius=survey?.query?.radiusKm;
  const rows=items.filter(row=>facilityGroup(row)===category.id&&row.distanceKm<=band.max&&(band.min==null||row.distanceKm>band.min));
  const complete=['success','empty'].includes(status)&&Number.isFinite(radius)&&radius>=band.max;
  // The inventory lower bound stays available for old consumers. The chart
  // reports an exact count of retrieved representatives, with query status
  // separately; it never claims these are every facility in the real world.
  const responseCoversBand=['success','empty','partial'].includes(status)&&Number.isFinite(radius)&&radius>=band.max;
  return {...category,count:rows.length||complete?rows.length:null,observedCount:rows.length||responseCoversBand?rows.length:null,
   status,isLowerBound:!complete,retrievalComplete:complete,countBasis:'retrieved_distinct_facilities',rows};
 })}));
}

export function isSearchCandidate(facility){return String(facility.sourceId||'').startsWith('vworld-place-');}

export const mercatorWorld=(lon,lat,zoom)=>{
 const size=256*2**zoom,s=Math.sin(Math.max(-85.05112878,Math.min(85.05112878,lat))*Math.PI/180);
 return [(lon+180)/360*size,(.5-Math.log((1+s)/(1-s))/(4*Math.PI))*size];
};

// Ground distance at the visible map center, using the survey's mean Earth radius.
// Recompute after both zooming and panning: Mercator scale varies with latitude.
export function mapScaleBar(latitude,zoom,maxPixelWidth=140,{fitWidth=false}={}){
 if(!Number.isFinite(latitude)||Math.abs(latitude)>85.05112878||!Number.isFinite(zoom)||zoom<0||!Number.isFinite(maxPixelWidth)||maxPixelWidth<=0)return null;
 const metersPerPixel=2*Math.PI*6371008.8*Math.cos(latitude*Math.PI/180)/(256*2**zoom),maxMeters=metersPerPixel*maxPixelWidth;
 if(!Number.isFinite(metersPerPixel)||metersPerPixel<=0||!Number.isFinite(maxMeters)||maxMeters<=0)return null;
 const magnitude=10**Math.floor(Math.log10(maxMeters));
 // Fixed endpoints require the full pixel span; round labels only, never the bar geometry.
 const meters=fitWidth?maxMeters:[5,2,1,.5].map(factor=>factor*magnitude).find(value=>value>0&&value<=maxMeters&&value/metersPerPixel<=maxPixelWidth);
 if(!meters)return null;
 const pixels=fitWidth?maxPixelWidth:meters/metersPerPixel,kilometers=meters>=1000,value=kilometers?meters/1000:meters;
 const label=`${value.toLocaleString('ko-KR',{maximumSignificantDigits:fitWidth?4:3})} ${kilometers?'km':'m'}`;
 return {meters,pixels,label,metersPerPixel};
}

// Preserve the prior maximum tick (width - 112). Extend only the zero tick
// leftward so a 320px sidebar gets a 192px bar instead of the previous 48px.
export function mapInstrumentLayout(width,height){
 if(!Number.isFinite(width)||!Number.isFinite(height)||width<160||height<180)return null;
 const endX=width-112,startX=Math.max(16,Math.min(width/2,endX-260)),pixels=endX-startX;
 const compact=pixels<96,stagger=pixels/4<28,lastLabelY=compact?75:stagger?61:49;
 return {pixels,startX,endX,scaleX:startX-16,scaleY:height-8-lastLabelY,scaleHeight:lastLabelY+4,
  compact,stagger,compassX:width-84,compassY:height-96};
}

// Match the survey's Haversine convention, then project every boundary point.
// A constant map-pixel radius would understate 5 km at Korean latitudes.
export function geodesicCircle(center,radiusKm=5,segments=128){
 if(!center||!Number.isFinite(center.lon)||!Number.isFinite(center.lat)||Math.abs(center.lat)>85||!Number.isFinite(radiusKm)||radiusKm<=0)return [];
 const phi=center.lat*Math.PI/180,lambda=center.lon*Math.PI/180,delta=radiusKm/6371.0088;
 return Array.from({length:segments+1},(_,index)=>{
  const bearing=2*Math.PI*(index%segments)/segments;
  const lat=Math.asin(Math.sin(phi)*Math.cos(delta)+Math.cos(phi)*Math.sin(delta)*Math.cos(bearing));
  const lon=lambda+Math.atan2(Math.sin(bearing)*Math.sin(delta)*Math.cos(phi),Math.cos(delta)-Math.sin(phi)*Math.sin(lat));
  return [lon*180/Math.PI,lat*180/Math.PI];
 });
}

export const MAP_RADIUS_KM=[1,3,5];
export function mapRadiusRings(center){
 return MAP_RADIUS_KM.map(radiusKm=>({radiusKm,points:geodesicCircle(center,radiusKm)})).filter(ring=>ring.points.length);
}

export function radiusMapView(center,radiusKm,width,height){
 const circle=geodesicCircle(center,radiusKm);
 if(!circle.length)return null;
 const [cx,cy]=mercatorWorld(center.lon,center.lat,0),points=circle.map(([lon,lat])=>mercatorWorld(lon,lat,0));
 const extentX=Math.max(...points.map(([x])=>Math.abs(x-cx)))*2,extentY=Math.max(...points.map(([,y])=>Math.abs(y-cy)))*2;
 // Forty pixels on each side keep the complete outer ring and its labels
 // inside the canvas without losing an extra zoom level on a short sidebar.
 const scale=Math.min(Math.max(60,width-80)/extentX,Math.max(60,height-80)/extentY);
 return {lon:center.lon,lat:center.lat,z:Math.max(5,Math.min(19,Math.floor(Math.log2(scale))))};
}

const intersects=(a,b)=>a.x<b.x+b.width+4&&a.x+a.width+4>b.x&&a.y<b.y+b.height+3&&a.y+a.height+3>b.y;
export function shortFacilityName(name,max=22){const chars=Array.from(String(name||'이름 미제공'));return chars.length>max?chars.slice(0,max-1).join('')+'…':chars.join('');}
export function facilityTextWidth(text){return Array.from(text).reduce((width,char)=>width+(/[\u0000-\u007f]/.test(char)?6.5:11),0);}

// Only screen-visible points receive names. Stable first-fit placement caps the
// text count and leaves every marker available for full-name inspection.
export function layoutFacilityLabels(markers,width,height,{blocked=[],limit=60}={}){
 const occupied=[...blocked],labels=[];
 for(const marker of markers){
  if(labels.length>=limit)break;
  if(marker.x<0||marker.x>width||marker.y<0||marker.y>height)continue;
  const text=shortFacilityName(marker.name),labelWidth=facilityTextWidth(text)+14,labelHeight=22;
  const positions=[{x:marker.x+16,y:marker.y-27},{x:marker.x+16,y:marker.y+7},{x:marker.x-labelWidth-16,y:marker.y-27},{x:marker.x-labelWidth-16,y:marker.y+7}];
  const box=positions.map(position=>({...position,width:labelWidth,height:labelHeight})).find(candidate=>candidate.x>=5&&candidate.y>=5&&candidate.x+candidate.width<=width-5&&candidate.y+candidate.height<=height-5&&!occupied.some(taken=>intersects(candidate,taken)));
  if(box){occupied.push(box);labels.push({...box,id:marker.id,text,color:marker.category.color});}
 }
 return labels;
}
