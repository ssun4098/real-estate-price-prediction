// Exact current-plan and register classification shared by boundary validation.
export const ZONE_POOL='녹지·관리·농림·자연환경보전',JIMOK_POOL='전·답·과수원·목장용지',JIMOK_OTHER='기타·미확인';
const ZONE_CODES={UQA100:['주거지역','주거'],UQA110:['전용주거지역','주거'],UQA111:['제1종전용주거지역','주거'],UQA112:['제2종전용주거지역','주거'],UQA120:['일반주거지역','주거'],UQA121:['제1종일반주거지역','주거'],UQA122:['제2종일반주거지역','주거'],UQA123:['제3종일반주거지역','주거'],UQA130:['준주거지역','주거'],UQA200:['상업지역','상업'],UQA210:['중심상업지역','상업'],UQA220:['일반상업지역','상업'],UQA230:['근린상업지역','상업'],UQA240:['유통상업지역','상업'],UQA300:['공업지역','공업'],UQA310:['전용공업지역','공업'],UQA320:['일반공업지역','공업'],UQA330:['준공업지역','공업'],UQA400:['녹지지역','녹지'],UQA410:['보전녹지지역','녹지'],UQA420:['생산녹지지역','녹지'],UQA430:['자연녹지지역','녹지'],UQB001:['관리지역','관리'],UQB100:['계획관리지역','관리'],UQB200:['생산관리지역','관리'],UQB300:['보전관리지역','관리'],UQC001:['농림지역','농림'],UQD001:['자연환경보전지역','자연환경보전']};
const ZONE_NAMES=Object.fromEntries(Object.entries(ZONE_CODES).map(([code,[name,broad]])=>[name,[code,broad]]));
const JIMOK_NAMES='전 답 과수원 목장용지 임야 광천지 염전 대 공장용지 학교용지 주차장 주유소용지 창고용지 도로 철도용지 제방 하천 구거 유지 양어장 수도용지 공원 체육용지 유원지 종교용지 사적지 묘지 잡종지'.split(' ');
const JIMOK_CODES=Object.fromEntries(JIMOK_NAMES.map((name,i)=>[String(i+1).padStart(2,'0'),name]));
const clean=x=>String(x??'').replace(/\s+/g,'');
export function classifyZone(value,sourceCode=null){
 const raw=value??'',code=String(sourceCode||'').trim(),name=clean(value)==='자연환경보전'?'자연환경보전지역':clean(value),named=ZONE_NAMES[name],coded=ZONE_CODES[code];
 if((coded&&name&&(!named||named[1]!==coded[1]||name!==coded[0]))||(code&&!coded&&named))return {status:'conflict',raw,code,broadClass:null,matchKey:null};
 const broad=coded?.[1]||(!code?named?.[1]:null)||null;
 return {status:broad?'ready':'unknown',raw,code:code||named?.[0]||null,broadClass:broad,matchKey:['녹지','관리','농림','자연환경보전'].includes(broad)?ZONE_POOL:broad};
}
export function classifyJimok(value,sourceCode=null){
 const raw=value??'',name=clean(value)==='대지'?'대':clean(value),code=String(sourceCode||'').trim(),coded=code?JIMOK_CODES[code.padStart(2,'0')]:null;
 const conflict=!!(code&&((!coded&&JIMOK_NAMES.includes(name))||(coded&&name&&coded!==name))),canonical=conflict?null:coded||(!code&&JIMOK_NAMES.includes(name)?name:null);
 return {status:conflict?'conflict':canonical?'ready':'unknown',raw,code:code||null,name:canonical,matchKey:['전','답','과수원','목장용지'].includes(canonical)?JIMOK_POOL:canonical==='대'?'대':canonical?JIMOK_OTHER:null};
}
const missingZones=new Set(['','-','미상','미정','미확인','미지정','없음','용도미지정','용도지역미지정','용도지역미확인','용도지역미상','용도지역없음']);
const missingJimoks=new Set(['','-','미상','미정','미확인','미지정','없음','지목미상','지목미확인','지목없음']);
const isMissing=(value,names)=>value==null||(typeof value==='string'&&names.has(clean(value)));
export const missingTransactionZone=value=>isMissing(value,missingZones);
export function classifyTransactionZone(value,sourceCode=null){
 const result=classifyZone(value,sourceCode);
 if(result.status==='unknown'&&!sourceCode&&isMissing(value,missingZones))return {...result,status:'missing',matchKey:ZONE_POOL};
 return result;
}
export function classifyTransactionJimok(value,sourceCode=null){
 const result=classifyJimok(value,sourceCode);
 if(result.status==='unknown'&&!sourceCode&&isMissing(value,missingJimoks))return {...result,status:'missing',matchKey:JIMOK_OTHER};
 return result;
}
export const landGroupLabel=(zone,jimok)=>(zone===ZONE_POOL?ZONE_POOL+'·미확인':zone)+' · '+jimok;
export const classificationStatus=result=>result.status==='ready'?'known':result.status==='missing'?'missing':'unclassified';
