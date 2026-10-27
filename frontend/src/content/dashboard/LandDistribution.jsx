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

// '예상 토지매입대금' 칸은 모델 예측만 보여 준다. 수지분석 표도 같은 금액을 쓴다 (비교사례 금액은 상세 테이블에서 확인).
// (위의 UnitPriceBox·FallbackPrice 는 지금 이 칸에서 쓰지 않음. 비교사례 분포를 다시 보여 줄 때 사용)
export function V5LandPlot({land,rows}){
 return <DataComponent className="v3-plot-source v5-land-plot" id="pf-live-land-box" queryId="liveLand" kind="custom" title="예상 토지매입대금" sourceRows={rows} displayRows={[]} description="토지 단가 예측 모델(CatBoost)이 예측한 시군구·지목·용도지역 그룹의 6개월 뒤 월간 거래단가 중앙값에 필지 면적을 곱한 금액입니다. 모델이 예측하지 못한 필지는 예측한 필지들의 평균 단가로 채웁니다. 이 금액이 수지분석 표의 예상 토지매입대금 기준입니다. 모델이 꺼져 있으면 비교사례 금액을 씁니다.">
  <ModelLandEstimate land={land}/>
 </DataComponent>;
}
