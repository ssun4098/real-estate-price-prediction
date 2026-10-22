import React from 'react';
import {DataComponent} from '../../data-app-public.jsx';
import {facilityDistanceBands} from './map-overlays.mjs';
import {FacilityIcon} from './FacilityIcon.jsx';
import './facility-bands.css';

const statuses={success:'조회 완료',empty:'조회 완료 · 검색 0건',partial:'일부 조회',error:'조회 실패',credentials_missing:'인증 미준비',permission_required:'이용 권한 확인 필요',not_requested:'조회 전'};
export function FacilityBands({survey,state={},onRetry}){
 const bands=facilityDistanceBands(state.loading?null:survey),max=Math.max(1,...bands.flatMap(b=>b.categories.map(c=>c.observedCount||0)));
 const incomplete=bands[0].categories.filter(c=>c.status!=='success'&&c.status!=='empty');
 const shortRadius=Number.isFinite(survey?.query?.radiusKm)&&survey.query.radiusKm<5;
 return <DataComponent id="pf-v5-facility-bands" queryId="liveSurvey" kind="custom" title="주변시설 개수" className="v3-chart-card v5-facility-bands" sourceRows={bands.flatMap(b=>b.categories.flatMap(c=>c.rows))} displayRows={bands.flatMap(b=>b.categories.map(({rows,...c})=>({...c,count:c.observedCount,band:b.range})))} description="학교·산·하천·산업단지·하수처리장 중 현재 조회되어 중복 정리한 본시설 후보의 정확한 개수입니다. 거리 구간은 서로 중복되지 않으며, 전체 지역의 시설 총수를 확정한 값은 아닙니다. 미확보는 0개로 취급하지 않습니다.">
  <div className="v5-facility-heading"><span>조회된 시설 · 개 · 구간 간 중복 제외</span></div>
  <div className="v5-facility-band-list" data-reviewed-rows>{bands.map(band=><section key={band.id} className="v5-facility-band" aria-label={`${band.title} · ${band.range}`}>
    <div className="v5-facility-band-heading"><h4>{band.title}</h4><span>{band.range}</span></div>
    <div className="v5-facility-count-chart" role="list" aria-label={`${band.range} 시설별 개수`}>
     {band.categories.map(row=><div className="v5-facility-count-column" role="listitem" key={row.id} title={`${row.label}: ${row.observedCount==null?'미확보':`조회된 시설 ${row.observedCount}개`} · ${statuses[row.status]||row.status}${row.retrievalComplete?'':' · 조회 범위와 완료 여부를 확인하세요'}`}>
      <span className={`v5-facility-count-value${row.observedCount==null?' is-missing':''}`}>{row.observedCount==null?(state.loading?'조회 중':'미확보'):row.observedCount}</span>
      <div className="v5-facility-count-track"><span style={{height:`${(row.observedCount||0)/max*100}%`,backgroundColor:row.color}}/></div>
      <span className="v5-facility-count-label"><FacilityIcon kind={row.id} color={row.color} size={15}/>{row.label}</span>
     </div>)}
    </div>
   </section>)}</div>
  <p className="v5-facility-band-note">조회된 본시설 후보를 중복 정리한 개수입니다. 선택 필지 중심~대표점 직선거리 · 입구·주차장 제외. 지역 전체의 시설 총수는 아닙니다.</p>
  {(state.loading||incomplete.length>0||shortRadius)&&<p className="v5-facility-query-status" role="status">{state.loading?'현재 선택 조건으로 조회 중':<>{incomplete.length>0?`조회 상태: ${incomplete.map(c=>`${c.label} ${statuses[c.status]||c.status}`).join(' · ')}.`:''}{shortRadius?` 조회 반경 ${survey.query.radiusKm}km 밖은 미확보입니다.`:''}</>}</p>}
  {state.error&&<p className="live-note warning" role="alert">{state.error}</p>}
  {onRetry&&<button className="v5-facility-retry" type="button" onClick={onRetry} disabled={state.loading||state.offline}>{state.loading?'주변시설 조회 중':'주변시설 조회'}</button>}
 </DataComponent>;
}
