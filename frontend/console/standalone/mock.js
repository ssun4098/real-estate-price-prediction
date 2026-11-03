// 분석 콘솔 '가상 데이터' 단독 HTML 용 가짜 서버 (2026-11-03 요청).
// 콘솔(main.js)과 지도는 그대로 두고, 브라우저의 fetch 를 가로채서 '/api/...' 요청에 미리 넣어 둔 자료로 답한다.
// 자료(demo-data.json.gz)는 make_demo_data.py 가 서버와 같은 계산 코드로 만든 것: 안산 장상동 27필지 샘플,
// 그 샘플을 현재 규칙·토지가격 모델로 다시 계산한 결과, 토지 그룹 월별 단가, 지가변동률·COFIX.
// 이 파일은 콘솔보다 먼저 실행돼야 하므로 standalone.js 가 가장 먼저 import 한다.
import {projectRevision} from '../../src/content/dashboard/revision-model.mjs';
import {selectedParcelCenter} from '../../src/content/dashboard/comparison-scope.mjs';

const fin=Number.isFinite;
const realFetch=globalThis.fetch.bind(globalThis);

/* ---------- 자료 읽기: HTML 안의 <script id="demo-data"> (gzip + base64) ---------- */
const ready=(async()=>{
 const el=document.getElementById('demo-data');
 if(!el)throw new Error('가상 데이터가 HTML 안에 없습니다.');
 const bin=Uint8Array.from(atob(el.textContent.trim()),c=>c.charCodeAt(0));
 const text=await new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
 const data=JSON.parse(text);
 data.parcels=new Map(data.sample.snapshot.inputs.parcels.map(p=>[String(p.pnu),p]));
 return data;
})();

/* ---------- 저장 샘플: 이 창을 닫기 전까지만 기억 (샘플 하나가 수 MB 라 브라우저 저장소에는 넣지 않는다) ---------- */
const saved=new Map();
let savedSeq=0;

/* ---------- 도형 도우미 ---------- */
const rings=g=>!g?[]:g.type==='Polygon'?g.coordinates:g.type==='MultiPolygon'?g.coordinates.flat(1):[];
const points=g=>rings(g).flat(1).filter(c=>fin(c?.[0])&&fin(c?.[1]));
function bboxOf(g){const p=points(g);if(!p.length)return null;const xs=p.map(c=>c[0]),ys=p.map(c=>c[1]);return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]}
function centerOf(g){const p=points(g);if(!p.length)return null;return {lon:p.reduce((t,c)=>t+c[0],0)/p.length,lat:p.reduce((t,c)=>t+c[1],0)/p.length}}
function km(a,b){const R=6371,r=Math.PI/180,dLat=(b.lat-a.lat)*r,dLon=(b.lon-a.lon)*r,h=Math.sin(dLat/2)**2+Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin(dLon/2)**2;return 2*R*Math.asin(Math.sqrt(h))}
const squash=s=>String(s||'').replace(/\s+/g,'').replace(/번지/g,'');

/* ---------- 응답 도우미 ---------- */
class MockError extends Error{constructor(status,code,message){super(message);this.status=status;this.code=code}}
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const withoutBoundary=p=>{const {boundaryAllocation,...rest}=p;return rest};
const sampleSummary=item=>{const s=item.snapshot;return {id:item.id,name:item.name,capturedAt:item.capturedAt,readOnly:true,persistencePolicy:item.persistencePolicy,isDefault:item.id===DEMO_ID,scenario:s?.scenario,parcelCount:(s?.inputs?.parcels||[]).length,areaM2:s?.results?.development?.landAreaM2??null}};
let DEMO_ID='';

/* ---------- 요청별 가짜 응답 ---------- */
async function answer(method,url,body){
 const d=await ready,q=url.searchParams,path=url.pathname;DEMO_ID=d.sample.id;
 if(path==='/api/status')return {mode:'local',demo:true,model:{status:'ready',...d.model},message:'가상 데이터 · 서버 없이 실행 중'};

 if(path==='/api/portfolio-samples'&&method==='GET')return {items:[d.sample,...saved.values()].map(sampleSummary),defaultId:d.sample.id};
 if(path==='/api/portfolio-samples'&&method==='POST'){
  const id=`demo-saved-${++savedSeq}`,item={...body,id,capturedAt:new Date().toISOString(),readOnly:true,persistencePolicy:'portfolio_frozen_v1'};
  saved.set(id,item);return item;
 }
 if(path.startsWith('/api/portfolio-samples/')){
  const id=decodeURIComponent(path.slice('/api/portfolio-samples/'.length));
  const item=id===d.sample.id?d.sample:saved.get(id);
  if(!item)throw new MockError(404,'NOT_FOUND','저장한 분석을 찾을 수 없습니다.');
  return structuredClone(item);
 }

 if(path==='/api/address'){
  const key=squash(q.get('keyword'));
  if(key.length<2)throw new MockError(400,'BAD_REQUEST','주소는 2~200자로 입력하세요.');
  const candidates=[...d.parcels.values()].filter(p=>squash(p.address).includes(key)||squash(p.legalDongName).includes(key)||key.includes(squash(p.dong))).map(p=>{const c=centerOf(p.geometry);return {label:p.address,address:p.address,roadAddress:'',legalDongCode:p.legalDongCode,legalDongName:p.legalDongName,dong:p.dong,lon:c?.lon??null,lat:c?.lat??null,coordinateStatus:'가상 데이터'}});
  return {candidates,totalCount:candidates.length,truncated:false,queriedAt:new Date().toISOString(),warnings:candidates.length?['가상 데이터: 안산 장상동 27필지만 찾을 수 있습니다.']:['가상 데이터에는 안산 장상동 27필지만 있습니다. 예: ‘장상동’으로 검색하세요.']};
 }

 if(path==='/api/parcels'){
  const [w,s,e,n]=String(q.get('bbox')||'').split(',').map(Number);
  const features=[...d.parcels.values()].filter(p=>{const b=bboxOf(p.geometry);return b&&!(b[2]<w||b[0]>e||b[3]<s||b[1]>n)})
   .map(p=>({type:'Feature',id:String(p.pnu),geometry:p.geometry,properties:{pnu:String(p.pnu),address:p.address,sourceStatus:'가상 데이터'}}));
  return {type:'FeatureCollection',features,crs:'EPSG:4326',totalCount:features.length,collectedCount:features.length,collectionStatus:'complete',queriedAt:new Date().toISOString(),warnings:[]};
 }

 if(path==='/api/parcel'||path==='/api/boundary-allocation'){
  const p=d.parcels.get(String(q.get('pnu')));
  if(!p)throw new MockError(404,'NOT_FOUND','가상 데이터에 없는 필지입니다.');
  if(path==='/api/parcel')return structuredClone(withoutBoundary(p));
  return {parcel:structuredClone(withoutBoundary(p)),boundaryAllocation:structuredClone(p.boundaryAllocation)};
 }

 if(path==='/api/site-survey'){
  const survey=structuredClone(d.sample.displayState?.survey||{facilities:[],statistics:{},sources:[]});
  survey.warnings=[...(survey.warnings||[]),'가상 데이터: 저장된 주변시설 조사 결과를 그대로 보여 줍니다.'];
  return survey;
 }

 if(path==='/api/comparables'){
  const params=Object.fromEntries(q.entries()),center=fin(+params.lon)&&fin(+params.lat)?{lon:+params.lon,lat:+params.lat}:null,radius=+params.radiusKm||5;
  const src=d.sample.snapshot.inputs.comparables;
  // 분양사례는 요청한 중심·반경으로 거리를 다시 재서 거른다. 토지 실거래는 저장된 사례 그대로.
  const revenueCases=src.revenueCases.map(c=>{const dist=center&&fin(c.lon)&&fin(c.lat)?km(center,{lon:c.lon,lat:c.lat}):c.distanceKm;return {...c,distanceKm:fin(dist)?Math.round(dist*100)/100:dist}}).filter(c=>!center||!fin(c.distanceKm)||c.distanceKm<=radius);
  const query={...params,radiusKm:radius,center,selectedPnus:String(params.selectedPnus||'').split(',').filter(Boolean),queriedAt:new Date().toISOString(),demo:true};
  return {revenueCases,landCases:structuredClone(src.landCases),query,landQuery:{...query,landRulesVersion:src.landQuery?.landRulesVersion},
   landCollectionStatus:'complete',collectionStatus:'complete',fromCache:false,geocodingStats:{},warnings:[`가상 데이터: 저장된 사례를 씁니다 (분양 ${revenueCases.length}건 · 반경 ${radius}km, 토지 ${src.landCases.length}건)`]};
 }

 if(path==='/api/analyze'&&method==='POST'){
  // 서버 대신 브라우저 계산(기존 화면의 즉시 계산과 같은 projectRevision)으로 결과를 만든다.
  // 기준 결과는 make_demo_data.py 가 서버 코드로 계산한 장상동 결과(토지가격 모델 예측 포함).
  // projectRevision 은 서버가 고른 '적합 분양 단지'를 그대로 쓰므로, 지금 입력의 분양사례로 그 목록을 다시 만든다 (서버 revenue._revenue 와 같은 규칙).
  const base=d.sample.snapshot,revenue={...base.results.revenue,...eligibleComplexes(body),comparisonReason:null};
  const out=projectRevision(body,{...base,inputs:body,results:{...base.results,revenue}},{preview:false});
  return {...out,inputs:body,calculationStatus:'가상 데이터 · 브라우저 계산',results:{...out.results,validation:{...out.results?.validation,mode:'demo-browser'}}};
 }

 if(path==='/api/console/land-history'){
  const keys=String(q.get('keys')||'').split(',').map(s=>s.trim()).filter(Boolean);
  return {series:keys.map(key=>({key,points:d.landHistory[key]||[]})),source:'가상 데이터 · 모델 입력 자료에서 미리 뽑은 장상동 시군구 토지 그룹 월간 단가'};
 }
 if(path==='/api/console/region-indicators'){
  const sgg=String(q.get('sgg')||'');
  return d.indicators[sgg]||{sgg,regionKey:null,regionName:null,landChange:[],cofix:[]};
 }
 throw new MockError(404,'NOT_FOUND',`가상 데이터에서는 지원하지 않는 요청입니다: ${path}`);
}

/* ---------- 적합 분양 단지 (서버 server/domain/analysis/revenue.py _revenue 의 사례 판정·단지 묶기와 같은 규칙) ---------- */
const median=v=>{const x=v.filter(fin).sort((a,b)=>a-b),n=x.length;return !n?null:n%2?x[(n-1)/2]:(x[n/2-1]+x[n/2])/2};
const positive=v=>fin(+v)&&+v>0?+v:null;
function eligibleComplexes(input){
 const f=input.comparisonFilters||{},asOf=input.project?.asOf||'',radiusMode=(f.scope||'radius')==='radius';
 const center=radiusMode?selectedParcelCenter(input.parcels||[]):null,radius=+(f.radiusKm??5);
 const start=f.revenueStartDate||'',end=f.revenueEndDate||'';
 const groups=new Map(),excluded=[],seen=new Set();
 (input.comparables?.revenueCases||[]).forEach((c,i)=>{
  const id=String(c.id||`revenue-${i}`),area=positive(c.supplyAreaM2),price=positive(c.priceManwon),complex=String(c.houseManageNo||c.complexId||'');
  let reason=c.eligible===false?(c.exclusionReason||'사용자 또는 수집 단계 제외'):!complex?'단지 식별자 미확보':!area||!price?'양수 가격·공급면적 미확보':null;
  const date=String(c.date||'').slice(0,10);
  if(!reason&&date){if(asOf&&date>asOf)reason='분석 기준일 이후 공고';else if((start&&date<start)||(end&&date>end))reason='조회 기간 밖 분양사례'}
  if(!reason&&radiusMode){
   if(!center||!fin(c.lon)||!fin(c.lat))reason='반경 비교를 위한 사업지 좌표 미확보';
   else if(c.addressVerified!==true||c.coordinateVerified!==true)reason='반경 비교를 위한 사업지 위치 미확정';
   else if(km(center,{lon:c.lon,lat:c.lat})>radius+1e-9)reason='선택한 분양 검색 반경 밖 사례';
  }
  const key=[complex,String(c.announcementNo||''),String(c.modelNo||id)].join('|');
  if(!reason&&seen.has(key))reason='같은 공고·주택형 식별자 중복';
  seen.add(key);
  if(reason){excluded.push({id,reason});return}
  if(!groups.has(complex))groups.set(complex,[]);
  groups.get(complex).push({c,id,unit:price*10000/area,dist:center&&fin(c.lon)?km(center,{lon:c.lon,lat:c.lat}):c.distanceKm});
 });
 const points=[];
 for(const [complex,rows0] of groups){
  let rows=rows0;
  if(new Set(rows.map(r=>String(r.c.announcementNo||''))).size>1){
   const chosen=rows.filter(r=>r.c.representativeAnnouncement===true);
   if(!chosen.length||new Set(chosen.map(r=>String(r.c.announcementNo))).size!==1){rows.forEach(r=>excluded.push({id:r.id,reason:'동일 단지 복수 공고 관계 미확인'}));continue}
   rows.filter(r=>!chosen.includes(r)).forEach(r=>excluded.push({id:r.id,reason:'확인된 대표 공고 외 공고'}));rows=chosen;
  }
  points.push({id:complex,label:rows[0].c.name||complex,unitPriceWonM2:median(rows.map(r=>r.unit)),medianSupplyAreaM2:median(rows.map(r=>positive(r.c.supplyAreaM2))),
   caseIds:rows.map(r=>r.id),distanceKm:rows[0].dist??null,legalDongName:rows[0].c.legalDongName});
 }
 return {points,eligibleComplexes:points,excluded,comparisonScope:radiusMode?'radius':'dong',radiusKm:radiusMode?radius:null};
}

globalThis.fetch=async(input,options={})=>{
 const raw=typeof input==='string'?input:input?.url||'';
 if(!raw.startsWith('/api/'))return realFetch(input,options);
 const signal=options.signal;
 const abort=()=>{throw new DOMException('요청을 취소했습니다.','AbortError')};
 if(signal?.aborted)abort();
 const url=new URL(raw,'http://demo.local'),method=String(options.method||'GET').toUpperCase();
 // 실제 서버처럼 잠깐 기다린다 (화면의 '조회 중' 표시가 보이도록). 계산은 조금 더 길게.
 await wait(url.pathname==='/api/analyze'?350:url.pathname==='/api/comparables'?500:150);
 if(signal?.aborted)abort();
 try{
  const body=options.body?JSON.parse(options.body):null;
  const data=await answer(method,url,body);
  return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
 }catch(e){
  const status=e.status||500,code=e.code||'DEMO_ERROR';
  return new Response(JSON.stringify({error:{code,message:e.message||'가상 데이터 처리 중 오류가 났습니다.'}}),{status,headers:{'Content-Type':'application/json'}});
 }
};

/* ---------- 위성사진 대신 그리는 가짜 지도 타일 ---------- */
// 실제 위성사진은 인터넷의 VWorld 에서만 받을 수 있어 넣을 수 없다. 대신 같은 자리에 들판·숲·길 느낌의 무늬를 그린다.
// 무늬는 세계 좌표로 정해지므로 타일끼리 이어지고, 같은 타일은 한 번만 그린다.
const tileCache=new Map();
const hash=(x,y,s)=>{let h=(x*374761393+y*668265263+s*982451653)|0;h=(h^(h>>>13))*1274126177|0;return ((h^(h>>>16))>>>0)/4294967295};
function smooth(x,y,size,seed){const gx=Math.floor(x/size),gy=Math.floor(y/size),fx=x/size-gx,fy=y/size-gy,u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);
 const a=hash(gx,gy,seed),b=hash(gx+1,gy,seed),c=hash(gx,gy+1,seed),e=hash(gx+1,gy+1,seed);return a+(b-a)*u+(c-a)*v+(a-b-c+e)*u*v}
globalThis.__mockTile=(z,y,x)=>{
 const key=`${z}/${y}/${x}`;if(tileCache.has(key))return tileCache.get(key);
 const cv=document.createElement('canvas');cv.width=cv.height=256;const ctx=cv.getContext('2d'),img=ctx.createImageData(256,256),px=img.data;
 const scale=2**Math.max(0,z-15);   // 확대할수록 무늬를 크게 (실제 땅 크기에 맞춤)
 for(let j=0;j<256;j++)for(let i=0;i<256;i++){
  const wx=(x*256+i)/scale,wy=(y*256+j)/scale;
  const field=smooth(wx,wy,48,1),detail=smooth(wx,wy,6,2),road=(Math.abs((wx%160)-3)<1.4||Math.abs((wy%190)-3)<1.4)?1:0;
  let r,g,b;
  if(road){r=g=b=150+detail*30}
  else if(field>.62){r=55+detail*25;g=78+detail*30;b=48+detail*15}        // 숲
  else if(field>.38){r=118+detail*30;g=122+detail*28;b=82+detail*18}      // 밭
  else{r=140+detail*30;g=128+detail*25;b=104+detail*20}                    // 맨땅·주거
  const k=(j*256+i)*4;px[k]=r;px[k+1]=g;px[k+2]=b;px[k+3]=255;
 }
 ctx.putImageData(img,0,0);
 const urlData=cv.toDataURL('image/jpeg',.72);tileCache.set(key,urlData);return urlData;
};

/* ---------- 화면에 '가상 데이터' 표시 ---------- */
function markDemo(){
 const h1=document.querySelector('.top h1');
 if(h1&&!document.getElementById('demoTag')){const t=document.createElement('span');t.id='demoTag';t.className='demo-tag';t.textContent='가상 데이터';t.title='서버 없이 미리 넣어 둔 장상동 자료로 동작하는 데모입니다. 위성사진은 그림 무늬로 대신합니다.';h1.after(t)}
 document.querySelector('.top a[href="/"]')?.remove();   // '기존 화면' 링크: 파일 하나로 열 때는 갈 곳이 없다
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',markDemo);else markDemo();
