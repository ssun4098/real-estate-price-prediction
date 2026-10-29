import React,{useEffect,useRef,useState} from 'react';
import {Dialog} from '../../data-app-public.jsx';
import {DataComponent} from './data-component.jsx';
import {number,eok,VerticalBox} from './pf-live-widgets.jsx';
import {financeRowSetting,revisionStats,currentBudget} from './revision-model.mjs';
import {parcelProfile} from './land-comparison.mjs';
import {buildingSummary,designationSummary} from './survey-summary.mjs';
import SurveyFloorChart from './SurveyFloorChart.jsx';
import BoundaryAllocation from './BoundaryAllocation.jsx';
import {FacilityBands} from './FacilityBands.jsx';
import RegulationComposition from './RegulationComposition.jsx';
import SavedSamplesBar from './SavedSamplesBar.jsx';
import {landAmountStatus} from './land-completeness.mjs';
import './v3-workbench.css';

const tabs=[['parcels','필지'],['regulation','규제'],['location','입지'],['development','개발규모']];
const detailNames={boundaries:'용도지역 경계·면적·토지비 적용 근거',tools:'설정·저장·내보내기',conditions:'사업·지역·비교기간',parcels:'주소·선택 필지',survey:'필지·건축물 상세',regulation:'규제·공개 속성 상세',location:'입지·수요·평가 상세',development:'개발규모·공급계획',compare:'비교사례·대표값·조회 근거',costs:'독립 예상비용',cashflow:'현금흐름·기관별 결과·OKR',evidence:'자료 출처·계산 근거'};
const finite=Number.isFinite;
const numeric=v=>v==null||typeof v==='boolean'||typeof v==='string'&&!v.trim()?null:finite(Number(v))?Number(v):null;
const rowsOf=(p,key)=>{const v=p?.attributes?.[key]??p?.[key],rows=Array.isArray(v)?v:Array.isArray(v?.rows)?v.rows:[];return rows.filter(r=>r&&typeof r==='object'&&!Array.isArray(r));};
const first=(p,keys)=>{for(const k of keys){if(p?.[k]!=null&&p[k]!=='')return p[k];}return null;};
const uniqueParcels=rows=>[...new Map((Array.isArray(rows)?rows:[]).filter(p=>p&&typeof p==='object'&&!Array.isArray(p)).map((p,i)=>[p.pnu||'missing-'+i,p])).values()];
function parcelFact(p,keys){return first(p,keys)??[...rowsOf(p,'landRegister'),...rowsOf(p,'characteristics')].map(r=>first(r,keys)).find(v=>v!=null);}
function grouped(values){const c=new Map();values.forEach(v=>c.set(v||'미확인',(c.get(v||'미확인')||0)+1));return [...c].map(([label,value])=>({label,value}));}
function VerticalBars({id,title,rows,unit,sourceRows,note,sync,onScroll,onEvidence,emptyMessage}){
 const maximum=Math.max(1,...rows.map(r=>finite(r.value)&&r.value>=0?r.value:0));
 const rough=maximum/3,power=10**Math.floor(Math.log10(rough)),step=[1,2,2.5,5,10].find(v=>v*power>=rough)*power;
 const ceiling=Math.ceil(maximum/step)*step,ticks=unit==='필지'?[...new Set([0,Math.ceil(ceiling/2),Math.ceil(ceiling)])]:[0,ceiling/2,ceiling];
 return <DataComponent id={'pf-v3-'+id} queryId="liveSurvey" kind="custom" title={title} sourceRows={sourceRows} displayRows={rows} description={note} className="v3-chart-card">
  <div className="v3-chart-unit">{unit} · 세로 막대</div>
  {rows.length?<div className="v3-vertical-chart" data-reviewed-rows>
   <div className="v3-axis" aria-hidden="true">{ticks.map(v=><span key={v} style={{bottom:`${v/ceiling*100}%`}}>{number(v,unit==='필지'?0:1)}</span>)}</div>
   <div className="v3-columns-scroll" tabIndex={0} role="region" aria-label={`${title}, 항목이 많으면 좌우로 이동`} data-sync={sync} onScroll={onScroll}>
    <div className="v3-columns" style={{gridTemplateColumns:`repeat(${rows.length},minmax(74px,1fr))`,minWidth:rows.length*80}}>
     {rows.map((r,i)=><div className="v3-column" key={r.label+'-'+i} role="img" aria-label={`${r.label}: ${finite(r.value)?number(r.value,2)+' '+unit:'미확인'}`}>
      <div className="v3-column-well">{finite(r.value)&&r.value>=0?<div className={'v3-column-bar'+(r.label==='미확인'?' is-unknown':'')} style={{height:`${r.value/ceiling*100}%`}}><span>{number(r.value,unit==='필지'||unit==='층'?0:1)}</span></div>:<span className="v3-missing-mark">미확인</span>}</div>
      <div className="v3-column-label" title={r.label}>{r.label}</div>
     </div>)}
    </div>
   </div>
  </div>:<div className="v3-chart-empty">{emptyMessage||'확인된 자료가 없습니다.'}</div>}
  <small className="v3-chart-note">{note}{onEvidence&&<> <button className="v4-chart-detail-button" onClick={onEvidence}>지정 원문 보기</button></>}</small>
 </DataComponent>;
}
function DevelopmentUnits({input,result,disabled,onInput,onDetail}){
 const d=result?.results?.development||{},linked=input.linkedScenario?.enabled===true,manual=linked&&input.linkedScenario?.areaMode==='manual';
 const points=d.areaPoints||(result?.results?.revenue?.eligibleComplexes||[]).filter(p=>finite(p.medianSupplyAreaM2)&&p.medianSupplyAreaM2>0).map(p=>({id:p.id,label:p.label,valueM2:p.medianSupplyAreaM2,caseIds:p.caseIds}));
 const stats=d.areaStats||revisionStats(points.map(p=>p.valueM2));
 const applyMedian=()=>onInput(s=>({...s,linkedScenario:{...s.linkedScenario,enabled:true,areaMode:'median'}}));
 return <DataComponent id="pf-v3-development-units" queryId="liveRevenue" kind="custom" title="계획 분양 호수" sourceRows={[]} displayRows={[]} description="적합 분양사례의 단지별 대표 공급면적을 동일가중으로 집계합니다. 총 계획 공급면적을 호당 면적 중앙값으로 나누어 정수 호수만 배정합니다." className="v3-chart-card v5-development-units v2-runtime-revenue">
  <div className="v5-unit-layout" data-reviewed-rows><div className="v5-unit-distribution"><strong>분양사례 호당 공급면적</strong>{points.length?<VerticalBox compact title="단지별 대표 공급면적" points={points} stats={stats} valueKey="valueM2" unit="㎡/호" divisor={1} onInspect={()=>onDetail('compare')}/>:<div className="v3-chart-empty">분양자료를 조회하면 면적 분포가 표시됩니다.</div>}<small>단지별 주택형 면적 중앙값 · 단지 동일가중</small></div>
   <div className="v5-unit-calculation"><small>{!linked?'사용자 주택형 계획':manual?'호당 면적 직접 입력 · 사용자 가정':'분양사례 중앙값 적용'}</small><div className="v5-unit-formula">{linked?<>계획 분양호수 = 총 계획 공급 ÷ {manual?'입력 호당 면적':'호당 면적 중앙값'}</>:'계획 분양호수 = 입력 주택형별 호수 합계'}</div>
    {linked&&<div className="v5-unit-operands"><span><small>총 계획 공급</small><b>{number(d.capacitySupplyAreaM2,2)} ㎡</b></span><span aria-hidden="true">÷</span><span><small>{manual?'입력 호당 면적':'호당 면적 중앙값'}</small><b>{number(d.unitSupplyAreaM2,2)} ㎡/호</b></span></div>}
    <div className="v5-unit-result">{number(d.units,0)} <small>호</small></div><small>{linked?'소수 호수 버림 · 잔여면적 '+number(d.unassignedSupplyAreaM2,2)+'㎡':'입력 주택형별 공급계획 적용'} · 인허가 가능 호수 확정 아님</small>
    <div className="v5-unit-actions">{(!linked||manual)&&<button disabled={disabled} onClick={applyMedian}>중앙값 적용</button>}<button onClick={()=>onDetail('compare')}>분양사례·조회 확인</button><button onClick={()=>onDetail('development')}>계산 가정</button></div>
   </div>
  </div>
 </DataComponent>;
}
function DevelopmentFar({input,result,disabled,onInput}){
 const linked=input.linkedScenario||{},far=linked.enabled?linked.farPct:input.assumptions?.farPct,max=finite(linked.farMaxPct)&&linked.farMaxPct>0?linked.farMaxPct:500;
 const change=value=>onInput(s=>({...s,linkedScenario:{...s.linkedScenario,enabled:true,areaMode:s.linkedScenario?.areaMode||'median',farPct:value}}));
 return <DataComponent id="pf-v5-development-far" queryId="liveParcels" kind="custom" title="용적률" className="v3-chart-card v5-development-far" sourceRows={uniqueParcels(input.parcels)} displayRows={[]} description="대지면적 × 입력 용적률 ÷ 100으로 총 계획 공급면적을 계산하고, 적용 호당 면적으로 나누어 계획 분양호수를 계산합니다. 용적률은 사용자 가정입니다."><div className="v5-development-far-body"><PercentControl id="v5-development-far-input" label="적용 용적률" sliderLabel="개발규모 용적률 조절" value={far} max={max} disabled={disabled} onChange={change} live/><div className="v5-far-formula">총 계획 공급 = 대지면적 × 용적률 ÷ 100</div><small>계획 면적·분양호수·수지분석에 함께 적용</small></div><small className="v3-chart-note">사용자 가정 · 분석 상한 {number(max,0)}%는 법정 허용치가 아닙니다.</small></DataComponent>;
}
function SurveyCharts({tab,input,result,survey,state,onBoundaryDetail,disabled,onInput,onDetail}){
 const root=useRef(),syncing=useRef(false),[designationDetail,setDesignationDetail]=useState(null),parcels=uniqueParcels(input.parcels),buildingData=buildingSummary(parcels),buildings=buildingData.buildings,d=result?.results?.development||{};
 const scroll=e=>{if(syncing.current||!e.currentTarget.dataset.sync)return;syncing.current=true;for(const node of root.current.querySelectorAll('[data-sync="buildings"]'))if(node!==e.currentTarget)node.scrollLeft=e.currentTarget.scrollLeft;requestAnimationFrame(()=>{syncing.current=false});};
 const chart=(id,title,rows,unit,note,sync)=> <VerticalBars key={id} {...{id,title,rows,unit,note,sync}} sourceRows={parcels} onScroll={scroll}/>;
 const designationChart=(id,title,kind)=>{const summary=designationSummary(parcels,kind),onEvidence=()=>setDesignationDetail({title,...summary});return <VerticalBars key={id} id={id} title={title} rows={summary.rows} unit="필지" note={summary.note} sourceRows={summary.evidence} onEvidence={onEvidence}/>;};
 let charts;
 if(tab==='parcels')charts=[designationChart('parcel-zone','용도지역','zone'),chart('parcel-category','지목',grouped(parcels.map(p=>{const profile=parcelProfile(p);return !['error','failed','partial','조회 실패','unavailable'].includes(profile.sourceBasis.registerStatus)&&profile.jimokRaw.length===1?profile.jimokRaw[0]:'미확인';})),'필지','현재 토지임야대장 기준 · 연도별 참고 속성과 구분'),<SurveyFloorChart key="building-floors" summary={buildingData}/>,chart('building-area','건축물 연면적',buildings.map(b=>({label:b.label,value:b.area})),'㎡','고유 건물별 연면적 · 식별자 중복 제거 · 층수와 별도 단위')];
 else if(tab==='regulation')charts=[<RegulationComposition key="regulation" parcels={parcels} onEvidence={setDesignationDetail}/>];
 else if(tab==='location')charts=[chart('road','도로 접면',grouped(parcels.map(p=>parcelFact(p,['roadSideCodeNm','roadSide','road']))),'필지','공개 속성 · 법적 진입권은 별도 확인'),<FacilityBands key="facilities" {...{survey,state}}/>];
 else charts=[<DevelopmentFar key="far" {...{input,result,disabled,onInput}}/>,chart('development-area','계획 면적',[{label:'확인 대지면적',value:d.knownLandAreaM2},{label:'총 계획 공급',value:d.capacitySupplyAreaM2??d.supplyAreaM2}],'㎡','면적의 서로 다른 개념 · 합산하지 않음'),<DevelopmentUnits key="units" {...{input,result,disabled,onInput,onDetail}}/>];
 return <><div ref={root} className={'v3-survey-charts v3-survey-'+tab} aria-busy={state?.loading||undefined}>{charts}</div><Dialog open={!!designationDetail} onClose={()=>setDesignationDetail(null)} title={(designationDetail?.title||'지정')+' 원문과 집계 근거'} expanded><div className="v4-survey-detail"><p>{designationDetail?.note}</p><p>한 필지가 여러 용도지역 등에 걸치면 각 지정에 1필지씩 표시합니다. 지정별 면적이나 토지가치 비중을 뜻하지 않습니다. 실제 토지비는 API 경계가 확인된 용도지역별 배분면적을 기준으로 계산하며, 경계가 누락되거나 충돌하면 보류합니다. <button onClick={()=>{setDesignationDetail(null);onBoundaryDetail?.()}}>자동 면적·단가 보기</button></p><table data-reviewed-rows><thead><tr><th>선택 필지</th><th>지정명</th><th>코드</th><th>관계</th><th>집계 판정</th><th>갱신일</th></tr></thead><tbody>{designationDetail?.evidence.map((row,i)=><tr key={i}><td>{row.parcelNumber}번<small>{row.pnu}</small></td><td>{row.designation}</td><td>{row.code}</td><td>{row.relation}</td><td>{row.decision}</td><td>{row.updatedAt}</td></tr>)}</tbody></table></div></Dialog></>;
}
const costRows=[['land','예상 토지매입대금'],['construction','허용 공사비'],['indirect','허용 간접 공사비'],['sales','허용 분양제비용'],['trust','허용 신탁보수'],['tax','허용 제세공과금'],['finance','허용 금융비용']];
export {V5LandPlot as V3LandPlot} from './LandDistribution.jsx';

function FinanceRow({id,label,input,budget,result,onChange,disabled,onDetail}){
 const setting=financeRowSetting(input,id),amount=setting.mode==='amount',perPyeong=setting.mode==='areaUnit';
 const applied=id==='revenue'?budget.revenueWon:id==='land'?budget.landWon:id==='trust'?budget.trustWon:budget.allocationRows?.find(r=>r.id===id)?.amountWon;
 // 간접·분양·제세·금융의 기본값은 허용 공사비 대비(7·6·5·6.5%)로 금액만 정하고, '기준'에는 총지출 대비 '지출%'로 환산해 보여 준다 (2026-10-29 요청: 공사비%는 보고용 기준으로 부적절).
 const fromConstruction=setting.mode==='constructionPct',shownMode=fromConstruction?'budgetPct':setting.mode;
 const value=fromConstruction?(finite(applied)&&finite(budget.totalExpenseWon)&&budget.totalExpenseWon>0?Math.round(applied/budget.totalExpenseWon*1e4)/100:''):finite(setting.value)?setting.value/(amount?1e8:1):setting.value??'';
 const comparable=id==='revenue'||id==='land',max=amount?Math.max(1000,finite(value)?Math.ceil(value/100)*100:0):perPyeong?Math.max(3000,finite(value)?Math.ceil(value/1000)*1000:0):setting.mode==='comparablePct'?200:100;
 const landModel=id==='land'&&result?.results?.land?.amountBasis==='model';
 // 지출 입력 방식 (2026-10-29): 평당 = 만원/3.3㎡ × 계획 공급면적(공사비만), 지출% = 예상 총지출 대비, 수입% = 예상 총수입 대비
 const choices=comparable?[['comparablePct',landModel?'모델%':'사례%'],['amount','금액']]:id==='construction'?[['areaUnit','평당'],['budgetPct','지출%'],['revenuePct','수입%'],['amount','금액']]:id==='trust'?[['revenuePct','수입%'],['budgetPct','지출%'],['amount','금액']]:[['budgetPct','지출%'],['revenuePct','수입%'],['amount','금액']];
 const update=raw=>{const n=raw.trim()===''?null:Number(raw);onChange(id,{...setting,mode:shownMode,value:raw.trim()===''?null:finite(n)?n*(amount?1e8:1):raw});};
 const modeChange=mode=>{const baseline=result?.results?.[id]?.comparableWon;const base=mode==='comparablePct'?baseline:mode==='budgetPct'?budget.allowableWon:mode==='revenuePct'?budget.revenueWon:mode==='areaUnit'&&finite(budget.supplyAreaM2)?budget.supplyAreaM2/3.3*1e4:null;onChange(id,{mode,value:mode==='amount'?(finite(applied)?applied:null):finite(base)&&base>0&&finite(applied)?applied/base*(mode==='areaUnit'?1:100):mode==='comparablePct'?100:mode==='areaUnit'?1000:null});};
 const valid=fromConstruction||setting.value==null||finite(setting.value)&&setting.value>=0&&(amount||setting.value<=max);
 const landStatus=id==='land'?landAmountStatus(result?.results?.land||{}):null,held=landStatus&&!finite(applied);
 return <div className={'v3-finance-row v3-finance-row-'+id} data-reviewed-rows>
  <label htmlFor={'v3-finance-'+id}>{label}</label>
  <select aria-label={label+' 입력 기준'} value={shownMode} disabled={disabled} onChange={e=>modeChange(e.target.value)}>{choices.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select>
  <div className="v3-row-input"><input id={'v3-finance-'+id} aria-label={label+(amount?' 금액, 억원':perPyeong?' 평당 단가, 만원':' 비율, 퍼센트')} title={perPyeong?'평당 단가(만원) × 계획 공급면적 ÷ 3.3':fromConstruction?`기본값: 허용 공사비의 ${number(setting.value,1)}% → 예상 총지출 대비 비율로 표시`:undefined} aria-invalid={!valid} inputMode="decimal" value={value} disabled={disabled} onChange={e=>update(e.target.value)}/><input aria-label={label+' 조절'} type="range" min="0" max={max} step={perPyeong?'10':'.1'} value={finite(value)?Math.min(max,Math.max(0,value)):0} disabled={disabled} onChange={e=>update(e.target.value)}/></div>
  <output>{finite(applied)?number(applied/1e8,2):held?<button type="button" className="v5-held-amount" onClick={()=>onDetail('boundaries')}>산정 보류</button>:'—'}</output>
  {held&&<div className="v5-land-row-status"><span>{finite(landStatus.confirmedSubtotalWon)?`확인분 소계 ${number(landStatus.confirmedSubtotalWon/1e8,2)}억원 · `:''}{landStatus.summary} · 전체 토지비 미적용</span><button onClick={()=>onDetail('boundaries')} title={landStatus.reasons.join(' · ')}>보류 원인·근거</button></div>}
  {landStatus?.fallbackUsed&&<div className="v5-land-row-status v6-land-fallback-status"><span>동일 그룹 비교사례 없음 · {landStatus.fallbackSummary}</span><button onClick={()=>onDetail('boundaries')}>대체 근거</button></div>}
  {landStatus?.modelUsed&&<div className="v5-land-row-status"><span>{landStatus.modelSummary} · {landStatus.appliedPct===100?"왼쪽 '예상 토지매입대금' 칸과 같은 금액":`왼쪽 '예상 토지매입대금' 칸 모델 예측의 ${number(landStatus.appliedPct,1)}%`}</span></div>}
 </div>;
}
function PercentControl({id,label,sliderLabel,value,max,disabled,onChange,live=false}){
 const [draft,setDraft]=useState(value==null?'':String(value));
 useEffect(()=>setDraft(value==null?'':String(value)),[value]);
 const parsed=draft.trim()===''?null:Number(draft),valid=finite(parsed)&&parsed>=0&&parsed<=max;
 const commit=()=>{if(!Object.is(parsed,value))onChange(parsed)};
 return <div className="v5-percent-control"><label htmlFor={id}>{label}</label><span className="v5-percent-input"><input id={id} aria-label={label+' 직접 입력, 퍼센트'} type="number" inputMode="decimal" min="0" max={max} step=".1" value={draft} title={live?'입력하면 계획 면적과 분양호수에 바로 적용됩니다.':'숫자를 입력한 뒤 Enter 또는 다른 곳을 누르면 적용됩니다.'} disabled={disabled} aria-invalid={!valid} aria-describedby={!valid?id+'-error':undefined} onChange={e=>{const text=e.target.value;setDraft(text);if(live)onChange(text.trim()===''?null:Number(text))}} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();commit()}else if(e.key==='Escape'){setDraft(value==null?'':String(value))}}}/><span aria-hidden="true">%</span></span><input aria-label={sliderLabel} type="range" min="0" max={max} step=".1" value={finite(value)&&value>=0&&value<=max?value:0} disabled={disabled} onChange={e=>{setDraft(e.target.value);onChange(Number(e.target.value))}}/>{!valid&&<small id={id+'-error'} className="v5-percent-error">0~{number(max,1)}%로 입력하세요.</small>}</div>;
}
function FinancePanel({input,result,plots,disabled,onInput,onAssume,onDetail}){
 const budget=currentBudget(input,result?.results),linked=input.linkedScenario||{},far=linked.enabled?linked.farPct:input.assumptions?.farPct,farMax=finite(linked.farMaxPct)&&linked.farMaxPct>0?linked.farMaxPct:500;
 const rowChange=(id,setting)=>onInput(s=>({...s,financeEditor:{...s.financeEditor,...(['revenue','land'].includes(id)?{[id]:setting}:{expenses:{...s.financeEditor?.expenses,[id]:setting}})}}));
 const setFar=value=>linked.enabled?onInput(s=>({...s,linkedScenario:{...s.linkedScenario,farPct:value}})):onAssume('farPct',value);
 return <div className="v3-finance-panel">
  <div className="v3-finance-sliders"><PercentControl id="v5-far-input" label="용적률" sliderLabel="용적률 조절" value={far} max={farMax} disabled={disabled} onChange={setFar}/><div className="v5-margin-applied" role="status">{finite(budget.targetMarginPct)?<>목표 수익률 <strong>{number(budget.targetMarginPct,2)}%</strong> · (예상 총수입 − 예상 총지출) ÷ 예상 총수입 · 자동 산정</>:budget.targetAdjustmentStatus==='infeasible'?'목표 수익률 보류 · 지출% 합계와 고정 비용 조합을 확인하세요.':budget.targetAdjustmentStatus==='missing-supply'?'목표 수익률 보류 · 공급계획(계획 공급면적)을 확인하세요.':budget.targetAdjustmentStatus==='zero-revenue'?'수입 0원 · 수익률 산정 불가':'목표 수익률 보류 · 총수입·토지비·지출 확인 후 자동 산정'}</div></div>
  <div className="v3-kpis" data-reviewed-rows>{[[financeRowSetting(input,'revenue').mode==='amount'?'예상 총수입 · 사용자 가정':'예상 총수입 · 사례 적용',eok(budget.revenueWon)],['예상 총지출 · 토지비 포함',eok(budget.totalExpenseWon)],['목표 수익률 · 자동 산정',finite(budget.profitMarginPct)?number(budget.profitMarginPct,1)+'%':'—']].map(([l,v])=><div key={l}><small>{l}</small><strong>{v}</strong></div>)}</div>
  <div className="v3-finance-content"><div className="v3-finance-heading"><h2>수지분석</h2><small>금액: 억원 · 평당: 만원(계획 공급면적÷3.3) · 지출%: 총지출 대비 · 수입%: 총수입 대비</small></div>
   <div className="v3-finance-body"><div className="v3-finance-plots">{plots}</div><div className="v3-budget-editor">
    <div className="v3-finance-row v3-row-head"><span>수입 항목</span><span>기준</span><span>금액 / 비율 조절</span><span>적용·억원</span></div>
    <FinanceRow id="revenue" label="예상 총수입" {...{input,budget,result,disabled,onDetail}} onChange={rowChange}/>
    
    <div className="v3-finance-row v3-row-head"><span>지출 항목</span><span>기준</span><span>금액 / 비율 조절</span><span>적용·억원</span></div>
    <div className="v3-expense-rows">{costRows.map(([id,label])=><FinanceRow key={id} {...{id,label,input,budget,result,disabled,onDetail}} onChange={rowChange}/>)}</div>
    <label className="v3-trust-type">신탁상품<select aria-label="신탁상품" disabled={disabled} value={input.budgetAllocation?.trustType||''} onChange={e=>{const type=e.target.value;onInput(s=>({...s,budgetAllocation:{...s.budgetAllocation,trustType:type}}));}}><option value="">상품 미선택 · 보수 가정</option><option value="management">관리형</option><option value="completion">책임준공관리형</option><option value="distribution">분양관리 · 적용 검토</option></select><button disabled={disabled} onClick={()=>rowChange('land',{mode:'comparablePct',value:100})}>토지 사례 100%</button></label>
    <p className="v3-finance-status" role="status">{budget.complete?`${budget.status||'계산 완료'} · 예상 총지출 ${eok(budget.allocatedWon)}`:budget.adjustmentError||'총수입·토지비·공급계획·지출 입력을 확인하세요. 미확보는 0원이 아닙니다.'}{!input.budgetAllocation?.trustType&&' · 신탁보수는 사용자 가정이며 기본값은 총수입의 1%입니다.'}</p>
   </div></div>
  </div>
  <div className="v3-finance-actions"><button onClick={()=>onDetail('compare')}>비교사례·상세 테이블</button><button onClick={()=>onDetail('boundaries')}>토지 면적·단가</button><button onClick={()=>onDetail('development')}>개발규모 설정</button><button onClick={()=>onDetail('costs')}>독립 비용</button><button onClick={()=>onDetail('cashflow')}>현금흐름·기관별 결과</button></div>
 </div>;
}
export default function V3Workbench(props){
 const {input,result,survey,surveyState,boundaryState={},onBoundaryRetry,onSurveyRetry,printing,map,plots,details,disabled,local,online,onInput,onAssume,onPrint,printBlocked,busy,calcing,error,onClearError,validation,address,onAddress,candidates,addressDisabled,onSearch,onCandidate,onClearParcels,draft,sampleLibrary,viewState,onViewState}=props;
 const [fallbackView,setFallbackView]=useState({main:'survey',tab:'parcels'}),[detail,setDetail]=useState(null),[pendingFocus,setPendingFocus]=useState(null);
 const activeView=viewState||fallbackView,main=activeView.main==='finance'?'finance':'survey',tab=tabs.some(([id])=>id===activeView.tab)?activeView.tab:'parcels';
 const changeView=patch=>{const next={main,tab,...patch};setFallbackView(next);onViewState?.(next);},setMain=value=>changeView({main:value}),setTab=value=>changeView({tab:value});
 const detailRef=useRef();
 useEffect(()=>{const navigate=e=>{const id=e.detail?.id||'',key=id.toLowerCase();if(key.includes('financeeditor')||key.includes('targetmargin')||key.includes('budgetallocation')){setDetail(null);setMain('finance');setTimeout(()=>{const field=key.includes('targetmargin')?document.getElementById('v5-margin-input'):key.includes('trusttype')?document.querySelector('[aria-label="신탁상품"]'):document.getElementById('v3-finance-'+['revenue','land','construction','indirect','sales','trust','tax','finance'].find(name=>key.includes(name)));field?.focus();},80);return;}const target=key.includes('boundary')?'boundaries':key.includes('development')||key.includes('linkedscenario')?'development':key.includes('compare')?'compare':key.includes('cost')||key.includes('budget')||e.detail?.section==='budget'?'costs':key.includes('cashflow')?'cashflow':key.includes('parcel')?'parcels':key.includes('survey')?'survey':'conditions';setDetail(target);setPendingFocus(id);};globalThis.addEventListener('pf-v3-navigate',navigate);return()=>globalThis.removeEventListener('pf-v3-navigate',navigate);},[main,tab,onViewState]);
 useEffect(()=>{if(!pendingFocus||!detail)return;const timer=setTimeout(()=>{const node=detailRef.current?.querySelector('[id="'+pendingFocus.replaceAll('"','')+'"]')||detailRef.current;node?.scrollIntoView({block:'start'});(node?.matches('input,select,button')?node:node?.querySelector('input:not(:disabled),select:not(:disabled),button:not(:disabled)'))?.focus({preventScroll:true});setPendingFocus(null);},80);return()=>clearTimeout(timer);},[detail,pendingFocus]);
 useEffect(()=>{if(printing)setDetail(null)},[printing]);
 const d=result?.results?.development||{},parcels=uniqueParcels(input.parcels),knownArea=parcels.reduce((sum,p)=>sum+(finite(p.areaM2)?p.areaM2:0),0),missingArea=parcels.filter(p=>!finite(p.areaM2)).length;
 const buildingCounts=parcels.reduce((c,p)=>{const b=p.attributes?.buildings||{};if(rowsOf(p,'buildings').length)c.present++;else if(['success','empty','호출 확인','자료 없음'].includes(b.status))c.empty++;else c.unknown++;return c;},{present:0,empty:0,unknown:0});
 const openSurvey=()=>setDetail(tab==='parcels'?'survey':tab);
 return <>
  <div className="v3-workbench">
   <header className="v3-topbar"><div className="v6-brand"><h1>개발사업성 분석 <small>V6</small></h1></div><nav className="v3-main-tabs" aria-label="사업 검토 구분">{[['survey','사업 기본조사'],['finance','사업 수지분석']].map(([v,l])=><button key={v} aria-pressed={main===v} onClick={()=>setMain(v)}>{l}</button>)}</nav><div className="v3-toolbar"><span className="v6-maker">made by 최태영</span><span className="v3-mode">{local?'PYTHON · LIVE':online?'저장 결과':'OFFLINE'}</span><button onClick={()=>setDetail('conditions')}>사업·조회 조건</button><button onClick={onPrint} disabled={printBlocked||printing} title="무손실 PNG · 4배 해상도 · A4 가로 5페이지">PDF</button></div></header>
   <div className="v3-contextbar"><div className="v6-context-metrics" data-reviewed-rows><span>사업지 <strong>{input.project?.name||'미입력'}</strong></span><span>선택 <strong>{parcels.length}필지</strong></span><span>대지면적 <strong>{number(knownArea,2)}㎡{missingArea?` · ${missingArea}필지 미확보`:''}</strong></span><span>공급계획 <strong>{number(d.units,0)}호 · {number(d.assignedSupplyAreaM2??d.supplyAreaM2,2)}㎡</strong></span></div><SavedSamplesBar library={sampleLibrary} onSettings={()=>setDetail('tools')}/><button className="v6-evidence-button" onClick={()=>setDetail('evidence')}>근거 확인</button></div>
   {(error||busy||calcing||surveyState?.loading)&&<div className={'v3-status'+(error?' is-error':'')} role={error?'alert':'status'}><span>{error||busy&&busy+' 중'||surveyState?.loading&&'선택 필지 기본조사 조회 중'||'조건 반영 중'}</span>{error&&<button onClick={onClearError}>닫기</button>}</div>}
   <div className="v3-workspace"><section className="v3-map-panel" aria-label="개발 대상 필지"><div className="v3-map-search"><input aria-label="주소로 지도 이동" value={address} onChange={e=>onAddress(e.target.value)} disabled={addressDisabled} placeholder="도로명·지번 주소" onKeyDown={e=>{if(e.key==='Enter'&&address.trim())onSearch()}}/><button disabled={addressDisabled||!address.trim()} onClick={onSearch}>검색</button><button onClick={()=>setDetail('parcels')}>필지 상세</button><button className="v6-clear-parcels" type="button" aria-label="선택된 필지 전부 해제" title="선택된 필지 전부 해제" disabled={printing||!parcels.length||!onClearParcels} onClick={onClearParcels}>전체 해제</button></div>{candidates.length>0&&<div className="v3-address-candidates">{candidates.map((a,i)=><button key={i} disabled={addressDisabled} onClick={()=>onCandidate(a)}>{a.label||a.address}</button>)}</div>}{map}</section>
    <div className="v3-right-pane">{main==='survey'?<section className="v3-survey-panel"><nav className="v3-subtabs" aria-label="기본조사 상세">{tabs.map(([v,l])=><button key={v} aria-pressed={tab===v} onClick={()=>setTab(v)}>{l}</button>)}</nav><SurveyCharts {...{tab,input,result,survey,disabled,onInput}} onDetail={setDetail} state={surveyState} onBoundaryDetail={()=>setDetail('boundaries')}/><div className="v3-survey-actions"><small>{surveyState?.error||(!input.parcels?.length?'지도에서 개발 필지를 선택하세요.':surveyState?.waitingForSelection?'보관 자료 열람 중 · 선택 필지로 실시간 자료를 조회할 수 있습니다.':surveyState?.loading?'조회 중 · 미확보 항목은 0으로 처리하지 않습니다.':tab==='parcels'?`건축물 자료 있음 ${buildingCounts.present} · 조회 0건 ${buildingCounts.empty} · 미확보 ${buildingCounts.unknown}필지 · 조회 0건은 현장 확인 필요`:'공개자료·사용자 가정 기준 · 출처와 세부 상태는 상세표 확인')}</small><div className="v5-boundary-actions">{tab==='location'&&<button disabled={!local||!!busy||surveyState?.loading||!input.parcels?.length} onClick={onSurveyRetry}>{surveyState?.error?'주변시설 다시 조회':'주변시설 조회'}</button>}<button onClick={()=>setDetail('boundaries')}>토지 면적·단가</button><button className="primary" onClick={openSurvey}>상세 테이블 보기</button></div></div></section>:<FinancePanel {...{input,result,plots,disabled,onInput,onAssume}} onDetail={setDetail}/>}</div>
   </div>
   <div className="v3-bottom"><div className="v3-draft-slot">{draft}</div>{validation?.fieldErrors?.length>0&&<button className="v3-validation-button" onClick={()=>setDetail('tools')}>입력 확인 {validation.fieldErrors.length}건</button>}<small>기준일 {input.project?.asOf} · {calcing?'계산 대기':'공개자료와 사용자 가정'}</small></div>
  </div>
  <Dialog open={!!detail&&!printing} onClose={()=>setDetail(null)} title={detailNames[detail]||'상세'} expanded><div ref={detailRef} className="pf-live-page pf-v3-dialog">{detail==='boundaries'?<BoundaryAllocation parcels={parcels} land={result?.results?.land||{}} state={boundaryState} onRetry={local?onBoundaryRetry:undefined}/>:detail?details[detail]:null}</div></Dialog>
 </>;
}
