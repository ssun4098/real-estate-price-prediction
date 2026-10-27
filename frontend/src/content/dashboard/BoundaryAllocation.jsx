import React from 'react';
import {DataComponent,DataTable} from '../../data-app-public.jsx';
import {boundaryView,boundaryNumber as fmt} from './boundary-display.mjs';
import {landAmountStatus} from './land-completeness.mjs';
import './boundary-allocation.css';

const metric=(value,suffix='',decimals=2)=>Number.isFinite(value)?fmt(value,decimals)+suffix:'미확인';
const sourceUrl=value=>{try{const url=new URL(value);return url.protocol==='https:'||url.protocol==='http:'?url.href:null;}catch{return null;}};
export function BoundaryPartDetail({part,onClose}){
 return <div className="v5-boundary-map-detail" role="status" data-reviewed-rows>
  <span><i style={{background:part.color}}/>{part.parcelNumber}번 · {part.zoneName||'용도지역 미확인'}</span>
  <strong>{part.pricingExcluded?'접함 미세 교차 · 금액 제외':part.status==='ready'?metric(part.allocatedAreaM2,'㎡'):'면적 배분 보류'} <small>{metric(Number.isFinite(part.ratio)?part.ratio*100:null,'%')}</small></strong>
  <span>{part.fallback?.used?'중앙값 대체 단가':'사례 기준 단가'} {part.pricingExcluded?'미적용':part.appliedUnitPriceWonM2==null?'미산출':fmt(part.appliedUnitPriceWonM2,0)+'원/㎡'}</span>
  <small>{part.pricingStatus} · {part.zoneMatchKey||'비교그룹 미확정'}</small>
  {part.fallback?.used&&<small>다른 {part.fallback.sourceGroupCount}개 그룹의 유효 거래 {part.fallback.sourceCaseCount}건을 모아 계산한 단가 중앙값</small>}
  {onClose&&<button onClick={onClose} aria-label="용도지역 경계 상세 닫기">닫기</button>}
 </div>;
}
export default function BoundaryAllocation({parcels=[],land={},state={},onRetry,printing=false}){
 const view=boundaryView(parcels,land),amountStatus=landAmountStatus(land),rows=view.parts.map(part=>({...part,sharePct:Number.isFinite(part.ratio)?part.ratio*100:null}));
 const columns=[
  {key:'parcelNumber',label:'필지',type:'number',renderCell:(v,r)=><span>{v}번<small className="v5-boundary-cell-sub">{r.address}</small></span>},
  {key:'zoneName',label:'용도지역',renderCell:(v,r)=><span className="v5-boundary-zone"><i style={{background:r.color}}/>{v}<small className="v5-boundary-cell-sub">{r.zoneCode||'코드 미제공'} · {r.zoneMatchKey||'비교그룹 미확정'}</small></span>},
  {key:'geometryAreaM2',label:'교차 도형면적·㎡',type:'number',renderCell:v=>metric(v)},
  {key:'sharePct',label:'필지 도형 중 비율·%',type:'number',renderCell:v=>metric(v)},
  {key:'allocatedAreaM2',label:'토지비 배분면적·㎡',type:'number',renderCell:(v,r)=>r.pricingExcluded?'금액 제외':v==null?'보류':fmt(v)},
  {key:'appliedUnitPriceWonM2',label:'적용 단가·원/㎡',type:'number',renderCell:(v,r)=>r.pricingExcluded?'미적용':v==null?'미산출':<span>{fmt(v,0)}{r.fallback?.used&&<small className="v5-boundary-cell-sub">중앙값 대체</small>}</span>},
  {key:'estimatedWon',label:'산정 기준액·억원',type:'number',renderCell:(v,r)=>r.pricingExcluded?'미적용':v==null?'미산출':fmt(v/1e8)},
  {key:'pricingStatus',label:'적용 상태',renderCell:(v,r)=><span>{v}{r.fallback?.used&&<small className="v5-boundary-cell-sub">다른 {r.fallback.sourceGroupCount}개 그룹 · 유효 거래 {r.fallback.sourceCaseCount}건의 단가 중앙값</small>}</span>},
 ];
 return <section className="v5-boundary-allocation">
  <div className="v5-boundary-heading" data-reviewed-rows><p>경계 확인 <strong>{view.readyCount}필지</strong> · 보류 <strong>{view.heldCount}필지</strong></p>{onRetry&&!printing&&<button disabled={!parcels.length||Object.values(state).some(s=>s?.loading)} onClick={()=>onRetry()}>선택 필지 경계 다시 조회</button>}</div>
  {parcels.length>0&&amountStatus.modelUsed&&<p data-reviewed-rows><strong>비교사례 기준 상세</strong> · {amountStatus.summary}{amountStatus.confirmedSubtotalWon!==null?` · 비교사례 합계 ${fmt(amountStatus.confirmedSubtotalWon/1e8)}억원`:''} · 수지분석에는 모델 예측 {fmt(amountStatus.appliedWon/1e8)}억원을 적용합니다 ({amountStatus.modelSummary}).</p>}
  {parcels.length>0&&!amountStatus.modelUsed&&<p data-reviewed-rows><strong>{amountStatus.label}</strong> · {amountStatus.summary}{amountStatus.confirmedSubtotalWon!==null?` · 확인분 소계 ${fmt(amountStatus.confirmedSubtotalWon/1e8)}억원`:''}{!amountStatus.completeness.complete?' · 미완료 필지 금액은 0원으로 처리하지 않습니다.':''}</p>}
  {amountStatus.fallbackUsed&&<p data-reviewed-rows><strong>동일 그룹 비교사례 없음 · 중앙값 대체</strong> · {amountStatus.fallbackSummary}</p>}
  <p>필지와 용도지역이 실제로 겹치는 도형을 계산합니다. <strong>토지비 배분면적 = 대장 면적 × (교차 도형면적 ÷ 필지 도형면적)</strong>. 토지비는 같은 용도지역·지목 그룹의 사례 단가를 우선 적용해 합산합니다. 동일 그룹에 사례가 없으면 다른 그룹의 유효 거래 단가를 모아 구한 중앙값으로 대체합니다.</p>
  {!parcels.length&&<p className="v5-boundary-empty">지도에서 개발 대상 필지를 선택하세요.</p>}
  <div className="v5-boundary-checks" data-reviewed-rows>{view.records.map(record=>{const e=record.evidence,s=state[record.pnu]||{};return <article key={record.pnu} className={record.status==='ready'?'is-ready':'is-held'}>
   <div><h3>{record.parcelNumber}번 · {record.address}</h3><strong>{s.loading?'경계 조회 중':record.status==='ready'?'경계 확인 완료':'토지비 산정 보류'}</strong></div>
   {(s.error||record.reasons.length>0)&&<p role={s.error?'alert':undefined}>{s.error||record.reasons.join(' · ')}</p>}
   {record.pricingReasons.filter(reason=>!record.reasons.includes(reason)).length>0&&<p>금액 미산출 사유: {[...new Set(record.pricingReasons.filter(reason=>!record.reasons.includes(reason)))].join(' · ')}</p>}
   {record.parts.some(part=>part.pricingExcluded)&&<p>접함으로 확인된 경계의 미세 교차 {fmt(record.parts.filter(part=>part.pricingExcluded).reduce((sum,part)=>sum+(part.geometryAreaM2||0),0),6)}㎡는 필지 전체 허용오차 {fmt(e.toleranceM2??.01,6)}㎡ 이내여서 금액에서 제외했습니다. 원도형·비율은 보존하며 남은 면적을 100%로 늘리지 않습니다.</p>}
   <dl><div><dt>대장 면적</dt><dd>{metric(e.registerAreaM2,'㎡')}</dd></div><div><dt>필지 도형면적</dt><dd>{metric(e.parcelGeometryAreaM2,'㎡')}</dd></div><div><dt>용도지역 포괄률</dt><dd>{metric(Number.isFinite(e.coverageRatio)?e.coverageRatio*100:null,'%')}</dd></div><div><dt>경계 미포괄 면적</dt><dd>{metric(e.gapAreaM2,'㎡')}</dd></div><div><dt>서로 다른 지역 중첩</dt><dd>{metric(e.overlapAreaM2,'㎡')}</dd></div></dl>
   <small>조회 {e.queriedAt||'미확인'} · 면적 계산 좌표계 {e.source?.areaCrs||'미확인'} · PNU {record.pnu}</small>
   <div className="v5-boundary-sources">{(e.sources||[]).map((source,index)=>{const href=sourceUrl(source.url);return href?<a href={href} target="_blank" rel="noreferrer" key={index}>{source.label||source.layer||'공식 출처'}</a>:<span key={index}>{source.label||source.layer||'출처 미확인'}</span>;})}{onRetry&&!printing&&<button disabled={s.loading} onClick={()=>onRetry(record.pnu)}>{s.loading?'조회 중':'이 필지 다시 조회'}</button>}</div>
  </article>;})}</div>
  <DataComponent id={printing?'pf-v5-boundary-allocation-report':'pf-v5-boundary-allocation-table'} queryId="liveSurvey" kind="table" title="용도지역별 면적·비율·토지비" sourceRows={view.records.map(r=>({pnu:r.pnu,...r.evidence}))} displayRows={rows} description="면적 배분과 비교사례 단가를 분리해 검증합니다. 동일 그룹 사례가 없는 행에는 다른 유효 그룹의 단가 중앙값 대체 여부와 근거 건수를 표시합니다. 보류 필지의 도형 참고값은 금액에 적용하지 않습니다.">
   {printing?<table data-reviewed-rows><caption>용도지역별 자동 면적 배분과 적용 단가 · 전체 행</caption><thead><tr>{columns.map(column=><th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.id}>{columns.map(column=><td key={column.key}>{column.renderCell?column.renderCell(row[column.key],row):row[column.key]}</td>)}</tr>)}</tbody></table>:<DataTable rows={rows} columns={columns} searchable={rows.length>8} compactNumbers={false} rowKey="id" label="용도지역별 자동 면적 배분과 적용 단가"/>}
  </DataComponent>
  <p className="v5-boundary-footnote">합계는 화면에서 반올림하기 전 값으로 계산합니다. 누락·중첩·속성 불일치가 허용오차를 넘으면 전체 토지비를 보류합니다. 이 경계와 면적은 사업 검토용 참고값이며 지적측량이나 법적 경계 확정 자료가 아닙니다. 표와 지도는 수지표의 사례% 조정·직접입력 전 값을 표시합니다. 사례 기준액에 수지표의 조정값을 반영한 토지비는 수지분석에서 확인하세요.</p>
 </section>;
}
