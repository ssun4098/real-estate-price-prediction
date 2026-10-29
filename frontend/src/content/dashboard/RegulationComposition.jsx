import React from 'react';
import {DataComponent} from './data-component.jsx';
import {designationComposition} from './survey-summary.mjs';
import {number} from './pf-live-widgets.jsx';
import './regulation-composition.css';

const percentage=value=>Number.isFinite(value)?`${value.toLocaleString('ko-KR',{maximumFractionDigits:1})}%`:'—';

export default function RegulationComposition({parcels,onEvidence}){
 const groups=designationComposition(parcels),rows=groups.flatMap(group=>group.rows.map(row=>({category:group.title,...row}))),sources=groups.flatMap(group=>group.evidence.map(row=>({category:group.title,...row})));
 return <DataComponent id="pf-v5-regulation-composition" queryId="liveSurvey" kind="custom" title="용도지역·지구·구역" className="v3-chart-card v5-regulation-composition" sourceRows={sources} displayRows={rows} description="각 종류 안에서 지정명별 필지 수를 더한 값(미확인 포함)을 분모로 구성비를 계산합니다. 같은 필지의 같은 지정은 한 번, 서로 다른 지정은 각각 집계합니다. 접함은 제외합니다.">
  <div className="v3-chart-unit">필지 수 · 가로 막대 · 종류별 구성비</div>
  <div className="v5-regulation-scroll" tabIndex={0} role="region" aria-label="용도지역·용도지구·용도구역별 필지 수와 구성비" data-reviewed-rows>
   <table className="v5-regulation-table">
    <colgroup><col className="designation"/><col className="distribution"/><col className="count"/><col className="share"/></colgroup>
    <thead><tr><th scope="col">지정명</th><th scope="col"><span className="v5-regulation-axis"><span>0%</span><span>50%</span><span>100%</span></span></th><th scope="col">필지 수</th><th scope="col">구성비</th></tr></thead>
    {groups.map(group=><tbody key={group.kind}>
     <tr className="v5-regulation-group"><th colSpan="4" scope="colgroup"><span>{group.title}</span><small>합계 {number(group.total,0)}{group.multipleParcels?` · 복수 지정 ${number(group.multipleParcels,0)}필지`:''}</small><button type="button" className="v4-chart-detail-button" onClick={()=>onEvidence?.(group)}>지정 원문 보기</button></th></tr>
     {group.rows.length?group.rows.map(row=><tr key={row.label}>
      <th scope="row">{row.label}</th><td><div className={'v5-regulation-bar-track'+(row.label==='미확인'?' is-unknown':'')} aria-hidden="true"><span style={{width:`${row.percentage}%`}}/></div></td><td className="num">{number(row.value,0)}</td><td className="num">{percentage(row.percentage)}</td>
     </tr>):<tr><td colSpan="4" className="v5-regulation-empty">필지를 선택하면 지정별 구성비가 표시됩니다.</td></tr>}
    </tbody>)}
   </table>
  </div>
  <small className="v3-chart-note">구성비 = 해당 지정 필지 수 ÷ 종류별 합계(미확인 포함). 복수 지정은 각각 집계하며, 면적 비율이 아닙니다. 접함 제외.</small>
 </DataComponent>;
}
