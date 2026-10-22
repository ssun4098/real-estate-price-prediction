import React,{useEffect,useRef,useState,useId} from 'react';
import {request} from './pf-live-widgets.jsx';
import {DRAFT_KEY,makeDraft,restoreDraft,periodErrors,recentPeriod,todayKorea} from './ui-workflow.mjs';
import './ui-workflow.css';
import {rollingPeriod} from './period-policy.mjs';
import {revenueDiagnostics} from './comparison-diagnostics.mjs';

export function jumpTo(id){if(document.querySelector('.pf-v3-page')){globalThis.dispatchEvent(new CustomEvent('pf-v3-navigate',{detail:{id}}));return;}const node=document.getElementById(id);node?.scrollIntoView({behavior:'smooth',block:'start'});const field=node?.querySelector('input:not(:disabled),button:not(:disabled),select:not(:disabled)');field?.focus({preventScroll:true});}
function RegionCombo({label,level,parent,value,onChange,disabled}){
 const [text,setText]=useState(value?.name||''),[rows,setRows]=useState([]),[open,setOpen]=useState(false),[active,setActive]=useState(-1),[loading,setLoading]=useState(false),[error,setError]=useState('');const id=useId(),seq=useRef(0),lastParent=useRef(parent);
 useEffect(()=>{if(value){setText(value.name);setRows([]);setOpen(false)}else if(lastParent.current!==parent){setText('');setRows([]);setOpen(false)}lastParent.current=parent},[value?.code,parent]);
 useEffect(()=>{if(disabled||!open||text.trim().length<1){setRows([]);return}const n=++seq.current;setLoading(true);const timer=setTimeout(()=>request('/api/regions?'+new URLSearchParams({q:text.trim(),level,parent:parent||'',current:'1'})).then(d=>{if(n===seq.current){setRows(d.items||[]);setError('');setActive(-1)}}).catch(e=>{if(n===seq.current){setRows([]);setError(e.message)}}).finally(()=>{if(n===seq.current)setLoading(false)}),180);return()=>{clearTimeout(timer);seq.current++}},[text,level,parent,disabled,open]);
 const choose=r=>{onChange(r);setText(r.name);setOpen(false);setActive(-1)};
 return <div className="pf-region-combo"><label htmlFor={id}>{label}</label><input id={id} value={text} disabled={disabled} role="combobox" autoComplete="off" aria-autocomplete="list" aria-expanded={open} aria-controls={id+'-list'} aria-activedescendant={active>=0?id+'-'+active:undefined} placeholder={level==='sgg'?'예: 서울특별시 강':'전체 이름 또는 일부 이름'} onFocus={()=>setOpen(true)} onBlur={()=>setTimeout(()=>setOpen(false),120)} onChange={e=>{setText(e.target.value);setOpen(true);if(value)onChange(null)}} onKeyDown={e=>{if(e.key==='ArrowDown'){e.preventDefault();setOpen(true);setActive(x=>Math.min(rows.length-1,x+1))}if(e.key==='ArrowUp'){e.preventDefault();setActive(x=>Math.max(0,x-1))}if(e.key==='Enter'&&open&&active>=0){e.preventDefault();choose(rows[active])}if(e.key==='Escape'){setOpen(false);setActive(-1)}}}/>{open&&!disabled&&<div className="pf-region-options" id={id+'-list'} role="listbox">{loading?<p>지역 목록 확인 중…</p>:error?<p role="alert">{error}</p>:rows.length?rows.map((r,i)=><button type="button" role="option" id={id+'-'+i} aria-selected={active===i} className={active===i?'active':''} key={r.code} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(r)}>{r.name}</button>):<p>{text?'일치하는 지역이 없습니다.':'지역명을 입력하세요.'}</p>}</div>}{text&&!value&&!open&&<small className="pf-field-error">후보에서 지역을 선택하세요.</small>}</div>;
}
export function RegionNavigator({value,onChange,onAddress,disabled}){
 const [meta,setMeta]=useState(null),[notice,setNotice]=useState('');
 useEffect(()=>{if(!disabled)request('/api/regions?q=&level=sgg').then(setMeta).catch(e=>setNotice(e.message))},[disabled]);
 const selected=value?.ri||value?.dong||value?.sgg;
 return <div className="pf-region-navigator"><h3>사업지 지역 찾기</h3><div className="live-fields three"><RegionCombo label="시·군·구 검색" level="sgg" value={value?.sgg} onChange={sgg=>onChange({sgg,dong:null,ri:null})} disabled={disabled}/><RegionCombo label="법정동·읍·면 검색" level="dong" parent={value?.sgg?.code} value={value?.dong} onChange={dong=>onChange({...value,dong,ri:null})} disabled={disabled||!value?.sgg}/><RegionCombo label="법정리 검색 · 해당 시" level="ri" parent={value?.dong?.code} value={value?.ri} onChange={ri=>onChange({...value,ri})} disabled={disabled||!value?.dong||!/[읍면]$/.test(value.dong.name)}/></div><p className="live-note">{selected?`탐색 지역: ${selected.name}`:'지역명을 선택하거나 지도에서 개발 필지를 선택하세요.'} · 가격 비교 지역은 실제 선택한 필지에서 확정합니다.</p><div className="live-actions"><button disabled={disabled||!selected} onClick={()=>onAddress(selected.name)}>이 지역에서 주소 찾기</button><button disabled={disabled} onClick={async()=>{setNotice('공식 목록 갱신 중…');try{const d=await request('/api/regions?refresh=1');setMeta(d);setNotice(d.status==='last_known'?'갱신 실패로 마지막 확인 목록을 사용합니다. '+(d.warnings||[]).join(' · '):'공식 목록을 갱신했습니다. 기존 선택은 유지합니다.')}catch(e){setNotice(e.message)}}}>지역 목록 갱신</button><details><summary>지역 정보·코드 출처</summary><p>{selected?.name||'미확정'} · 코드 {selected?.code||'미확정'}</p><a href="https://www.code.go.kr/stdcode/regCodeL.do" target="_blank" rel="noreferrer">행정표준코드관리시스템</a><p>다운로드: {meta?.downloadedAt||'미확인'} · 다운로드 기준일: {meta?.referenceDate||'제공되지 않음'} · 법적 적용일과 다를 수 있습니다</p></details></div>{notice&&<p role="status" className="live-note">{notice}</p>}</div>;
}
export function LandCacheStatus({local,sgg,busy}){
 const [info,setInfo]=useState(null),[error,setError]=useState('');
 useEffect(()=>{if(!local)return;let stopped=false,inFlight=false;const controller=new AbortController();
  const load=async()=>{if(inFlight)return;inFlight=true;try{const d=await request('/api/land-cache'+(/^\d{5}$/.test(sgg||'')?'?sgg='+sgg:''),{signal:controller.signal});if(!stopped){setInfo(d);setError('')}}catch(e){if(!stopped)setError(e.message)}finally{inFlight=false}};
  load();const timer=busy?setInterval(load,3000):null;return()=>{stopped=true;controller.abort();if(timer)clearInterval(timer)};
 },[local,sgg,busy]);
 if(!local)return <p className="live-note">이 HTML에 저장된 토지자료를 열람 중입니다. 다른 PC에서도 파일에 포함된 자료를 볼 수 있으며, 새 조회는 Python 연결이 필요합니다.</p>;
 const retry=new Set([...(info?.pending||[]),...(info?.failures||[])].map(r=>r.sgg+'-'+r.month)).size;
 return <div className="pf-period-group" data-testid="land-storage-status"><strong>토지 로컬 보관 · 재실행 후 이어받기</strong>
  <p className="live-note" role="status">{error?'보관 상태 확인 실패 · '+error:!info?'저장소 확인 중…':!info.enabled?info.error||'이번 실행은 임시 보관만 사용합니다.':`${sgg?'선택 시군구':'전체 보관 지역'} · 보관 ${info.completedMonths}개월 / ${info.storedRows.toLocaleString()}행 · 이어받기·재확인 필요 ${retry}개월`}</p>
  <small>같은 지역을 조회하면 보관한 월을 재사용합니다. 최근 2개월은 1시간, 과거 월은 30일 후 재확인합니다. 한도가 회복되면 일반 조회 버튼으로 이어받으세요.</small>
  <p className="live-note">다른 PC에 전달하려면 ‘분석 저장’ 후 생성된 HTML을 전달하세요. 현재 분석의 토지자료가 포함되며 인증키는 포함되지 않습니다. 내 PC의 저장소가 온라인 사이트에 자동 공유되지는 않습니다.</p>
 </div>;
}
export function PeriodControls({input,onRefresh,disabled}){
 const target=rollingPeriod(),query=input.comparables?.landQuery||input.comparables?.query;
 const savedRange=!!query&&(query.periodMode!=='rolling60'||query.endExclusive!==target.endExclusive);
 return <div className="pf-periods" data-testid="automatic-periods">
  <div className="live-actions"><strong>직전 60개월 · 매월 1일은 제외</strong><button disabled={disabled} onClick={onRefresh}>다음 조회기간 확인</button></div>
  <div className="live-fields two">{[['land','토지 매매 실거래가','계약일'],['revenue','청약홈 민영 아파트 분양가격','모집공고일']].map(([kind,label,basis])=><div className="pf-period-group" key={kind}>
   <strong>{label}</strong><div className="live-fields two"><label>다음 조회 시작일<input type="text" aria-label={label+' 다음 조회 시작일'} value={target.startDate} readOnly/></label><label>다음 조회 종료일 · 포함<input type="text" aria-label={label+' 다음 조회 종료일'} value={target.endDate} readOnly/></label></div>
   <small>{basis} 기준 · 종료 경계 {target.endExclusive}은 포함하지 않습니다.</small>
  </div>)}</div>
  <p className="live-note">한국시간 기준입니다. 지도에서 필지를 선택하고 지역코드가 확인되면 해당 지역의 60개월 자료를 조회합니다. 실행·새로고침·저장 결과 복구만으로는 토지·분양 API를 호출하지 않습니다. 매월 예약 수집은 하지 않으며, 다음 필지 선택·재조회 시 기간이 이동합니다.</p>
  {query&&<p className={'live-note'+(savedRange?' warning':'')} role="status">현재 보관·조회 자료의 기간: 토지 {query.landStartDate||query.landStart||query.start||'미확인'} ~ {query.landEndDate||query.landEnd||query.end||'미확인'}{query.endExclusive?' · '+query.endExclusive+' 제외':''}. {savedRange?'이전 기간의 자료를 표시하고 있습니다. 원래 기간은 유지하며, 필지를 새로 선택하면 위의 60개월로 조회합니다.':'위 기간의 수집 완료 여부는 출처·수집 상태에서 확인하세요.'}</p>}
  {!query&&<p className="live-note">위 날짜는 조회할 기간입니다. 아직 자료가 모두 확보됐다는 뜻은 아닙니다. 지연 신고·정정·취소 자료가 이후 반영될 수 있습니다.</p>}
 </div>;
}
export function WorkflowGuide({state,validation}){return <><nav className="pf-workflow" aria-label="사업수지 입력 단계">{state.steps.map((s,i)=><button key={s.target} onClick={()=>jumpTo(s.target)} aria-label={`${i+1}단계 ${s.label} ${s.ready?'확인됨':'입력 필요'}`} className={s.ready?'done':''}><span>{String(i+1).padStart(2,'0')}</span><strong>{s.label}</strong><small>{s.ready?'확인됨':s.hint}</small></button>)}</nav>{validation?.fieldErrors?.length>0&&<div className="live-notice error" role="alert"><strong>입력을 확인하세요. 영향받지 않는 결과는 유지합니다.</strong><ul>{validation.fieldErrors.map((e,i)=><li key={i}><button onClick={()=>jumpTo(({development:'live-development',revenue:'live-compare',land:'live-parcels',costs:'live-costs',cashflow:'live-cashflow',okr:'live-cashflow'})[e.section]||'live-conditions')}>{e.message}</button></li>)}</ul></div>}</>}
export function LockNotice({children,target}){return <div className="pf-lock-note" role="status">{children}<button onClick={()=>jumpTo(target)}>먼저 입력할 곳으로 이동</button></div>}
export function DraftKeeper({input,enabled,onRestore}){
 const [offer,setOffer]=useState(null),[checked,setChecked]=useState(false),[message,setMessage]=useState(''),initial=useRef(null),last=useRef('');
 useEffect(()=>{if(!enabled)return;try{const raw=localStorage.getItem(DRAFT_KEY);if(raw){const draft=JSON.parse(raw);restoreDraft(draft);setOffer(draft)}}catch(e){setMessage('초안을 읽을 수 없습니다. 보관함 삭제 후 다시 사용할 수 있습니다.')}initial.current=JSON.stringify(input);setChecked(true)},[enabled]);
 useEffect(()=>{if(!enabled||!checked||offer)return;const current=JSON.stringify(input);if(initial.current===current)return;const timer=setTimeout(()=>{try{const data=makeDraft(input),body=JSON.stringify(data);const signature=JSON.stringify(data.input);if(signature===last.current)return;localStorage.setItem(DRAFT_KEY,body);last.current=signature;setMessage('입력 초안 보관 · '+new Date(data.savedAt).toLocaleTimeString('ko-KR'))}catch(e){setMessage('초안 보관 실패 · '+e.message)}},800);return()=>clearTimeout(timer)},[input,enabled,checked,offer]);
 if(!enabled)return null;
 const remove=()=>{try{localStorage.removeItem(DRAFT_KEY);setOffer(null);initial.current=JSON.stringify(input);last.current='';setMessage('초안을 삭제했습니다. 다음 입력 변경부터 다시 보관합니다.')}catch(e){setMessage('초안 삭제 실패 · '+e.message)}};
 return <div className="pf-draft"><span role="status">{offer?`${new Date(offer.savedAt).toLocaleString('ko-KR')}의 미저장 입력 초안이 있습니다.`:message||'입력 변경 시 이 브라우저에 초안을 보관합니다.'}</span>{offer&&<button onClick={()=>{try{onRestore(restoreDraft(offer));setOffer(null);setMessage('초안 복구 완료 · 속성·비교사례를 다시 조회하세요.')}catch(e){setMessage(e.message)}}}>초안 복구</button>}<button onClick={remove}>초안 삭제</button></div>;
}
export function RevenueStatus({input,result,compact=false,onQuery,queryState={},queryDisabled=false}){
 const revenue=result?.results?.revenue||{};
 if(queryState.loading)return <div className="v4-comparison-reason" role="status"><p>선택 필지의 최근 60개월 분양자료와 위치를 확인하고 있습니다. 최초 조회는 수 분이 걸릴 수 있습니다.</p><button disabled>분양자료 조회 중</button></div>;
 if(Number.isFinite(revenue.representativeWon))return <p className="live-note">{!revenue.points?.length?'사례 분포 미확보 · 수입표에는 사용자 가정을 적용합니다.':`현재 계산 ${revenue.stats?.n||0}단지 · ${(revenue.stats?.n||0)<5?'사례 부족: 개별 점과 대표액으로 표시합니다.':'사례 분포를 세로 박스플롯으로 표시합니다.'}`}</p>;
 const issues=revenueDiagnostics(input,result);
 const queryAction=onQuery&&<button onClick={onQuery} disabled={queryDisabled}>{queryState.error?'분양자료 다시 조회':'선택 필지 분양자료 조회'}</button>;
 if(compact)return <div className="v4-comparison-reason" role={queryState.error?'alert':'status'}><p>{queryState.error||issues[0]?.message}</p>{queryAction}<button onClick={()=>jumpTo('live-compare')}>미산출 원인·해결 보기</button></div>;
 return <div className="live-notice v4-comparison-notice" role="status"><strong>분양수입 미산출 원인</strong>{queryState.error&&<p role="alert">{queryState.error}</p>}{queryAction}{issues.map(item=><div key={item.code}><p>{item.message}</p><button onClick={()=>jumpTo(item.target)}>{item.action}</button></div>)}<p>미확보 분양수입을 0원으로 처리하지 않습니다.</p></div>;
}
