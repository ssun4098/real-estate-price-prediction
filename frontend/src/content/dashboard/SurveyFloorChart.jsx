import React,{useEffect,useRef,useState} from 'react';
import {Dialog} from '../../data-app-public.jsx';
import {EvidenceChart} from './data-component.jsx';
import {number} from './pf-live-widgets.jsx';
import './survey-charts.css';

export default function SurveyFloorChart({summary}){
 const plotRef=useRef(),[height,setHeight]=useState(140),[detail,setDetail]=useState(false);
 useEffect(()=>{const node=plotRef.current;if(!node)return;const measure=()=>setHeight(Math.max(90,Math.floor(node.getBoundingClientRect().height)));measure();const observer=new ResizeObserver(measure);observer.observe(node);return()=>observer.disconnect();},[summary.knownCount]);
 const colors=Object.fromEntries(summary.slices.map((r,i)=>[r.label,['#7baed6','#b6d4eb','#bf8fac','#dbb47c','#7d8a9b'][i]]));
 const excluded=[summary.unknownCount?`층수 미확인 ${summary.unknownCount}동`:null,summary.conflictCount?`층수 충돌 ${summary.conflictCount}동`:null,summary.unidentifiedCount?`식별자 미확인 ${summary.unidentifiedCount}행`:null,summary.mismatchedCount?`다른 필지 ${summary.mismatchedCount}행`:null].filter(Boolean);
 const evidence=[...summary.buildings.flatMap(b=>b.sourceRows.map(row=>({...row,buildingLabel:b.label,floorStatus:b.floorStatus,appliedFloors:b.floors}))),...summary.unidentified,...summary.mismatched];
 return <><EvidenceChart id="pf-v3-building-floors" queryId="liveSurvey" title="건축물 지상층수 구성" className="v3-chart-card v4-floor-card"
  rows={summary.slices} sourceRows={evidence} height={height} description="분모는 지상층수가 확인된 고유 건물 동수입니다. 동일 필지의 여러 동을 각각 집계하고, 식별자 중복은 제거합니다. 미확인·충돌은 비율에서 제외합니다."
  spec={{type:'pie',x:'label',y:'count',showLegend:false,showValues:false,centerValue:`${summary.knownCount}동`,centerLabel:'층수 확인',valueDecimals:0,colors}}
  renderPlot={plot=><div className="v4-floor-body" ref={plotRef} data-reviewed-rows>{summary.knownCount?<><div className="v4-floor-plot">{plot}</div><div className="v4-floor-legend" aria-label="층수별 건물 동수와 비율">{summary.slices.map(row=><div className="v4-floor-legend-row" key={row.label}><span><i style={{background:colors[row.label]}}/>{row.label}</span><strong>{row.count}동 <small>{number(row.share*100,1)}%</small></strong></div>)}</div></>:<div className="v3-chart-empty">층수와 식별자가 확인된 건물 자료가 없습니다.</div>}</div>}>
   <div className="v4-floor-footnote"><small>분모: 층수 확인 {summary.knownCount}동{excluded.length?` · 제외: ${excluded.join(' · ')}`:''}{summary.distribution.length>5?' · 기타는 나머지 층수 합계':''}</small><button className="v4-chart-detail-button" onClick={()=>setDetail(true)}>층수 집계 상세</button></div>
  </EvidenceChart><Dialog open={detail} onClose={()=>setDetail(false)} title="건물별 지상층수 집계 근거" expanded><div className="v4-survey-detail"><p>필지 수가 아닌 고유 건물 동수로 계산합니다. 같은 필지에 건물이 여러 동이면 각각 포함합니다. 동일 식별자 원자료 {summary.duplicateCount}행을 중복 제거했습니다.</p><table data-reviewed-rows><thead><tr><th>지상층수</th><th>건물 동수</th><th>확인 건물 중 비율</th></tr></thead><tbody>{summary.distribution.map(row=><tr key={row.label}><td>{row.label}</td><td>{row.count}동</td><td>{number(row.share*100,1)}%</td></tr>)}</tbody></table><h3>건물별 적용값</h3><table data-reviewed-rows><thead><tr><th>필지 / 건물</th><th>건물 식별자</th><th>지상층수</th><th>판정</th><th>원자료 행수</th></tr></thead><tbody>{summary.buildings.map(b=><tr key={b.id}><td>{b.label}</td><td style={{overflowWrap:"anywhere"}}>{b.identifier}<small>{b.identifierType}</small></td><td>{b.floors==null?'미확인':`${b.floors}층`}</td><td>{b.floorStatus}</td><td>{b.sourceCount}</td></tr>)}</tbody></table>{excluded.length>0&&<p>비율에서 제외: {excluded.join(' · ')}. 원문은 차트의 자료 확인 메뉴에서 확인할 수 있습니다.</p>}</div></Dialog></>;
}
