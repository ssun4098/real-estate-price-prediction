// Portfolio snapshots preserve the reviewed view, unlike the independent-only
// analysis export. Network credentials and raw transport data never belong here.
const POLICY='portfolio_frozen_v1';
const DB_NAME='pf-study-v6-portfolio-samples';
const STORE_NAME='samples';
const normalizedKey=value=>String(value).replace(/[^a-z0-9]/gi,'').toLowerCase();
const secretFields=new Set('key keys apikey servicekey confmkey credentials credential authorization proxyauthorization password passwd secret token accesstoken refreshtoken idtoken accesskey accesskeyid secretaccesskey consumerkey consumersecret clientsecret sessiontoken apisecret vworldapikey datagokrapikey jusoapikey kosisapikey sgissecret sig signature auth cookie setcookie cookies'.split(' '));
const transportFields=new Set('raw rawresponse rawresponses rawbody rawpayload responsebody requestbody requestpayload responsepayload payload transport networkresponse networkrequest request response headers requestheaders responseheaders httppayload httprequest httpresponse connectionstring'.split(' '));
const forbiddenKey=key=>secretFields.has(normalizedKey(key))||transportFields.has(normalizedKey(key))||/(?:apikey|servicekey|password|clientsecret|accesstoken|refreshtoken|privatekey)$/.test(normalizedKey(key))||['__proto__','prototype','constructor'].includes(key);
function credentialUrl(value){
 try{
  const url=new URL(value);
  if(url.username||url.password)return true;
  if([...url.searchParams.keys()].some(key=>secretFields.has(normalizedKey(key))||/^(?:xamz|xgoog)/.test(normalizedKey(key))||/(?:apikey|servicekey|accesstoken|secret|signature)$/.test(normalizedKey(key))))return true;
  if(/\/wmts\/1\.0\.0\/[^/]+/i.test(url.pathname))return true;
  return false;
 }catch{return true;}
}
function cleanString(value){
 const urls=value.match(/https?:\/\/[^\s"'<>]+/gi)||[];
 if(urls.length===1&&value.trim()===urls[0]&&credentialUrl(urls[0]))return undefined;
 return value.replace(/https?:\/\/[^\s"'<>]+/gi,url=>credentialUrl(url)?'[인증 URL 제외]':url)
  .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi,'[인증정보 제외]');
}
export function cleanPortfolioValue(value){
 const ancestors=new WeakSet();
 function clean(item){
  if(item===null)return null;
  if(typeof item==='string')return cleanString(item);
  if(typeof item==='boolean')return item;
  if(typeof item==='number')return Number.isFinite(item)?item:null;
  if(item instanceof Date)return Number.isNaN(item.getTime())?null:item.toISOString();
  if(typeof item==='undefined'||typeof item==='function'||typeof item==='symbol')return undefined;
  if(typeof item!=='object')throw new Error('저장할 수 없는 분석 값이 있습니다.');
  if(ancestors.has(item))throw new Error('분석 자료에 순환 참조가 있어 저장할 수 없습니다.');
  ancestors.add(item);
  const result=Array.isArray(item)?item.map(row=>clean(row)??null):Object.fromEntries(Object.entries(item).filter(([key])=>!forbiddenKey(key)).map(([key,row])=>[key,clean(row)]).filter(([,row])=>row!==undefined));
  ancestors.delete(item);
  return result;
 }
 return clean(value);
}
function validEnvelope(item){
 return item&&typeof item==='object'&&typeof item.id==='string'&&!!item.id&&typeof item.name==='string'&&!!item.name.trim()&&item.persistencePolicy===POLICY&&item.readOnly===true&&item.snapshot&&typeof item.snapshot==='object'&&!Array.isArray(item.snapshot)&&item.snapshot.inputs&&typeof item.snapshot.inputs==='object'&&!Array.isArray(item.snapshot.inputs)&&item.snapshot.results&&typeof item.snapshot.results==='object'&&!Array.isArray(item.snapshot.results);
}
export function portfolioMeta(item){
 const input=item?.snapshot?.inputs||{},parcels=Array.isArray(input.parcels)?input.parcels:[];
 const seen=new Set();
 for(let index=0;index<parcels.length;index++){
  const parcel=parcels[index];
  if(parcel&&typeof parcel==='object'&&!Array.isArray(parcel))seen.add(parcel.pnu||`missing-${index}`);
 }
 return {id:item?.id,name:item?.name||'이름 없는 분석',scenario:input.project?.scenario||'',createdAt:item?.capturedAt,capturedAt:item?.capturedAt,parcelCount:seen.size,readOnly:true,persistencePolicy:POLICY,...(typeof item?.isDefault==='boolean'?{isDefault:item.isDefault}:{})};
}
function browserError(action,error){
 if(error?.name==='QuotaExceededError')return new Error('브라우저 저장 공간이 부족합니다. 분석이 저장되지 않았습니다.');
 return new Error(`브라우저에서 분석을 ${action} 못했습니다.${error?.message?' '+error.message:''}`);
}
function openDatabase(){
 return new Promise((resolve,reject)=>{
  if(!globalThis.indexedDB){reject(new Error('이 브라우저에서는 분석 저장소를 사용할 수 없습니다.'));return;}
  let request,settled=false;
  const fail=error=>{if(!settled){settled=true;reject(error);}};
  try{request=globalThis.indexedDB.open(DB_NAME,1);}catch(error){fail(browserError('열지',error));return;}
  request.onupgradeneeded=()=>{const db=request.result;if(!db.objectStoreNames.contains(STORE_NAME))db.createObjectStore(STORE_NAME,{keyPath:'id'});};
  request.onerror=()=>fail(browserError('열지',request.error));
  request.onblocked=()=>fail(new Error('다른 탭에서 저장소를 사용 중입니다. 해당 탭을 닫은 뒤 다시 시도하세요.'));
  request.onsuccess=()=>{if(settled){request.result.close();return;}settled=true;const db=request.result;db.onversionchange=()=>db.close();resolve(db);};
 });
}
async function transact(mode,action,operation){
 const db=await openDatabase();
 return new Promise((resolve,reject)=>{
  let transaction,request,result,settled=false;
  const fail=error=>{if(!settled){settled=true;db.close();reject(browserError(action,error));}};
  try{
   transaction=db.transaction(STORE_NAME,mode);
   request=operation(transaction.objectStore(STORE_NAME));
   request.onsuccess=()=>{result=request.result;};
   request.onerror=()=>fail(request.error);
   transaction.oncomplete=()=>{if(!settled){settled=true;db.close();resolve(result);}};
   transaction.onerror=()=>fail(transaction.error);
   transaction.onabort=()=>fail(transaction.error||new Error('저장이 취소되었습니다.'));
  }catch(error){fail(error);}
 });
}
export async function listBrowserSamples(){
 const items=await transact('readonly','불러오지',store=>store.getAll());
 return items.filter(validEnvelope).map(portfolioMeta).sort((a,b)=>String(b.capturedAt||'').localeCompare(String(a.capturedAt||'')));
}
export async function getBrowserSample(id){
 if(typeof id!=='string'||!id)throw new Error('불러올 분석을 선택하세요.');
 const item=await transact('readonly','불러오지',store=>store.get(id));
 if(!validEnvelope(item))throw new Error('저장된 분석을 찾을 수 없거나 지원하지 않는 형식입니다.');
 return cleanPortfolioValue(item);
}
export async function saveBrowserSample({name,snapshot,displayState={}}){
 const label=typeof name==='string'?name.trim():'';
 if(!label)throw new Error('저장할 분석 이름을 입력하세요.');
 if(!globalThis.crypto?.randomUUID)throw new Error('안전한 저장 식별자를 만들 수 없습니다. HTTPS 또는 로컬 주소에서 다시 시도하세요.');
 const item={id:'portfolio-'+globalThis.crypto.randomUUID(),name:label.slice(0,80),capturedAt:new Date().toISOString(),readOnly:true,persistencePolicy:POLICY,snapshot:cleanPortfolioValue(snapshot),displayState:cleanPortfolioValue(displayState)};
 if(!validEnvelope(item))throw new Error('현재 분석의 입력과 계산 결과를 확인한 뒤 저장하세요.');
 await transact('readwrite','저장하지',store=>store.add(item));
 return item;
}
