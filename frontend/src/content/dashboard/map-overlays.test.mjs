import assert from 'node:assert/strict';
import {test} from 'node:test';
import {selectedParcelCenter} from './comparison-scope.mjs';
import {FACILITY_CATEGORIES,facilityCategory,facilityDistanceBands,nearestFacilitySummary,isSearchCandidate,mercatorWorld,mapScaleBar,mapInstrumentLayout,isRetailFacility,visibleFacilities,withoutRetailSurvey,geodesicCircle,mapRadiusRings,radiusMapView,layoutFacilityLabels} from './map-overlays.mjs';

const geometry=(lon,lat)=>({type:'Polygon',coordinates:[[[lon,lat],[lon+.002,lat],[lon+.002,lat+.002],[lon,lat+.002],[lon,lat]]]});
const radians=value=>value*Math.PI/180;
const distance=(a,b)=>{
 const dLat=radians(b[1]-a.lat),dLon=radians(b[0]-a.lon),h=Math.sin(dLat/2)**2+Math.cos(radians(a.lat))*Math.cos(radians(b[1]))*Math.sin(dLon/2)**2;
 return 2*6371.0088*Math.atan2(Math.sqrt(h),Math.sqrt(1-h));
};

test('three concentric geodesic map rings retain 1, 3, and 5 km ground distances',()=>{
 const center={lon:126.78564,lat:37.54094},rings=mapRadiusRings(center);
 assert.deepEqual(rings.map(r=>r.radiusKm),[1,3,5]);
 for(const ring of rings){assert.equal(ring.points.length,129);assert.deepEqual(ring.points[0],ring.points.at(-1));for(const point of ring.points)assert.ok(Math.abs(distance(center,point)-ring.radiusKm)<1e-8);}
 assert.deepEqual(mapRadiusRings(null),[]);
});

test('Seoul scale matches projected ground distance and uses a fitting nice distance',()=>{
 const center={lon:126.978,lat:37.5665},zoom=17,scale=mapScaleBar(center.lat,zoom);
 assert.equal(scale.meters,100);assert.equal(scale.label,'100 m');
 assert.ok(scale.pixels>105&&scale.pixels<106);
 const origin=mercatorWorld(center.lon,center.lat,zoom),longitude=360*scale.pixels/(256*2**zoom);
 const projected=mercatorWorld(center.lon+longitude,center.lat,zoom);
 assert.ok(Math.abs(projected[0]-origin[0]-scale.pixels)<1e-7);
 assert.ok(Math.abs(distance(center,[center.lon+longitude,center.lat])*1000-scale.meters)<1e-6);
 assert.ok(scale.pixels<=140&&scale.pixels>0);
 assert.ok(200/scale.metersPerPixel>140);
 assert.equal(mapScaleBar(center.lat,13).label,'2 km');
});

test('scale follows viewport latitude, zoom steps, and a narrow available width',()=>{
 const equator=mapScaleBar(0,17),seoul=mapScaleBar(37.5665,17),north=mapScaleBar(60,17);
 assert.ok(equator.metersPerPixel>seoul.metersPerPixel&&seoul.metersPerPixel>north.metersPerPixel);
 assert.ok(Math.abs(north.metersPerPixel/equator.metersPerPixel-.5)<1e-12);
 assert.equal(mapScaleBar(-37.5665,17).metersPerPixel,seoul.metersPerPixel);
 assert.equal(mapScaleBar(37.5665,18).metersPerPixel,seoul.metersPerPixel/2);
 assert.ok(Math.abs(mapScaleBar(37.5665,17.5).metersPerPixel-seoul.metersPerPixel/Math.sqrt(2))<1e-12);
 for(const width of [1,12,35,70,140]){
  const scale=mapScaleBar(37.5665,17,width);
  assert.ok(scale.pixels>0&&scale.pixels<=width);
  assert.ok(Math.abs(scale.pixels*scale.metersPerPixel-scale.meters)<1e-12);
  const factor=scale.meters/10**Math.floor(Math.log10(scale.meters));
  assert.ok([1,2,5].some(nice=>Math.abs(nice-factor)<1e-12));
 }
 assert.equal(mapScaleBar(37.5665,17,35).label,'20 m');
});

test('fixed-width scale keeps its endpoints while ground distance changes with zoom',()=>{
 const center={lon:127.7,lat:36.4},pixels=280.6640625;
 for(const zoom of [16,17,18]){
  const scale=mapScaleBar(center.lat,zoom,pixels,{fitWidth:true});
  assert.equal(scale.pixels,pixels);
  const longitude=360*pixels/(256*2**zoom);
  assert.ok(Math.abs(distance(center,[center.lon+longitude,center.lat])*1000-scale.meters)<1e-5);
 }
 const close=mapScaleBar(center.lat,18,pixels,{fitWidth:true}),far=mapScaleBar(center.lat,17,pixels,{fitWidth:true});
 assert.equal(far.meters,close.meters*2);
 assert.equal(far.pixels,close.pixels);
});

test('narrow sidebar extends the zero tick left and fixes both instruments to the bottom',()=>{
 const narrow=mapInstrumentLayout(320,540);
 assert.equal(narrow.endX,320-112,'same maximum tick position as the old layout');
 assert.equal(narrow.startX,16);assert.equal(narrow.pixels,192);assert.ok(narrow.pixels>3*(320/2-112));
 assert.equal(narrow.scaleY+49,540-8);assert.equal(narrow.compassY+88,540-8);
 for(const width of [300,320,436,456,1000])for(const height of [250,540,740]){
  const v=mapInstrumentLayout(width,height);assert.equal(v.endX,width-112);assert.equal(v.compassX,width-84);assert.equal(v.compassY,height-96);
  assert.ok(v.startX>=16&&v.startX<=width/2);assert.ok(v.pixels/4>=40);assert.equal(v.scaleX+16+v.pixels,v.endX);assert.equal(v.scaleY+49,height-8);
  const scale=mapScaleBar(37.5,17,v.pixels,{fitWidth:true});assert.equal(scale.pixels,v.pixels);assert.ok(Math.abs(scale.meters/scale.metersPerPixel-v.pixels)<1e-9);
  const longitude=360*scale.pixels/(256*2**17);assert.ok(Math.abs(distance({lon:127,lat:37.5},[127+longitude,37.5])*1000-scale.meters)<1e-5);
 }
 assert.equal(mapInstrumentLayout(100,500),null);assert.equal(mapInstrumentLayout(320,100),null);
});

test('five requested groups render with type evidence; ancillary evidence survives without becoming a map point',()=>{
 const rows=[{id:'retail-1',name:'현대할인마트',group:'retail'},{id:'school-1',name:'초등학교',group:'school'},
  {id:'main',name:'천마산',group:'mountain',category:'자연지명 > 산지 > 산맥'},{id:'entry',name:'천마산 입구',group:'mountain'},
  {id:'complex',name:'테스트산업단지',sourceId:'vworld-place-industrial',category:'시설구역경계 > 산업단지구역'},
  {id:'park',name:'테스트산업단지 주차장',group:'industrial'},{id:'sewage',group:'sewage',name:'테스트하수처리장',category:'환경기초시설'},
  {id:'river',name:'왕숙천',group:'river',category:'자연지명 > 하천'},{id:'excluded',name:'본시설미확정',group:'mountain',included:false}];
 const original=JSON.stringify(rows),visible=visibleFacilities(rows);assert.deepEqual(visible.map(r=>r.id),['main','complex','sewage','river']);assert.equal(JSON.stringify(rows),original);
 assert.deepEqual(FACILITY_CATEGORIES.map(c=>c.id),['school','mountain','river','industrial','sewage']);
 const source={facilities:{items:rows,candidates:rows,services:{retail:{label:'마트'},school:{label:'학교'},mountain:{rows:[rows[2]]}},referenceLayers:{schoolDistrict:{},nationalIndustrialZone:{}},referenceFeatureCollection:{features:[{properties:{group:'park'}},{properties:{group:'nationalIndustrialZone'}}]}},indicators:[{id:'retailNearestKm'},{id:'schoolNearestKm'},{id:'mountainNearestKm'},{id:'households',value:123}],sources:[{id:'vworld-place-school'},{id:'vworld-place-river'},{id:'kosis'}]};
 const snapshot=JSON.stringify(source),filtered=withoutRetailSurvey(source);assert.equal(JSON.stringify(source),snapshot);
 assert.deepEqual(filtered.facilities.items.map(r=>r.id),['main','complex','sewage','river']);assert.deepEqual(Object.keys(filtered.facilities.services),['school','mountain']);
 assert.deepEqual(filtered.indicators.map(r=>r.id),['schoolNearestKm','mountainNearestKm','households']);assert.deepEqual(filtered.sources.map(r=>r.id),['vworld-place-school','vworld-place-river','kosis']);
 assert.equal(filtered.facilities.referenceFeatureCollection.features.length,1);assert.deepEqual(Object.keys(filtered.facilities.referenceLayers),['nationalIndustrialZone']);
 assert.equal(filtered.facilities.candidates.length,rows.length);assert.equal(isRetailFacility({name:'스마트초등학교'}),false);assert.equal(isRetailFacility({indicatorId:'nearest-retail-km'}),true);
});

test('scale rejects invalid inputs and unusable numeric ranges without throwing',()=>{
 for(const latitude of [NaN,Infinity,-Infinity,85.1,-85.1,90,-90,undefined,'37'])assert.equal(mapScaleBar(latitude,17),null);
 for(const zoom of [NaN,Infinity,-Infinity,-1,undefined,'17',1024])assert.equal(mapScaleBar(37,zoom),null);
 for(const width of [NaN,Infinity,-Infinity,0,-1,null,'140',Number.MIN_VALUE])assert.equal(mapScaleBar(37,17,width),null);
 assert.ok(mapScaleBar(85.05112878,0));
 assert.ok(mapScaleBar(-85.05112878,0));
});

test('facility overview keeps five categories, uses nearest main representative, and never turns missing into zero',()=>{
 const items=[{id:'far',group:'mountain',name:'먼산',category:'자연지명 > 산지 > 산맥',distanceKm:3},{id:'near',group:'mountain',name:'가까운산',category:'자연지명 > 산지 > 산맥',distanceKm:1},
  {id:'accessory',group:'mountain',name:'먼산 입구',distanceKm:.01},{id:'river',group:'river',name:'왕숙천',category:'자연지명 > 하천',distanceKm:0},
  {id:'school',group:'school',name:'학교',distanceKm:.001}];
 const result=nearestFacilitySummary({facilities:{items,services:{mountain:{status:'success',candidateCount:3},industrial:{status:'credentials_missing'}}}});
 assert.deepEqual(result.map(row=>row.group),['school','mountain','river','industrial','sewage']);
 assert.equal(result[1].value,1);assert.equal(result[1].candidateCount,2);assert.equal(result[1].sourceCandidateCount,3);assert.equal(result[1].label,'산 · 가까운산');
 assert.equal(result[2].value,0);assert.equal(result[3].value,null);assert.equal(result[3].status,'credentials_missing');
 assert.equal(result[4].status,'not_requested');assert.equal(nearestFacilitySummary(null).every(row=>row.value===null),true);
});

test('circle uses the full parcel selection center and disappears for no or incomplete geometry',()=>{
 const center=selectedParcelCenter([{geometry:geometry(127,37)},{geometry:geometry(127.1,37.1)}]);
 assert.ok(Math.abs(center.lon-127.051)<1e-12);
 assert.ok(Math.abs(center.lat-37.051)<1e-12);
 assert.equal(geodesicCircle(center).length,129);
 assert.deepEqual(geodesicCircle(selectedParcelCenter([])),[]);
 assert.deepEqual(geodesicCircle(selectedParcelCenter([{geometry:geometry(127,37)},{}])),[]);
});

test('5 km circle follows ground distance at Korean latitudes instead of map pixel units',()=>{
 for(const lat of [33,37.5,39]){
  const center={lon:127,lat},ring=geodesicCircle(center);
  for(const point of ring)assert.ok(Math.abs(distance(center,point)-5)<1e-8);
  assert.deepEqual(ring[0],ring.at(-1));
  const origin=mercatorWorld(center.lon,center.lat,12),east=mercatorWorld(...ring[32],12);
  const equatorPixels=5/(2*Math.PI*6371.0088)*(256*2**12);
  assert.ok((east[0]-origin[0])/equatorPixels>1.18);
 }
});

test('radius view fits the full projected circle with padding on desktop and mobile',()=>{
 const center={lon:127.0276,lat:37.4979};
 for(const [width,height] of [[1000,560],[360,360],[300,250]]){
  const view=radiusMapView(center,5,width,height),origin=mercatorWorld(view.lon,view.lat,view.z);
  assert.equal(view.lon,center.lon);assert.equal(view.lat,center.lat);
  for(const point of geodesicCircle(center)){
   const pixel=mercatorWorld(...point,view.z);
   assert.ok(Math.abs(pixel[0]-origin[0])<width/2-40);
   assert.ok(Math.abs(pixel[1]-origin[1])<height/2-40);
  }
 }
});

test('short map canvas does not discard a fitting zoom level for the five-km outer ring',()=>{
 const center={lon:126.78564,lat:37.54094},view=radiusMapView(center,5,300,250);
 assert.equal(view.z,11);
 const xs=geodesicCircle(center,5).map(point=>mercatorWorld(...point,view.z)[0]);
 const diameter=Math.max(...xs)-Math.min(...xs);
 assert.ok(diameter>150&&diameter<170);
});

test('search groups retain distinct colors, readable names, and candidate status',()=>{
 assert.equal(new Set(FACILITY_CATEGORIES.map(c=>c.color)).size,FACILITY_CATEGORIES.length);
 assert.equal(facilityCategory({group:'mountain'}).label,'산');
 assert.equal(facilityCategory({sourceId:'vworld-place-sewage'}).label,'하수처리장');
 assert.equal(facilityCategory({group:'not-known'}).label,'범위 외');
 assert.equal(isSearchCandidate({sourceId:'vworld-place-park'}),true);
 assert.equal(isSearchCandidate({sourceId:'vworld-layer-schoolDistrict'}),false);
});

test('1,522 dense points produce bounded non-overlapping names without altering point data',()=>{
 const markers=Array.from({length:1522},(_,index)=>({id:String(index),name:`주변시설 검색 후보 ${index}`,x:20+(index*17)%760,y:20+(index*23)%470,category:FACILITY_CATEGORIES[index%FACILITY_CATEGORIES.length]}));
 const blocked={x:360,y:200,width:170,height:50};
 const labels=layoutFacilityLabels(markers,800,520,{blocked:[blocked]});
 assert.ok(labels.length>5&&labels.length<=60);assert.equal(markers.length,1522);
 const overlap=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
 for(let i=0;i<labels.length;i++){
  const a=labels[i];
  assert.ok(a.x>=0&&a.y>=0&&a.x+a.width<=800&&a.y+a.height<=520);
  assert.equal(overlap(a,blocked),false);
  for(const b of labels.slice(i+1))assert.equal(overlap(a,b),false);
 }
 assert.deepEqual(layoutFacilityLabels([{id:'outside',name:'화면 밖',category:FACILITY_CATEGORIES[0],x:-40,y:50}],800,520),[]);
});

test('retained legacy candidates ending in 산 cannot bypass positive natural-feature classification',()=>{
 const raw=[{id:'food',name:'수중회수산',group:'mountain',category:'기타식품제조업 > 도시락및식사용조리식품제조업'},
  {id:'farm',name:'진접농.수.산',group:'mountain',category:'식료품소매업'},
  {id:'consulting',name:'디디오동산',group:'mountain',category:'경영컨설팅업'},
  {id:'missing',name:'철마산',group:'mountain'},
  {id:'mountain',name:'철마산',group:'mountain',category:'자연지명 > 산지 > 산맥'},
  {id:'peak',name:'수리봉',group:'mountain',category:'자연지명 > 산지 > 봉'}];
 assert.deepEqual(visibleFacilities(raw).map(row=>row.id),['mountain','peak']);assert.equal(raw.length,6);
});

test('environment-classified sewage plants render while sports facilities and unknown categories remain excluded',()=>{
 const rows=[{id:'plant',name:'공공하수처리시설',group:'sewage',category:'환경기초시설'},
  {id:'sports',name:'내촌하수처리시설내다목적운동장',group:'sewage',category:'생활스포츠시설 > 기타스포츠시설'},
  {id:'unknown',name:'공공하수처리시설',group:'sewage'}];
 assert.deepEqual(visibleFacilities(rows).map(row=>row.id),['plant']);
});

test('schools require a school category and exclude academies and accessory buildings',()=>{
 const rows=[{id:'main',name:'테스트초등학교',group:'school',category:'교육연구시설 > 초등학교'},
  {id:'academy',name:'테스트학교',group:'school',category:'교육 > 학원'},
  {id:'parking',name:'테스트초등학교 주차장',group:'school',category:'교육 > 초등학교'},
  {id:'gym',name:'테스트초등학교 체육관',group:'school',category:'교육 > 초등학교'},
  {id:'unknown',name:'테스트학교',group:'school'}];
 assert.deepEqual(visibleFacilities(rows).map(row=>row.id),['main']);
});

test('facility counts assign boundary distances to exclusive bands and count an entity once',()=>{
 const items=[0,1,1.000001,3,3.000001,5,5.000001].map((distanceKm,index)=>({id:`s${index}`,group:'school',name:`학교${index}`,category:'교육 > 학교',distanceKm}));
 const source={query:{radiusKm:5},facilities:{items:[...items,items[1]],services:{school:{status:'success'}}}};
 const original=JSON.stringify(source),rows=facilityDistanceBands(source).map(b=>b.categories[0]);
 assert.deepEqual(rows.map(row=>row.count),[2,2,2]);
 assert.equal(new Set(rows.flatMap(row=>row.rows.map(r=>r.id))).size,6);
 assert.ok(rows.every(row=>!row.isLowerBound));assert.equal(JSON.stringify(source),original);
});

test('count charts distinguish verified search zero from failed or partial retrieval and a smaller query radius',()=>{
 const source={query:{radiusKm:1},facilities:{items:[{id:'s',group:'school',name:'테스트학교',category:'교육 > 학교',distanceKm:.5}],services:{school:{status:'partial'},mountain:{status:'empty'},river:{status:'error'}}}};
 const bands=facilityDistanceBands(source);
 assert.equal(bands[0].categories[0].count,1);assert.equal(bands[0].categories[0].isLowerBound,true);
 assert.equal(bands[0].categories[1].count,0);assert.equal(bands[0].categories[2].count,null);
 assert.equal(bands[1].categories[1].count,null);assert.ok(facilityDistanceBands(null).every(b=>b.categories.every(c=>c.count===null)));
});

test('observed counts are exact retrieved integers with completeness separate from inventory bounds',()=>{
 const items=[{id:'a',group:'school',name:'테스트학교',category:'교육 > 학교',distanceKm:.5},
  {id:'b',group:'school',name:'다른학교',category:'교육 > 학교',distanceKm:2}];
 const source={query:{radiusKm:5},facilities:{items:[...items,items[0]],services:{school:{status:'partial'},mountain:{status:'error'},river:{status:'empty'}}}};
 const original=JSON.stringify(source),bands=facilityDistanceBands(source),school=bands.map(b=>b.categories[0]);
 assert.deepEqual(school.map(r=>r.observedCount),[1,1,0]);
 assert.ok(school.every(r=>Number.isInteger(r.observedCount)&&r.retrievalComplete===false&&r.countBasis==='retrieved_distinct_facilities'));
 assert.equal(school[2].count,null,'legacy inventory bound remains unknown while observed returned rows are exactly zero');
 assert.ok(bands.every(b=>b.categories[1].observedCount===null),'failed retrieval is never rendered as zero');
 assert.ok(bands.every(b=>b.categories[2].observedCount===0&&b.categories[2].retrievalComplete));
 source.query.radiusKm=1;
 const limited=facilityDistanceBands(source);
 assert.equal(limited[0].categories[0].observedCount,1);
 assert.equal(limited[2].categories[0].observedCount,null,'outside queried radius is unacquired');
 source.query.radiusKm=5;assert.equal(JSON.stringify(source),original);
});
