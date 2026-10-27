import React,{useState} from 'react';
import {DataComponent,ChartMark,ChartTooltip} from '../../data-app-public.jsx';
import {number,eok,VerticalBox} from './pf-live-widgets.jsx';
import {landAmountStatus} from './land-completeness.mjs';
import './land-distribution.css';
import {wonM2ToEokPyeong} from './price-formula.mjs';
import {ModelLandEstimate} from './ModelLandEstimate.jsx';

function UnitPriceBox({group,onInspect,referenceOnly=false}){
 const {points=[]}=group,stats=group.unitPriceStats||group.stats;
 const unknown=points.filter(p=>p.zoningStatus==='missing'||p.jimokStatus==='missing').length,known=points.length-unknown;
 if(!points.length||!stats?.n)return <div className="v3-box-empty">같은 비교그룹의 거래 없음<small>대체에 사용할 다른 그룹의 유효 거래도 없거나, 대상 경계·면적 확인이 필요합니다.</small></div>;
 const values=points.map(p=>p.unitPriceWonM2),min=Math.min(...values),max=Math.max(...values),pad=Math.max((max-min)*.12,max*.06,100),lo=Math.max(0,min-pad),hi=max+pad,y=v=>116-(v-lo)/(hi-lo)*96,format=v=>number(wonM2ToEokPyeong(v),5);
 return <div className="v5-land-reference" data-reviewed-rows>
  <div className="v5-land-reference-legend"><span><i className="known"/>분류 확인 {known}건</span><span><i className="missing"/>분류 미확인 포함 {unknown}건</span></div>
  <div className="v5-land-reference-frame" data-chart-interaction-root>
  <svg viewBox="0 0 270 141" role="img" aria-label={`${group.label} 평당 단가 분포. 분류 미확인 ${unknown}건 포함 총 ${stats.n}건. 중앙값 ${format(stats.median)}억원/평`}>
   <text x="5" y="11">억원/평</text>
   {[lo,(lo+hi)/2,hi].map((v,i)=><g key={i}><line x1="68" x2="258" y1={y(v)} y2={y(v)} className="grid"/><text x="62" y={y(v)+3} textAnchor="end">{number(wonM2ToEokPyeong(v),4)}</text></g>)}
   {stats.showBox&&<g><line x1="162" x2="162" y1={y(stats.whiskerHigh)} y2={y(stats.whiskerLow)} className="whisker"/><line x1="149" x2="175" y1={y(stats.whiskerHigh)} y2={y(stats.whiskerHigh)} className="whisker"/><line x1="149" x2="175" y1={y(stats.whiskerLow)} y2={y(stats.whiskerLow)} className="whisker"/><rect x="142" width="40" y={y(stats.q3)} height={Math.max(1,y(stats.q1)-y(stats.q3))} className="box"/><line x1="142" x2="182" y1={y(stats.median)} y2={y(stats.median)} className="median"/></g>}
   {points.map((point,i)=><circle key={point.id+'-'+i} cx={119+(i*17%79)} cy={y(point.unitPriceWonM2)} r={point.zoningStatus==='missing'||point.jimokStatus==='missing'?3.4:2.8} className={point.zoningStatus==='missing'||point.jimokStatus==='missing'?'case-dot missing-zone':'case-dot known-zone'} aria-hidden="true"/>)}
   <path d={`M218 ${y(stats.mean)-4} l4 4 -4 4 -4 -4 Z`} className="mean"/><text x="162" y="135" textAnchor="middle">{stats.n}건 · {stats.showBox?'사분위 분포':'5건 미만 · 사례점 표시'}</text>
  </svg>
  {points.map((point,i)=>{const zone=point.zoningStatus==='missing'?'용도지역 미확인':point.landUse,label=`${point.label} · ${zone} · ${format(point.unitPriceWonM2)}억원/평`;return <ChartMark key={point.id+'-'+i} className="v5-land-reference-mark" aria-label={label} style={{left:`${(119+(i*17%79))/270*100}%`,top:`${y(point.unitPriceWonM2)/141*100}%`}} tooltip={<ChartTooltip active label={point.label} headerValue={`${format(point.unitPriceWonM2)} 억원/평`} details={[{label:'용도지역',value:zone},{label:'지목',value:point.jimok||'지목 미확인'},{label:'분포 반영',value:referenceOnly?'단가 분포 포함 · 대상 면적 확인 전':'동일 비교그룹 토지비 산정 포함'}]}/>} context={{kind:'chart',chartType:'scatter',label,value:point.unitPriceWonM2,field:'unitPriceWonM2',row:point,actions:onInspect?[{label:'거래 원문·포함 근거 보기',onSelect:()=>onInspect(point)}]:[]}}/>})}
  </div>
  <small className="v3-box-caption">중앙 {format(stats.median)} · 평균 {format(stats.mean)} 억원/평</small>
 </div>;
}

function FallbackPrice({group,rows,onInspect}){
 const fallback=group.fallback,donors=(rows||[]).filter(row=>(fallback.sourceCaseIds||[]).includes(row.id));
 return <div className="v6-land-fallback" data-reviewed-rows>
  <strong>동일 그룹 비교사례 없음 · 중앙값 대체</strong>
  <small>다른 {fallback.sourceGroupCount}개 그룹의 유효 거래 {fallback.sourceCaseCount}건을 합친 단가 중앙값입니다.</small>
  <details><summary>대체 사례·계산 근거</summary><small>동일 그룹 사례 {group.unitPriceStats?.n??0}건 · 대체 단가 {number(fallback.unitPriceWonM2,2)}원/㎡ × 배분면적 {number(group.areaM2,2)}㎡ · 가격 보정 전 {eok(fallback.unitPriceWonM2*group.areaM2)}</small><small>{(fallback.sourceGroupIds||[]).map(id=>id.replace('|',' · ')).join(' / ')}</small>{donors.map(row=><button type="button" className="live-text-button" key={row.id} onClick={()=>onInspect?.(row)}>{row.date||'날짜 미확인'} · {row.dong||row.address||row.id} · {row.jimok||'지목 미확인'}</button>)}</details>
 </div>;
}

export function V5LandPlot({land,rows,onInspect,selection:controlledSelection,onSelectionChange}){
 const [localSelection,setLocalSelection]=useState('');
 const selection=controlledSelection===undefined?localSelection:controlledSelection;
 const setSelection=value=>{if(controlledSelection===undefined)setLocalSelection(value);onSelectionChange?.(value)};
 const groups=land.groups||[],references=land.referenceGroups||[],amountStatus=landAmountStatus(land),method=land.method||'median';
 const unitGroups=[...groups.map(group=>({...group,referenceOnly:false})),...references.filter(ref=>!groups.some(group=>group.id===ref.id)).map(group=>({...group,referenceOnly:true}))];
 const options=[...unitGroups.map(group=>({id:'unit:'+group.id,mode:'unit',group,label:'평당 단가 · '+(group.label||group.id)})),...groups.map(group=>({id:'amount:'+group.id,mode:'amount',group,label:'산정 금액 · '+(group.label||group.id)}))];
 const selected=options.find(o=>o.id===selection)||options[0],group=selected?.group,unitStats=group?.unitPriceStats||(group?.referenceOnly?group.stats:null),unit=group?.representativeUnitPriceWonM2??unitStats?.[method],fallback=group?.fallback?.used===true;
 const reasons=amountStatus.reasons;
 return <DataComponent className="v3-plot-source v5-land-plot" id="pf-live-land-box" queryId="liveLand" kind="custom" title="예상 토지매입대금" sourceRows={rows} displayRows={fallback?[{groupId:group.id,areaM2:group.areaM2,representativeUnitPriceWonM2:unit,representativeWon:group.representativeWon,fallback:group.fallback}]:group?.points||[]} description="용도지역 4개 × 지목 3개 비교그룹. 같은 그룹의 유효 거래 단가 중앙값 또는 평균에 배분 면적을 곱합니다. 같은 그룹이 0건이면 현재 조회·필터 조건을 통과한 다른 그룹의 거래 단가를 모두 모아 중앙값으로 대체합니다. 대체 그룹과 근거 거래를 표시하며 직접 비교사례 건수는 0건으로 유지합니다. 경계·면적 미확정 또는 모든 그룹의 유효 거래가 없으면 총액을 보류합니다.">
  <div className="live-box-value v5-land-unit-value" data-reviewed-rows>{Number.isFinite(unit)?`${number(wonM2ToEokPyeong(unit),5)} 억원/평`:'미산출'}<small>{fallback?'중앙값 대체 · 동일 그룹 0건':`사례 평당 단가 ${method==='mean'?'평균':'중앙값'} · ${unitStats?.n??0}건`}</small></div>
  {group?<><div className="v3-land-group-control">{options.length>1?<select aria-label="토지 분포 보기" value={selected.id} onChange={e=>setSelection(e.target.value)}>{options.map(o=><option key={o.id} value={o.id}>{o.label}</option>)}</select>:<small>{selected.label}</small>}</div>
   <small className="v3-land-total">{group.referenceOnly?'대상 면적 확인 전 · 단가만 표시':`선택군 예상액 ${eok(group.representativeWon)} · ${number(group.areaM2,2)}㎡`}</small>
   {fallback?<FallbackPrice group={group} rows={rows} onInspect={onInspect}/>:selected.mode==='unit'?<UnitPriceBox group={group} onInspect={onInspect} referenceOnly={group.referenceOnly}/>:<VerticalBox compact title={group.label||group.id} points={group.points} stats={group.stats} onInspect={onInspect}/>}
  </>:<div className="v3-box-empty">토지 비교군 확인 필요<small>대상 필지 분류와 같은 그룹의 유효 거래가 필요합니다.</small></div>}
  <div className="v5-land-total-amount" data-reviewed-rows><span>{amountStatus.status==='manual'?'사용자 가정 적용액':'전체 토지매입대금'}</span><strong>{eok(amountStatus.appliedWon)}</strong></div>
  {amountStatus.fallbackUsed&&<small className="v6-land-fallback-note" data-reviewed-rows>{amountStatus.fallbackSummary} 포함</small>}
  <ModelLandEstimate land={land}/>
  {!amountStatus.completeness.complete&&<details className="v5-land-completeness"><summary>{amountStatus.label} · {amountStatus.summary}</summary><span>{amountStatus.confirmedSubtotalWon!==null?`확인분 소계 ${eok(amountStatus.confirmedSubtotalWon)}`:'확인된 산정 금액 없음'}</span><small>부분 금액은 전체 토지비에 적용하지 않습니다.</small>{reasons.length>0&&<small className="v5-land-hold">{reasons.join(' · ')}</small>}</details>}
 </DataComponent>;
}
