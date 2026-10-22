export const MONEY_FACTORS = {'원':1,'만원':10000,'억원':100000000};
export const AREA_FACTORS = {'㎡':1,'평':3.305785};
export const newId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
export const duplicateRow = row => ({...structuredClone(row),id:newId(),actual:false,status:'사용자 가정',sourceStatus:'사용자 가정',source:'사용자 가정',needsReview:true});
export function numericError(text,{required=false,min,max,integer=false}={}) {
 if(String(text??'').trim()==='') return required?'이 입력란을 입력하세요.':'';
 const v=Number(text); if(!Number.isFinite(v))return '유한한 숫자로 입력하세요.';
 if(integer&&!Number.isInteger(v))return '정수로 입력하세요.';
 if(min!=null&&v<min)return `${min} 이상으로 입력하세요.`;
 if(max!=null&&v>max)return `${max} 이하로 입력하세요.`;
 return '';
}
export function validDate(v){if(!/^\d{4}-\d{2}-\d{2}$/.test(v||''))return false;const d=new Date(`${v}T00:00:00Z`);return Number.isFinite(+d)&&d.toISOString().slice(0,10)===v;}
export function normalizeDate(v,format='YYYY-MM-DD'){
 const x=String(v??'').trim();if(!x)return '';
 const sep=format==='YYYY/MM/DD'?'/':format==='YYYY.MM.DD'?'.':'-';
 const parts=x.split(sep);if(parts.length!==3||!parts.every(p=>/^\d+$/.test(p)))return null;
 const d=`${parts[0].padStart(4,'0')}-${parts[1].padStart(2,'0')}-${parts[2].padStart(2,'0')}`;return validDate(d)?d:null;
}
export function parseTsv(text){return String(text||'').replace(/\r/g,'').split('\n').filter(x=>x.trim()).map(x=>x.split('\t'));}
export function convertPasteRows(matrix,columns,mapping,{header=true,units={},dateFormat='YYYY-MM-DD',validateRow}={}){
 const errors=[],rows=[];const seen=Object.values(mapping).filter(v=>v!==''&&v!=null);if(new Set(seen.map(String)).size!==seen.length)errors.push('같은 원본 열을 둘 이상의 항목에 대응시킬 수 없습니다.');
 columns.forEach(c=>{if(c.required&&(mapping[c.key]===''||mapping[c.key]==null))errors.push(`${c.label}: 원본 열을 선택하세요.`);if(c.kind&&mapping[c.key]!==''&&mapping[c.key]!=null&&!(c.kind==='money'?MONEY_FACTORS:AREA_FACTORS)[units[c.key]])errors.push(`${c.label}: 단위를 선택하세요.`)});
 (header?matrix.slice(1):matrix).forEach((cells,i)=>{const row={id:newId(),status:'사용자 가정',sourceStatus:'사용자 가정',actual:false};columns.forEach(c=>{const idx=mapping[c.key],s=idx===''||idx==null?'':String(cells[Number(idx)]??'').trim();const prefix=`${i+(header?2:1)}행 ${c.label}`;
 if(!s){row[c.key]=c.type==='text'||c.type==='date'||c.type==='enum'?'':null;if(c.required)errors.push(`${prefix}: 값을 입력하세요.`);return;}
 if(/^[=+@]/.test(s)||/^-[A-Za-z]/.test(s)){errors.push(`${prefix}: 수식은 사용할 수 없습니다. 값으로 붙여넣으세요.`);return;}
 if(c.type==='number'||c.type==='integer'){const clean=s.replace(/,/g,'');const err=numericError(clean,{min:c.min??0,max:c.max,integer:c.type==='integer'});if(err){errors.push(`${prefix}: ${err}`);return;}const factor=c.kind?(c.kind==='money'?MONEY_FACTORS:AREA_FACTORS)[units[c.key]]:1;row[c.key]=Number(clean)*(factor||1);}
 else if(c.type==='date'){row[c.key]=normalizeDate(s,dateFormat);if(!row[c.key])errors.push(`${prefix}: ${dateFormat} 형식의 실제 날짜를 확인하세요.`);}
 else if(c.type==='enum'){const opts=c.options||[];const found=opts.find(o=>(typeof o==='string'?o:o.value)===s||(typeof o==='object'&&o.label===s));if(!found)errors.push(`${prefix}: 허용된 항목을 선택하세요.`);else row[c.key]=typeof found==='string'?found:found.value;}
 else row[c.key]=s;
 });if(validateRow){const e=validateRow(row)||[];(Array.isArray(e)?e:[e]).filter(Boolean).forEach(x=>errors.push(`${i+(header?2:1)}행: ${x}`));}rows.push(row)});
 if(!rows.length)errors.push('붙여넣을 자료 행이 없습니다.');return {rows,errors};
}
export function recurringDates({start,end,months=1,day='end',maturity,analysisEnd}){
 const errors=[],warnings=[],dates=[];if(!validDate(start)||!validDate(end)||start>end)return {dates,errors:['시작일과 종료일을 확인하세요.'],warnings};
 if(![1,2,3,6,12].includes(Number(months)))return {dates,errors:['지원되는 지급 주기를 선택하세요.'],warnings};
 if(day!=='end'&&(!Number.isInteger(Number(day))||Number(day)<1||Number(day)>31))return {dates,errors:['지급일은 1~31 또는 말일이어야 합니다.'],warnings};
 const a=new Date(`${start}T00:00:00Z`),b=new Date(`${end}T00:00:00Z`);let n=0;
 for(let k=0;k<1200;k+=Number(months)){const base=new Date(Date.UTC(a.getUTCFullYear(),a.getUTCMonth()+k,1));if(base>b)break;const last=new Date(Date.UTC(base.getUTCFullYear(),base.getUTCMonth()+1,0)).getUTCDate();const d=new Date(Date.UTC(base.getUTCFullYear(),base.getUTCMonth(),day==='end'?last:Math.min(Number(day),last))).toISOString().slice(0,10);if(d>=start&&d<=end)dates.push(d);if(++n>600){errors.push('600회를 초과하는 일정은 나누어 작성하세요.');break;}}
 if(!dates.length)errors.push('선택한 기간에 생성되는 지급일이 없습니다.');
 if(maturity&&dates.some(d=>d>maturity))warnings.push('PF 만기 이후 지급일이 있습니다. 실제 약정을 확인하세요.');if(analysisEnd&&dates.some(d=>d>analysisEnd))errors.push('정산 예정일을 초과하는 일정이 있습니다.');warnings.push('공휴일·영업일 조정은 적용하지 않았습니다.');return {dates,errors,warnings};
}
export function eventMode(row){if(row.pctLand!=null)return 'pctLand';if(row.pctRevenue!=null)return 'pctRevenue';return 'amountWon';}
export function setEventMode(row,mode){return {...row,amountWon:null,pctLand:null,pctRevenue:null,amountMode:mode,needsReview:true};}
export function paymentDraft({kind,rows,mode='amountWon',contractDate='',basisWon=null,asOf='',endDate='',maturity=''}){
 const errors=[],warnings=[],events=[];const sum=rows.reduce((a,r)=>a+(Number.isFinite(r.value)?r.value:0),0);
 if(kind==='salesReceipt'&&!validDate(contractDate))errors.push('분양수납은 계약일을 먼저 입력하세요.');
 if(kind==='salesReceipt'&&mode==='pctRevenue'&&!(basisWon>0))errors.push('해당 판매 구간의 기준 분양대금을 입력하세요.');
 if(mode!=='amountWon'&&Math.abs(sum-100)>1e-7)errors.push(`지급 비율 합계가 ${sum}%입니다. 100%가 되도록 확인하세요.`);
 if(mode==='amountWon'&&kind==='land'&&basisWon>0&&Math.abs(sum-basisWon)>1)errors.push('금액 합계와 대표 토지 매입대금이 일치하지 않습니다.');
 if(kind==='land'&&!(basisWon>0))errors.push('대표 토지 매입대금을 먼저 산정하세요.');
 rows.forEach((r,i)=>{if(!validDate(r.date))errors.push(`${i+1}회: 지급·수납일을 확인하세요.`);else{if(asOf&&r.date<asOf)errors.push(`${i+1}회: 과거 실적은 일정 도우미로 변경하지 않습니다.`);if(endDate&&r.date>endDate)errors.push(`${i+1}회: 정산 예정일을 초과했습니다.`);if(kind==='salesReceipt'&&contractDate&&r.date<contractDate)errors.push(`${i+1}회: 계약일보다 수납일이 빠릅니다.`);if(maturity&&r.date>maturity)warnings.push(`${i+1}회: PF 만기 이후 날짜입니다.`);}if(!Number.isFinite(r.value)||r.value<0)errors.push(`${i+1}회: 금액 또는 비율을 입력하세요.`);
 const event={id:newId(),date:r.date,label:r.label||`${i+1}회`,kind,actual:false,status:'사용자 가정',contractDate:kind==='salesReceipt'?contractDate:undefined,amountWon:null,pctLand:null,pctRevenue:null};
 if(kind==='salesReceipt'&&mode==='pctRevenue'){event.amountWon=Number.isFinite(r.value)&&basisWon>0?basisWon*r.value/100:null;event.collectionBasisWon=basisWon;event.collectionPct=r.value;}else event[mode]=r.value;
 events.push(event);});if(!rows.length)errors.push('회차를 추가하세요.');if(new Set(rows.map(r=>r.date)).size!==rows.length)warnings.push('같은 날짜에 여러 회차가 있습니다. 중복 입력인지 확인하세요.');return {events,errors,warnings};
}
export function mergeFutureRows(existing,incoming,{mode='append',asOf='',protectRow=r=>!!r.actual&&!!r.date&&r.date<asOf}={}){const protectedRows=existing.filter(protectRow);return mode==='replace'?[...protectedRows,...incoming]:[...existing,...incoming];}
export function scheduleRevision(flow,next,description){const history=flow.planHistory||[];return {...next,planHistory:[...history,{id:newId(),at:new Date().toISOString(),description,before:{events:structuredClone(flow.events||[]),interestPaymentDates:[...(flow.interestPaymentDates||[])],trust:structuredClone(flow.trust||{}),exit:structuredClone(flow.exit||{})}}]};}
