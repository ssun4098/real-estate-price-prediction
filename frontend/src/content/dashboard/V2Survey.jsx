import React,{useState,useEffect} from 'react';
import {DataComponent} from './data-component.jsx';
import {Field,Select,number,safeUrl,uid} from './pf-live-widgets.jsx';
import {evaluateSite,REALTIME_NOTICE} from './v2-policy.mjs';
import {withoutRetailSurvey,isOutOfScopeFacility} from './map-overlays.mjs';
import './v2-survey.css';
const statusLabel={success:'조회 성공',empty:'자료 없음',error:'조회 실패',credentials_missing:'인증 미준비',permission_required:'추가 권한 필요',unavailable:'미확보',needs_configuration:'설정 필요',partial:'일부 확인',not_requested:'조회 전'};
const label=x=>x?.statusLabel||statusLabel[x?.status]||x?.status||'미확보';
const val=x=>x==null||x===''?'미확보':typeof x==='object'?JSON.stringify(x):String(x);
const temporalLabels={current:'현재 제공자료 · 과거 시점 재현 아님',reference_year_current_revision:'해당 기준연도 자료 · 현재 수정내역 반영',statistical_period:'통계 작성기간 기준 자료',statistical_period_current_revision:'통계 작성기간 · 현재 수정내역 반영'};
function Source({item}){const s=item?.source||item||{};const url=safeUrl(s.url||s.sourceUrl);return <span className="v2-source">{url?<a href={url} target="_blank" rel="noreferrer">{s.title||s.label||'공식 확인 경로'} ↗</a>:'출처 미확보'} · 기준 {item?.referencePeriods?.join?.(', ')||item?.referenceDate||'미제공'} · 조회 {item?.queriedAt||'조회 전'}</span>}
const PUBLIC_FIELDS={
 pnu:'필지 고유번호',PNU:'필지 고유번호',ldCode:'법정동 코드',ldCodeNm:'법정동',
 legalDongCode:'법정동 코드',legalDongName:'법정동',mnnmSlno:'지번',mnnm:'본번',slno:'부번',
 regstrSeCode:'대장 구분 코드',regstrSeCodeNm:'대장 구분',lndcgrCode:'지목 코드',lndcgrCodeNm:'지목',
 lndpclAr:'대장면적',areaM2:'면적',landCategory:'지목',jimok:'지목',
 lndUseSituCode:'토지 이용상황 코드',lndUseSituCodeNm:'토지 이용상황',ladUseSittnNm:'토지 이용상황',
 tpgrphHgCodeNm:'지형 높이',tpgrphFrmCodeNm:'지형 형상',roadSideCodeNm:'도로 접면',
 prposArea1Nm:'용도지역 1',prposArea2Nm:'용도지역 2',
 prposAreaDstrcCode:'지역·지구 코드',prposAreaDstrcCodeNm:'지정명',
 cnflcAt:'저촉 구분 코드',cnflcAtNm:'저촉 여부',
 posesnSeCode:'소유 구분 코드',posesnSeCodeNm:'소유 구분',cnrsPsnCo:'공유인 수',
 stdrYm:'기준연월',resdncSeCodeNm:'거주지 구분',nationInsttSeCodeNm:'국가기관 구분',
 ownshipChgCauseCodeNm:'소유권 변동 원인',ownshipChgDe:'소유권 변동일',
 buldNm:'건물명',bldNm:'건물명',buldMnnm:'건물 본번',buldSlno:'건물 부번',
 buldTotar:'연면적',totArea:'연면적',archArea:'건축면적',platArea:'대지면적',
 gisIdntfcNo:'공간정보 식별번호',buldIdntfcNo:'건물 식별번호',buldKndCodeNm:'건물 종류',
 buldDongNm:'건물 동명',buldMainAtachSeCodeNm:'주건축물·부속건축물 구분',
 buldPlotAr:'건물 대지면적',buldBildngAr:'건축면적',buldHg:'건물 높이',
 mainPrposCodeNm:'주용도',strctCodeNm:'구조',detailPrposCodeNm:'세부 용도',buldPrposClCodeNm:'건물 용도 분류',
 prmisnDe:'허가일',useConfmDe:'사용승인일',manageNo:'관리번호',registDt:'등록일',
 groundFloorCo:'지상층수',undgrndFloorCo:'지하층수',grndFlrCnt:'지상층수',ugrndFlrCnt:'지하층수',
 mainPurpsCdNm:'주용도',strctCdNm:'구조',useAprDay:'사용승인일',
 pblntfPclnd:'공시지가',priceWonPerM2:'공시지가',stdrYear:'기준연도',stdrMt:'기준월',
 lastUpdtDt:'최종 갱신일',sourceUpdatedAt:'원천 갱신일',year:'기준연도',month:'기준월',
 address:'주소',jibunAddress:'지번주소',roadAddress:'도로명주소',rnAdres:'도로명주소',
 name:'명칭',label:'항목명',category:'유형',group:'분류',unit:'단위',value:'값',
 regionName:'지역명',regionCode:'지역 코드',period:'기준시점',referenceDate:'기준일',
 distanceKm:'직선거리',pointBasis:'위치 근거',sourceId:'출처 식별자',
 candidateKind:'검색 후보 구분',parentName:'본시설명 후보',inclusionReason:'집계·제외 근거',included:'지도·개수 집계',entityId:'연결 대표 후보',groupingRuleVersion:'정리 규칙 버전',
 normalizedName:'비교용 시설명',fullAddress:'원천 전체주소',memberIds:'같은 대표점으로 묶인 후보',subsidiaryIds:'연결한 부속 장소',entityStatus:'시설 후보 상태',sourceRecordId:'원천 기록 식별자',duplicateCount:'묶인 중복 후보 수',
 ORG_NM:'작성기관',ORG_ID:'작성기관 코드',TBL_NM:'통계표명',TBL_ID:'통계표 코드',
 ITM_NM:'통계항목',ITM_ID:'통계항목 코드',ITM_NM_ENG:'통계항목 영문명',
 DT:'값',UNIT_NM:'단위',UNIT_NM_ENG:'단위 영문명',PRD_DE:'통계 기준시점',
 PRD_SE:'통계 주기 코드',LST_CHN_DE:'통계 최종 수정일',
 C1:'분류 1 코드',C1_NM:'분류 1 명칭',C1_OBJ_NM:'분류 1 구분',
 C2:'분류 2 코드',C2_NM:'분류 2 명칭',C2_OBJ_NM:'분류 2 구분',
 C3:'분류 3 코드',C3_NM:'분류 3 명칭',C3_OBJ_NM:'분류 3 구분',
 C4:'분류 4 코드',C4_NM:'분류 4 명칭',C4_OBJ_NM:'분류 4 구분',
 adm_cd:'행정구역 코드',adm_nm:'행정구역명',base_year:'기준연도',
 tot_ppltn:'총인구',tot_house:'총주택 수',tot_family:'총가구 수',avg_age:'평균연령',
 longitude:'경도',latitude:'위도',lon:'경도',lat:'위도',
 status:'조회 상태',statusLabel:'조회 상태',note:'설명',reason:'확인 사항',
 dimensions:'분류 기준',properties:'공개 속성',geometry:'원천 도형',coordinates:'원천 좌표'
};
const PUBLIC_UNITS={lndpclAr:'㎡',areaM2:'㎡',buldTotar:'㎡',totArea:'㎡',archArea:'㎡',platArea:'㎡',buldPlotAr:'㎡',buldBildngAr:'㎡',buldHg:'m',groundFloorCo:'층',undgrndFloorCo:'층',grndFlrCnt:'층',ugrndFlrCnt:'층',cnrsPsnCo:'명',pblntfPclnd:'원/㎡',priceWonPerM2:'원/㎡',distanceKm:'km'};
const PUBLIC_PRIORITY=['DT','ITM_NM','PRD_DE','UNIT_NM','C1_NM','C2_NM','C3_NM','lndcgrCodeNm','lndpclAr','prposAreaDstrcCodeNm','cnflcAtNm','posesnSeCodeNm','buldNm','bldNm','buldTotar','groundFloorCo','ldCodeNm','mnnmSlno','name','address','value','unit','period'];
function PublicField({name}){const title=PUBLIC_FIELDS[name]||name;return <>{title}{title!==name&&<small className="v2-field-origin">{name}</small>}</>}
function PublicValue({value,field}){
 const [expanded,setExpanded]=useState(false);
 if(value==null||value==='')return <span className="v2-value-missing">미제공</span>;
 if(typeof value==='object'){
  const entries=Object.entries(value);
  if(!entries.length)return <span className="v2-value-missing">제공 항목 없음</span>;
  return <details className="v2-nested-value" onToggle={event=>{if(event.target===event.currentTarget)setExpanded(event.currentTarget.open)}}><summary>하위 자료 {entries.length}개</summary>{expanded&&<dl className="v2-public-fields">{entries.map(([key,child])=><div key={key}><dt>{Array.isArray(value)?`${Number(key)+1}번`:<PublicField name={key}/>}</dt><dd><PublicValue value={child} field={key}/></dd></div>)}</dl>}</details>;
 }
 if(typeof value==='boolean')return <>{value?'예':'아니요'}</>;
 const unit=PUBLIC_UNITS[field];
 return <>{String(value)}{unit&&<span className="v2-value-unit"> {unit}</span>}</>;
}
function PublicRecord({row,index}){
 const entries=row&&typeof row==='object'&&!Array.isArray(row)?Object.entries(row):[['value',row]];
 entries.sort(([a],[b])=>{
  const x=PUBLIC_PRIORITY.indexOf(a),y=PUBLIC_PRIORITY.indexOf(b);
  return (x<0?PUBLIC_PRIORITY.length:x)-(y<0?PUBLIC_PRIORITY.length:y);
 });
 const fields=list=><dl className="v2-public-fields">{list.map(([key,value])=><div key={key}><dt><PublicField name={key}/></dt><dd><PublicValue value={value} field={key}/></dd></div>)}</dl>;
 return <article className="v2-public-record"><h5>자료 {index+1}<span>{entries.length}개 항목</span></h5>{entries.length?fields(entries.slice(0,8)):<p>제공된 항목이 없습니다.</p>}{entries.length>8&&<details className="v2-additional-fields"><summary>나머지 {entries.length-8}개 항목 보기</summary>{fields(entries.slice(8))}</details>}</article>;
}
function PublicRows({rows,title}){
 const [page,setPage]=useState(0),pageCount=Math.max(1,Math.ceil(rows.length/20));
 useEffect(()=>setPage(0),[rows]);
 const currentPage=Math.min(page,pageCount-1),start=currentPage*20;
 return <div className="v2-public-data" data-reviewed-rows><p className="live-note">원천 기록 기준 {rows.length}건 중 {start+1}–{Math.min(start+20,rows.length)}건 · 한국어 항목 아래 원자료 필드명을 함께 표시합니다.</p><div className="v2-public-records" role="region" aria-label={`${title} 공개자료`} tabIndex={0}>{rows.slice(start,start+20).map((row,index)=><PublicRecord key={`${start+index}`} row={row} index={start+index}/>)}</div><div className="v2-public-pager"><span>페이지당 20건</span><div><button type="button" disabled={currentPage===0} aria-label={`${title} 이전 자료`} onClick={()=>setPage(Math.max(0,currentPage-1))}>이전</button><span aria-live="polite">{currentPage+1} / {pageCount}</span><button type="button" disabled={currentPage+1>=pageCount} aria-label={`${title} 다음 자료`} onClick={()=>setPage(Math.min(pageCount-1,currentPage+1))}>다음</button></div></div><p className="v2-public-print-note">인쇄에는 현재 페이지에서 펼친 자료만 포함됩니다.</p></div>;
}
function Item({title,item}){
 const [expanded,setExpanded]=useState(false);
 return <div className="v2-evidence-item"><h4>{title} <small>{label(item)}</small></h4><p>{item?.reason||item?.note||item?.message||temporalLabels[item?.temporalBasis]||'항목별 제공 여부와 시점을 확인합니다.'}</p>{Array.isArray(item?.rows)&&item.rows.length>0&&<details className="v2-public-details" onToggle={event=>{if(event.target===event.currentTarget)setExpanded(event.currentTarget.open)}}><summary>공개 자료 확인 · 총 {item.rows.length}건</summary>{expanded&&<PublicRows rows={item.rows} title={title}/>}</details>}<Source item={item}/>{item?.warnings?.length>0&&<p className="live-note warning">{item.warnings.map(w=>typeof w==='string'?w:w.message).join(' · ')}</p>}</div>;
}
function attribute(p,key){const x=p?.attributes?.[key]??p?.[key];return Array.isArray(x)?{status:x.length?'success':'empty',rows:x}:x&&typeof x==='object'?x:{status:'unavailable',rows:[]};}
function buildingState(p){const b=attribute(p,'buildings');if(b.rows?.length)return `공개자료 ${b.rows.length}행 확인`;return ['success','empty','호출 확인','자료 없음'].includes(b.status)?'조회 0건 · 현장 확인 필요':label(b)+' · 나대지 판정 불가';}
export function BasicSurvey({parcels=[],survey,state={},selected,onSelect,onRetry}){
 const rows=parcels.map((p,i)=>({...p,sequence:i+1}));
 const current=rows.find(r=>r.pnu===selected)||rows[0];
 const price=current?.officialLandPrice;
 return <section id="live-survey" className="v2-survey"><div className="live-heading"><div><span>02-B</span><h2>토지신탁 기본조사</h2></div><span className="live-note">{state?.loading?'조회 중':state?.error?'조회 실패':state?.offline?'Python 연결 필요':rows.length?'선택 필지별 확인':'필지 선택 전'}</span></div>{state?.error&&<p className="live-note warning" role="alert">{state.error} {onRetry&&<button disabled={state.loading||state.offline} onClick={onRetry}>기본조사 다시 조회</button>}</p>}<DataComponent id="pf-v2-basic-survey" queryId="liveSurvey" kind="table" title="선택 부지 기본조사" sourceRows={rows} displayRows={rows}><div className="live-table-scroll"><table><thead><tr><th>순번</th><th>토지면적 ㎡</th><th>지목</th><th>위치</th><th>건축물 여부</th></tr></thead><tbody>{rows.map(p=><tr key={p.pnu} className={current?.pnu===p.pnu?'v2-selected-row':''} onClick={()=>onSelect(p.pnu)}><td><button onClick={()=>onSelect(p.pnu)} aria-label={`${p.sequence}번 필지 상세`}>{p.sequence}</button></td><td className="num">{number(p.areaM2,2)}<small>{p.areaM2==null?'대장 면적 미확보':''}</small></td><td>{p.jimok||p.landCategory||attribute(p,'landRegister').rows?.[0]?.lndcgrCodeNm||attribute(p,'characteristics').rows?.[0]?.lndcgrCodeNm||'미확보'}</td><td><button className="live-text-button" onClick={()=>onSelect(p.pnu)}>{p.address||p.legalDongName||p.pnu}</button><small>PNU {p.pnu}</small></td><td>{buildingState(p)}</td></tr>)}</tbody></table></div>{!rows.length&&<p className="live-note">지도에서 필지를 선택하면 순번·대장 면적·지목·위치·공개 건축물 조회 상태를 표시합니다.</p>}</DataComponent>{current&&<div className="live-panel v2-parcel-detail"><h3>{current.sequence}번 필지 · {current.address||current.pnu}</h3><p className="live-note">확인된 공개 속성입니다. 등기·현장·인허가 검토 완료를 뜻하지 않습니다. 필지의 여러 속성행을 토지면적에 중복 가산하지 않습니다.</p><div className="v2-detail-grid"><Item title="토지임야·대장" item={attribute(current,'landRegister')}/><Item title="토지 특성" item={attribute(current,'characteristics')}/><Item title="용도지역·토지이용계획" item={attribute(current,'landUse')}/><Item title="소유 구분 등 공개 속성" item={attribute(current,'ownership')}/><Item title="기존 건물" item={attribute(current,'buildings')}/><div className="v2-evidence-item"><h4>공시지가 참고 <small>{label(price)}</small></h4>{price?.rows?.length?price.rows.map((r,i)=><p key={i}><strong>{number(r.priceWonPerM2,0)} 원/㎡</strong> · 기준 {r.year||'연도 미확보'}{r.month?`년 ${r.month}월`:''} · 원천 갱신 {r.sourceUpdatedAt||'미제공'}</p>):<p>가격 자료 미확보</p>}<Source item={price}/><p className="live-note warning">실거래가·매입대금·장부가·감정평가금액과 구분하며 사업수지 가격에 자동 적용하지 않습니다.</p></div></div><h4>별도 확인이 필요한 자료</h4><div className="v2-detail-grid">{[['registry','등기부'],['ownerNames','개인 소유자 성명'],['bookValue','위탁자 장부가'],['appraisalValue','개별 사업 감정평가금액']].map(([k,t])=><Item key={k} title={t} item={survey?.unavailable?.[k]}/>)}</div></div>}</section>;
}
function FacilityCandidateEvidence({facilities}){
 const candidates=facilities?.candidates||[];
 if(!candidates.length)return null;
 const excluded=candidates.filter(row=>!row.included).length;
 return <details className="live-details"><summary>검색 원자료·중복 정리 근거 {candidates.length}건 · 개별 집계 제외 {excluded}건</summary><p className="live-note">학교·산·하천·산업단지·하수처리장에 해당하는 원천 분류와 본시설 이름을 함께 확인한 대표점만 지도와 거리 구간별 개수에 사용합니다. 1km 이하, 1km 초과~3km 이하, 3km 초과~5km 이하는 서로 중복되지 않습니다. 입구·주차장 등은 별도 시설로 세지 않습니다. 동명·동일 지역·300m 이내 본시설 후보를 묶되 공공하수처리시설 같은 일반명칭은 전체주소도 일치해야 합니다. 부속 장소는 동명 후보가 2km 이내 한 곳일 때만 연결합니다. 공식 시설 경계나 고유 식별자가 없어 실제 시설 수를 확정한 결과는 아닙니다.</p><DataComponent id="pf-v5-facility-candidates" queryId="liveSurvey" kind="table" title="주변시설 검색 후보와 집계 근거" sourceRows={candidates} displayRows={candidates}><PublicRows rows={candidates} title="주변시설 검색 후보와 집계 근거"/></DataComponent></details>;
}
export function SiteContext({survey,state,criteria=[],onCriteria,disabled}){
 survey=withoutRetailSurvey(survey);
 criteria=criteria.filter(c=>!isOutOfScopeFacility(c));
 const items=survey?.indicators||[],evaluation=evaluateSite(items,criteria);
 const amend=(id,k,v)=>onCriteria(criteria.map(c=>c.id===id?{...c,[k]:v}:c));
 return <section id="live-site-context" className="v2-survey"><div className="live-heading"><div><span>02-C</span><h2>입지·수요·사업계획 검토</h2></div></div><p className="live-note">{state?.loading?'현재 선택 조건 조회 중 · 이전 조사 결과는 사용하지 않습니다.':state?.offline?'Python 연결 후 주변시설·통계 조회 필요':`조사 범위 ${survey?.query?.radiusKm??'미설정'}km · 분석 기준일 ${survey?.query?.asOf||'미확보'}`} · 원천 기준시점과 조회일은 별도 확인합니다.</p><div className="live-panel"><h3>공개·실측 지표</h3><DataComponent id="pf-v2-site-indicators" queryId="liveSurvey" kind="table" title="입지 지표와 자료 상태" sourceRows={items} displayRows={items}><div className="live-table-scroll"><table><thead><tr><th>지표</th><th>값</th><th>단위</th><th>범위·출처·해석</th></tr></thead><tbody>{items.map(i=><tr key={i.id}><td>{i.label}</td><td className="num">{Number.isFinite(i.value)?number(i.value,2):'미확보'}</td><td>{i.unit||'미제공'}</td><td>{i.note||'별도 범위 확인'}<small>{i.sourceId||'출처 미확보'}</small></td></tr>)}</tbody></table></div></DataComponent>{!items.length&&<p className="live-note">확인된 지표가 아직 없습니다. 결측·비공개·미조회 값을 0으로 채우지 않습니다.</p>}<div className="v2-detail-grid">{Object.entries(survey?.statistics||{}).map(([key,item])=><Item title={`${key.toUpperCase()} 통계`} item={item} key={key}/>)}{Object.entries(survey?.facilities?.referenceLayers||{}).map(([key,item])=><Item title={`${item.label||item.title||key} 지정구역 · 시설 수와 구분`} item={item} key={key}/>)}{Object.entries(survey?.facilities?.services||{}).map(([key,item])=><Item title={`${item.label||item.title||key} 시설`} item={item} key={key}/>)}</div>{survey?.facilities?.items?.length>0&&<details className="live-details"><summary>본시설 대표점 후보 {survey.facilities.items.length}개</summary><div className="live-table-scroll"><table><thead><tr><th>시설</th><th>유형</th><th>직선거리</th><th>위치·근거</th></tr></thead><tbody>{survey.facilities.items.map(i=><tr key={i.id}><td>{i.name}</td><td>{i.category||i.group}</td><td>{Number.isFinite(i.distanceKm)?number(i.distanceKm,3)+' km':'미산출'}</td><td>{i.pointBasis||'원천 위치 확인'}<small>{i.sourceId}</small></td></tr>)}</tbody></table></div></details>}<FacilityCandidateEvidence facilities={survey?.facilities}/></div><div className="live-panel"><div className="live-panel-label"><h3>사용자 설정 입지 평가</h3><button disabled={disabled} onClick={()=>onCriteria([...criteria,{id:uid(),indicatorId:'',direction:'',min:null,max:null,weight:null}])}>평가 지표 추가</button></div><p className="live-note">방향·하한·상한·가중치를 모두 입력한 뒤 계산합니다. 구간 안에서는 선형 환산, 밖에서는 0~100점으로 제한합니다. 가중치 합계는 100%여야 하며 자료 누락 시 종합점수를 보류합니다.</p>{criteria.map((c,index)=><div className="v2-score-row" key={c.id}><Select label={`평가 ${index+1} 지표`} value={c.indicatorId} options={[{value:'',label:'선택 필요'},...items.map(i=>({value:i.id,label:i.label}))]} onChange={v=>amend(c.id,'indicatorId',v)} disabled={disabled}/><Select label={`평가 ${index+1} 방향`} value={c.direction} options={[{value:'',label:'방향 선택'},{value:'increase',label:'클수록 유리'},{value:'decrease',label:'작을수록 유리'}]} onChange={v=>amend(c.id,'direction',v)} disabled={disabled}/><Field label={`평가 ${index+1} 하한`} value={c.min} onChange={v=>amend(c.id,'min',v)} disabled={disabled}/><Field label={`평가 ${index+1} 상한`} value={c.max} onChange={v=>amend(c.id,'max',v)} disabled={disabled}/><Field label={`평가 ${index+1} 가중치`} unit="%" value={c.weight} onChange={v=>amend(c.id,'weight',v)} disabled={disabled}/><button disabled={disabled} onClick={()=>onCriteria(criteria.filter(x=>x.id!==c.id))}>삭제</button></div>)}<p className="v2-score-total">종합점수 <strong>{Number.isFinite(evaluation.score)?number(evaluation.score,1)+' / 100':'산출 보류'}</strong><span>{evaluation.reason||'사용자 설정에 따른 점수 · 수지 가격에 자동 반영하지 않음'}</span></p>{evaluation.rows.length>0&&<div className="live-table-scroll"><table><thead><tr><th>평가 지표</th><th>관측값</th><th>점수</th><th>가중치</th><th>상태</th></tr></thead><tbody>{evaluation.rows.map(row=><tr key={row.id}><td>{row.label}</td><td>{number(row.value,2)} {row.unit}</td><td>{number(row.score,1)}</td><td>{number(row.weight,1)}%</td><td>{row.error||'사용자 기준 적용'}</td></tr>)}</tbody></table></div>}</div><details className="live-details"><summary>도로·교통·철거 등 추가 확인</summary><div className="v2-detail-grid">{[['roadWidth','진입도로 폭·접도'],['traffic','교통량·접근성'],['demolition','지장물·철거']].map(([k,t])=><Item key={k} title={t} item={survey?.unavailable?.[k]}/>)}</div></details></section>;
}
export function GeocodingStatus({comparables={},source,filters={},printing}){
 const s=comparables.geocodingStats,rows=comparables.geocodingOutcomes||[];
 const [page,setPage]=useState(0);useEffect(()=>setPage(0),[rows]);
 if(printing)return <p className="live-note">{REALTIME_NOTICE}</p>;
 const D=s?.D,total=s?['V','C','U','E','P'].reduce((n,k)=>n+(Number.isFinite(s[k])?s[k]:0),0):null;
 const rate=v=>Number.isFinite(D)&&D>0&&Number.isFinite(v)?number(v/D*100,1)+'%':'해당 없음';
 return <div className="live-panel v2-geocoder v2-runtime-revenue"><h3>공급주소 위치 확인 · 공고 단위</h3>{!s?<p className="live-note">현재 조건의 V2 위치 확인 집계가 없습니다. Python 연결 후 위치 재조회가 필요합니다. 기존 반경 수집 건수는 아래 별도 기록으로 유지합니다.</p>:<><p className="live-note">분모 D = 이번 실행의 고유 처리 대상 공고. 주택형 수·호출 횟수와 구분합니다. 원문 직접 요청과 지번 후보 재시도를 분리합니다.</p><div className="live-radius-counts">{[['D','처리 대상'],['V','일치 확인'],['C','좌표 후보·검토'],['U','위치 미확정'],['E','호출 실패'],['P','대기·미처리']].map(([k,t])=><span key={k}>{t} <b>{number(s[k],0)}</b>{k!=='D'&&<small>{rate(s[k])}</small>}</span>)}</div><p className={`live-note ${D!==total?'warning':''}`}>D {val(D)} = V+C+U+E+P {val(total)} · {D===total?'대사 일치':'대사 불일치 · 집계 검토 필요'}</p><div className="live-radius-counts"><span>좌표 반환 {rate((s.V||0)+(s.C||0))}</span><span>원문 일치 확인 {rate(s.V)}</span><span>처리율 {rate(Number.isFinite(D)?D-(s.P||0):null)}</span><span>원문 직접 확인 {number(s.originalVerifiedCount,0)}</span><span>후보 재시도 확인 {number(s.candidateVerifiedCount,0)}</span><span>호출 오류 이력 {number(s.errorEventCount,0)}</span><span>반경 내 {number(s.withinRadiusCount,0)}</span><span>가격 적합 공고 {number(s.eligibleNoticeCount,0)}</span></div><p className="live-note">청약홈 수집: {source?.collectionStatus||'미확인'} · 위치 처리: {source?.geocodingCollectionStatus||comparables.geocodingCollectionStatus||'개별 상태 확인'}</p><p className="live-note">처리율은 성공률이 아닙니다. C는 좌표가 있어도 비교 포함을 보류합니다. 반경 내 공고 수·적합 공고 수와 단지 수는 구분합니다.</p></>}{rows.length>0&&<details className="live-details"><summary>공고별 원문·후보·최종 상태 {rows.length}건</summary><div className="live-table-scroll"><table><thead><tr><th>공고</th><th>청약홈 원공급주소</th><th>처리 경로·후보</th><th>최종 상태</th><th>실패·검토 이유</th></tr></thead><tbody>{rows.slice(page*20,(page+1)*20).map((r,i)=><tr key={r.id||`${r.houseManageNo}-${r.announcementNo}-${i}`}><td>{r.name||r.houseName||r.houseManageNo||r.HOUSE_MANAGE_NO||'공고'}<small>{r.announcementNo||r.PBLANC_NO}</small></td><td>{r.inputAddress||r.originalAddress||r.address||r.HSSPLY_ADRES||'주소 없음'}</td><td>{r.geocodingMethod==='original'?'원문 직접':r.geocodingMethod==='parcel_candidate'?'지번 후보 재시도':'미확정'}<small>{r.candidateAddress||r.parcelCandidate||r.matchedParcelAddress||r.attempts?.find(a=>a.method==='parcel_candidate')?.address||'후보 없음·미제공'}</small>{r.attempts?.length>0&&<details><summary>요청 이력 {r.attempts.length}회</summary>{r.attempts.map((a,j)=><small key={j}>{a.method==='original'?'원문':'후보'} · {a.address} · {a.status}{a.errorCode?' / '+a.errorCode:''}</small>)}<small>응답 정제주소: {r.refinedAddress||'미제공'}</small></details>}</td><td>{r.geocodingState||'P'}<small>좌표 {r.coordinateReturned?'반환':'없음'} / 일치 {r.coordinateVerified?'확인':'미확인'}</small></td><td>{(r.geocodingErrors||r.errorCodes||[]).map(e=>typeof e==='string'?e:e.code||e.errorCode||'호출 오류').join(' · ')||r.reason||r.coordinateStatus||'오류 기록 없음'}</td></tr>)}</tbody></table></div><div className="live-table-pager"><span>현재 페이지의 20건까지 표시 · 실시간 메모리</span><div><button disabled={!page} onClick={()=>setPage(p=>p-1)}>이전</button><span>{page+1} / {Math.max(1,Math.ceil(rows.length/20))}</span><button disabled={(page+1)*20>=rows.length} onClick={()=>setPage(p=>p+1)}>다음</button></div></div></details>}<p className="live-note warning">{REALTIME_NOTICE}</p></div>;
}
