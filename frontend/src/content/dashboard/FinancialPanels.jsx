import React, { useMemo, useState } from 'react';
import { DataComponent, EvidenceChart } from '../../data-app-public.jsx';
import { calculateModel, MODEL_NOTES } from './financial-model.mjs';

const nf=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2});
const money=v=>Number.isFinite(v)?`${nf.format(Math.abs(v)<1e-8?0:v)}억`:'미산출';
const pct=v=>Number.isFinite(v)?`${nf.format(v)}%`:'미산출';
const names={revenue:'전량 판매 가정 순매출',targetMargin:'목표 세전 사업이익률',startDate:'사업 시작월',land:'토지 취득비',construction:'본 도급공사비',separate:'별도 공사비',design:'설계·감리·사업관리비',taxes:'세금·부담금·보증료',salesFeeRate:'판매 수수료율',monthlyOpex:'월 운영비',reserve:'예비비',trustType:'신탁 유형',trustRate:'신탁보수율',trustBasis:'신탁보수 기준금액',trustExtension:'연장보수 총액',initialCash:'초기 자기자본',bridgeAmount:'브릿지 인출액',bridgeRate:'브릿지 연이율',bridgeFeeRate:'브릿지 인출 수수료율',pfLimit:'PF 누적 인출한도',pfRate:'PF 연이율',pfFeeRate:'PF 인출 수수료율',pfStart:'PF 개시월',completion:'계약상 준공월',pfMaturity:'PF 만기월',salesStart:'분양 개시월',salesMonths:'판매기간',soldPct:'계약 가정 비율',depositPct:'계약금 비율',interimPct:'중도금 비율',balanceLagMonths:'준공·계약 후 잔금 시차',delayMonths:'준공 지연',costIncreasePct:'공사비 증액률'};
const rates=new Set(['targetMargin','salesFeeRate','trustRate','bridgeRate','bridgeFeeRate','pfRate','pfFeeRate','soldPct','depositPct','interimPct','costIncreasePct']);
const periods=new Set(['pfStart','completion','pfMaturity','salesStart','salesMonths','balanceLagMonths','delayMonths']);
const trusts={managed:'관리형',completion:'책임준공관리형',borrowed:'차입형'};
const evidence=input=>Object.entries(input||{}).map(([key,value])=>({항목:names[key]||key,입력값:value??'미확보',자료상태:value==null?'미확보':'사용자 가정'}));

function downloadCsv(filename,rows){
  if(!rows.length)return;const keys=Object.keys(rows[0]);
  const q=v=>{let s=String(v??'');if(/^[=+@]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
  const csv='\uFEFF'+[keys.map(q).join(','),...rows.map(r=>keys.map(k=>q(r[k])).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
}
function Missing({model}){const missing=model?.missing||[];return <div className="pf-empty"><strong>사업 조건 입력 대기</strong><div>{missing.slice(0,5).map(k=>names[k]||k).join(' · ')||'입력값을 확인하세요.'}{missing.length>5?` 외 ${missing.length-5}개`:''}</div>{model?.errors?.map((e,i)=><p key={i}>{e}</p>)}<p className="pf-mini-note">미확보 비용은 0원으로 대체하지 않습니다. 좌측 조건을 입력하거나 예시 가정을 불러오세요.</p></div>;}
function Tabs({items,value,onChange}){return <div className="pf-subnav" role="tablist">{items.map(([id,label])=><button type="button" role="tab" aria-selected={id===value} className={id===value?'active':''} onClick={()=>onChange(id)} key={id}>{label}</button>)}</div>;}
function Stats({rows}){return <dl className="pf-stat-list">{rows.map(([label,value],i)=><div key={i}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;}

export function FinancialPanel({model,input,inputEvidence=[],onEvidenceChange}){
  const [tab,setTab]=useState('budget');const s=model?.summary;
  const budget=useMemo(()=>!s?[]:[
    ['토지 취득비',input.land],['본 도급공사비',s.construction],['별도 공사비',s.separate],['설계·감리·사업관리비',input.design],['세금·부담금·보증료',input.taxes],
    ['판매 수수료 · 전량판매 예산',s.revenue*input.salesFeeRate/100],['운영비 · 분석기간 전체',input.monthlyOpex*model.months.length],['예비비',input.reserve],
    ['신탁보수 · 연장보수 포함',s.trustFee],['브릿지 이자 · 발생액',s.bridgeInterestAccrued],['PF 이자 · 발생액',s.pfInterestAccrued],['대출 인출 수수료',s.lenderFeeIncome]
  ].map(([항목,금액])=>({항목,금액,비중:s.totalCost?금액/s.totalCost*100:null})),[s,input,model]);
  const chartRows=useMemo(()=>model?.valid?model.months.map(m=>({월:m.date,분양수납:m.receipts,사업비지급:m.operatingPaid,차입잔액:m.bridgeBalance+m.pfBalance,미조달액:m.unfunded})):[],[model]);
  const sourceRows=inputEvidence.length?inputEvidence:evidence(input);
  return <section className="pf-panel"><div className="pf-panel-head"><div><h2>수지와 월별 자금흐름</h2><p>이익과 현금은 다르게 움직입니다. 금액 단위: 억원</p></div>{model?.valid&&<button className="pf-btn" onClick={()=>downloadCsv(tab==='cash'?'PF_월별현금흐름.csv':tab==='inputs'?'PF_입력근거.csv':'PF_사업수지.csv',tab==='cash'?model.months:tab==='inputs'?sourceRows:budget)}>CSV 받기</button>}</div>
    <Tabs items={ [['budget','사업수지'],['cash','월별 자금흐름'],['inputs','입력값·근거']] } value={tab} onChange={setTab}/>
    {tab==='inputs'?<DataComponent id="financial-inputs" title="계산 입력값" kind="table" queryId="scenarioInputs" sourceRows={sourceRows} displayRows={sourceRows} showHeading={false}>
      <div className="pf-table-scroll" data-reviewed-rows><table><thead><tr><th>항목</th><th>현재 입력</th><th>상태</th></tr></thead><tbody>{Object.entries(input||{}).filter(([k])=>names[k]).map(([key,value])=><tr key={key}><td>{names[key]}</td><td>{value==null?(key==='trustBasis'?'전량판매 매출 기준':'미확보'):key==='trustType'?trusts[value]:key==='startDate'?value:rates.has(key)?pct(value):periods.has(key)?`${value}개월`:money(value)}</td><td>{value==null?(key==='trustBasis'?'산식 기준':'미확보'):key==='revenue'?'공개자료 기반 추정':<select aria-label={`${names[key]} 자료 상태`} value={sourceRows.find(r=>r.key===key)?.source||'사용자 가정'} onChange={e=>onEvidenceChange?.(key,e.target.value)}>{['사용자 가정','교육용 예시 가정','공개자료 기반 추정','계약·견적','계약·견적 입력','실적','실적+잔여 견적 입력'].map(x=><option key={x} value={x}>{x}</option>)}</select>}</td></tr>)}</tbody></table></div><p className="pf-mini-note">0개월은 사업 시작월입니다. 거래사례로 산출한 매출도 실제 계약수입을 보장하지 않습니다. 각 비용의 자료 상태와 산정 근거는 좌측 입력에서 관리합니다.</p>
    </DataComponent>:!model?.valid?<Missing model={model}/>:tab==='budget'?<>
      <DataComponent id="financial-budget" title="비용별 구성" kind="table" queryId="scenarioInputs" sourceRows={sourceRows} displayRows={budget} showHeading={false}>
      <div className="pf-benchmark-stats"><div><strong>{money(s.potentialRevenue)}</strong><span>전량 판매 가정 매출</span></div><div><strong>{money(s.contractedRevenue)}</strong><span>계약 가정액</span></div><div><strong>{money(s.receipts)}</strong><span>계획 전체 수납액</span></div></div>
      <div className="pf-table-scroll" data-reviewed-rows><table><thead><tr><th>지출 항목</th><th>예상 비용</th><th>총사업비 비중</th></tr></thead><tbody>{budget.map(r=><tr key={r.항목}><td>{r.항목}</td><td>{money(r.금액)}</td><td>{r.비중==null?'해당 없음':pct(r.비중)}</td></tr>)}<tr className="total"><td>예상 총사업비</td><td>{money(s.totalCost)}</td><td>{s.totalCost? '100%':'해당 없음'}</td></tr><tr><td>목표 이익률에 따른 허용 사업비</td><td>{money(s.allowableCost)}</td><td>{pct(input.targetMargin)} 목표</td></tr><tr className="total"><td>허용 비용 대비 여유</td><td className={s.costHeadroom>=0?'positive':'negative'}>{money(s.costHeadroom)}</td><td>{s.costHeadroom>=0?'범위 이내':'조정 필요'}</td></tr><tr><td>세전 잠재이익 / 이익률</td><td>{money(s.profit)}</td><td>{pct(s.margin)}</td></tr></tbody></table></div>
      <p className="pf-mini-note">비용표 합계와 엔진 총사업비 차이: {money(budget.reduce((v,r)=>v+r.금액,0)-s.totalCost)}. 대출원금 상환·출자금 반환은 비용에서 제외합니다. 신탁보수는 전체 계약기간 기준입니다.</p>
      </DataComponent><div className="pf-notice warning">전량 판매 가정 손익입니다. 미분양 {money(s.inventoryPotential)}은 현금에 포함하지 않았으며 분석 종료 이후 보유·판매비용은 별도로 확인해야 합니다.</div>
    </>:<>
      <EvidenceChart id="monthly-funding-chart" title="수납·차입·미조달 흐름" queryId="scenarioInputs" rows={chartRows} sourceRows={sourceRows} height={250} spec={{type:'line',x:'월',y:'분양수납',fields:['분양수납','차입잔액','미조달액'],yLabel:'억원',stackable:false,showXAxisLabel:false,colors:{분양수납:'var(--pf-accent)',차입잔액:'var(--chart-1)',미조달액:'var(--pf-risk)'}}}/>
      <div className="pf-chart-note"><span>차입잔액은 월말 기준</span><span>분석 종료: {model.months.at(-1)?.date}</span></div>
      <DataComponent id="monthly-funding-table" title="월별 자금수지" kind="table" queryId="scenarioInputs" sourceRows={sourceRows} displayRows={model.months} showHeading={false}>
      <div className="pf-table-scroll pf-cash-table" data-reviewed-rows><table><thead><tr><th>월</th><th>수납</th><th>사업비 지급</th><th>신규차입</th><th>이자·수수료 지급</th><th>원금 상환</th><th>월말 현금</th><th>미조달액</th></tr></thead><tbody>{model.months.map(m=><tr key={m.index}><td>{m.date}{m.index===input.pfMaturity&&<small>PF 만기</small>}</td><td>{nf.format(m.receipts)}</td><td>{nf.format(m.operatingPaid)}</td><td>{nf.format(m.bridgeDraw+m.pfDraw)}</td><td>{nf.format(m.interestPaid+m.feesPaid)}</td><td>{nf.format(m.bridgePrincipalPaid+m.pfPrincipalPaid)}</td><td>{nf.format(m.cash)}</td><td className={m.unfunded>0?'negative':''}>{nf.format(m.unfunded)}</td></tr>)}</tbody></table></div></DataComponent>
      <p className="pf-mini-note">미조달액은 지급기일이 지난 의무잔액입니다. 미지급 비용을 현금 지급으로 표시하지 않으며, PF 만기월부터 신규 인출을 중단합니다. 월별 현금 대사 최대오차: {money(model.reconciliation.maxCashError)}.</p>
    </>}
    <details className="pf-accordion"><summary>계산 방식과 적용 범위</summary><ul className="pf-insight-list">{MODEL_NOTES.map((n,i)=><li key={i}>{n}</li>)}</ul></details>
  </section>;
}

export function StakeholderPanel({model,input,exit,cap,landLimit,scaleStatus="missing"}){
  const [tab,setTab]=useState('developer'),[otherRates,setOtherRates]=useState({managed:null,completion:null});const s=model?.summary;
  const sourceRows=evidence(input);
  const landCap=typeof landLimit==='number'?landLimit:landLimit?.landCap??landLimit?.cap??landLimit?.limit;
  const ratesByType={managed:input.trustType==='managed'?input.trustRate:otherRates.managed,completion:input.trustType==='completion'?input.trustRate:otherRates.completion};
  const trustCases=Object.entries(ratesByType).map(([type,rate])=>({type,rate,result:rate==null?null:calculateModel({...input,trustType:type,trustRate:rate})}));
  return <><section className="pf-panel"><h3>누구의 관점으로 볼까요?</h3><Tabs items={ [['developer','시행사'],['lender','대주'],['trust','신탁사']] } value={tab} onChange={setTab}/>
    {!model?.valid?<Missing model={model}/>:<DataComponent id={`stakeholder-${tab}`} title={`${tab==='developer'?'시행사':tab==='lender'?'대주':'신탁사'} 검토`} kind="table" queryId="scenarioInputs" sourceRows={sourceRows} displayRows={[s]} showHeading={false}>
    {tab==='developer'?<><span className={`pf-status ${s.targetMet&&s.liquidityClear&&scaleStatus!=='exceeded'?'good':'risk'}`}>{scaleStatus==='exceeded'?'건축규모 상한 초과':s.targetMet&&s.liquidityClear?'수익·자금만 충족 · 규모 별도 검토':'수익·자금 조건 검토'}</span><Stats rows={[
      ['규모 입력 검토',scaleStatus==='exceeded'?'용적률 상한 초과':scaleStatus==='missing'?'부지·연면적 미확보':'입력 상한 이내 · 인허가 미검증'],['전량판매 가정 이익률',pct(s.margin)],['목표 대비 차이',`${nf.format(s.margin-input.targetMargin)}%p`],['최대 미조달액',money(s.peakUnfunded)],['발생월',s.peakUnfundedMonth||'없음'],['본 도급비 허용 상한',cap?.status==='solved'?money(cap.constructionCap):cap?.status==='unattainable'?'현재 조건 불가':'미산출'],['토지비 허용 상한',money(landCap)]
    ]}/><p className="pf-insight">허용 비용은 <strong>목표 수익률의 경계</strong>입니다. 토지·공사비 상한은 각각 다른 비용을 고정한 결과이며 동시에 적용할 수 없습니다. 실제 매입가격·견적 및 건축계획과 비교하세요. 비용 상한을 충족해도 자금조달이 부족하면 실행 조건을 충족하지 못합니다.</p></>:
    tab==='lender'?<><span className={`pf-status ${model.months[input.pfMaturity].unfunded<1e-8?'good':'risk'}`}>{model.months[input.pfMaturity].unfunded<1e-8?'만기 도래 의무 잔액 0':'만기 지급·상환 부족'}</span><Stats rows={[
      ['최대 PF 잔액',money(s.pfPeak)],['PF 누적 인출',money(s.pfDrawTotal)],['만기 PF 미상환액',money(s.pfMaturityShortfall)],['만기 브릿지 원리금·수수료',money(s.bridgeAtPfMaturity)],['만기 전체 미조달 의무액',money(model.months[input.pfMaturity].unfunded)],['PF 발생 이자',money(s.pfInterestAccrued)],['브릿지 발생 이자',money(s.bridgeInterestAccrued)],['브릿지+PF 발생 수익',money(s.lenderGrossIncome)],['브릿지+PF 현금 수취',money(s.lenderCashIncome)],['추정 Exit 분양률',exit?.status==='solved'?pct(exit.exitPct):exit?.status==='unattainable'?'현재 경로 불가':'미산출'],['만기 예상 금액 분양률',pct(s.maturitySalesPct)]
    ]}/><p className="pf-insight">합계 수익은 브릿지와 본 PF의 이자·수수료이며, 개별 금융기관의 순이익이 아닙니다. 조달원가·신용손실·운영비는 미포함입니다. <strong>Exit 여유만으로 승인하지 않고 만기 부족액을 함께 확인</strong>합니다.</p>{exit?.note&&<p className="pf-mini-note">{exit.note}</p>}</>:
    <><span className="pf-status">인수 판단에는 추가 자료 필요</span><Stats rows={ [['선택 유형',trusts[input.trustType]],['기준금액',money(s.trustBasis)],['약정 기본 보수율',pct(input.trustRate)],['총 보수 · 연장 포함',money(s.trustFee)]]}/>
    <p className="pf-insight">관리형·책임준공형의 <strong>비교 요율을 직접 입력</strong>하세요. 공통 표준요율로 가정하지 않습니다.</p>
    {trustCases.map(({type,rate,result})=><div key={type} style={{marginTop:10}}><label className="pf-label">{trusts[type]} 비교 보수율 (%)<input type="number" min="0" step="0.1" value={rate??''} disabled={type===input.trustType} placeholder="비교 요율 입력" onChange={e=>setOtherRates(v=>({...v,[type]:e.target.value===''?null:Math.max(0,Number(e.target.value))}))}/></label><p className="pf-mini-note">{result?.valid?`보수 ${money(result.summary.trustFee)} · 시행사 잠재이익률 ${pct(result.summary.margin)}`:'요율 미확보 · 비교 보류'}</p></div>)}
    <p className="pf-insight">보수 차이는 인수 위험의 가격을 확정하지 않습니다. 시공사 재무·공정계획·교체 비용·책임준공 약정 범위를 확보해야 합니다. 비교 중 금융조건은 동일하게 유지합니다.</p></>}
    </DataComponent>}
  </section></>;
}

export function SensitivityPanel({model,input,project,onApply}){
  const [mode,setMode]=useState('priceCost');
  const modes={priceCost:{label:'분양가 × 도급비',x:[-10,-5,0,5,10],y:[-10,-5,0,5,10],xTitle:'분양가격 변화',yTitle:'본 도급비 변화',metric:'전량판매 가정 이익률',percent:true},salesSpeed:{label:'판매 속도 × 수납시차',x:[6,12,18,24,30],y:[0,1,3,6,12],xTitle:'판매기간',yTitle:'잔금 시차',metric:'만기 미조달액',percent:false},salesTiming:{label:'분양률 × 수납시차',x:[20,40,60,80,100],y:[0,1,3,6,12],xTitle:'전체 계약 비율',yTitle:'잔금 시차',metric:'만기 미조달액',percent:false},delayCost:{label:'준공 지연 × 공사비',x:[0,3,6,9,12],y:[0,5,10,15,20],xTitle:'준공 지연',yTitle:'공사비 증액률',metric:'전량판매 가정 이익률',percent:true},rateLimit:{label:'금리 × PF 한도',x:[-2,-1,0,1,2],y:[0.6,0.8,1,1.2,1.4],xTitle:'PF 금리 변화',yTitle:'PF 한도 배수',metric:'만기 미조달액',percent:false}};
  const cfg=modes[mode];
  const cells=useMemo(()=>{
    if(!model?.valid)return [];
    return cfg.y.map(y=>cfg.x.map(x=>{
      let changed={...input},priceAdjustment;
      if(mode==='priceCost'){changed.revenue=input.revenue*(1+x/100);changed.construction=input.construction*(1+y/100);priceAdjustment=((1+(Number(project?.priceAdjustment)||0)/100)*(1+x/100)-1)*100;}
      if(mode==='salesTiming'){changed.soldPct=x;changed.balanceLagMonths=y;}
      if(mode==='salesSpeed'){changed.salesMonths=x;changed.balanceLagMonths=y;}
      if(mode==='delayCost'){changed.delayMonths=x;changed.costIncreasePct=y;}
      if(mode==='rateLimit'){changed.pfRate=Math.max(0,input.pfRate+x);changed.pfLimit=input.pfLimit*y;}
      const result=calculateModel(changed);const value=result.valid?(cfg.percent?result.summary.margin:result.months[changed.pfMaturity].unfunded):null;
      const good=result.valid&&(cfg.percent?result.summary.targetMet&&result.summary.liquidityClear:value<1e-8);
      return {x,y,changed,priceAdjustment,result,value,good};
    }));
  },[model,input,project?.priceAdjustment,mode]);
  const labelX=x=>mode==='priceCost'?`${x>0?'+':''}${x}%`:mode==='salesTiming'?`${x}%`:['delayCost','salesSpeed'].includes(mode)?`${x}개월`:`${x>0?'+':''}${x}%p`;
  const labelY=y=>mode==='priceCost'?`${y>0?'+':''}${y}%`:['salesTiming','salesSpeed'].includes(mode)?`${y}개월`:mode==='delayCost'?`${y}%`:`${nf.format(y)}배`;
  return <section className="pf-panel"><div className="pf-panel-head"><div><h2>조건을 바꾸어 의사결정하기</h2><p>셀을 누르면 해당 시나리오를 전체 대시보드에 적용합니다.</p></div></div>
    <Tabs items={Object.entries(modes).map(([key,v])=>[key,v.label])} value={mode} onChange={setMode}/>
    {!model?.valid?<Missing model={model}/>:<DataComponent id={`sensitivity-${mode}`} title={`${cfg.label} 민감도`} kind="table" queryId="scenarioInputs" sourceRows={evidence(input)} displayRows={cells.flat().map(c=>({가로변수:c.x,세로변수:c.y,결과:c.value,지표:cfg.metric}))} showHeading={false}>
      <p className="pf-mini-note">가로: {cfg.xTitle} · 세로: {cfg.yTitle} · 셀: {cfg.metric}{!cfg.percent?' (억원)':''}</p>
      <div className="pf-table-scroll" data-reviewed-rows><table className="pf-heatmap"><thead><tr><th>{cfg.yTitle}</th>{cfg.x.map((x,i)=><th key={i}>{labelX(x)}</th>)}</tr></thead><tbody>{cells.map((row,j)=><tr key={j}><th>{labelY(cfg.y[j])}</th>{row.map((cell,i)=><td key={i}><button type="button" className={`${cell.good?'good':'bad'} ${mode==='priceCost'&&cell.x===0&&cell.y===0?'base':''}`} disabled={!cell.result.valid} title={`${cfg.xTitle} ${labelX(cell.x)}, ${cfg.yTitle} ${labelY(cell.y)} — 적용`} onClick={()=>onApply({input:cell.changed,...(cell.priceAdjustment===undefined?{}:{priceAdjustment:cell.priceAdjustment}),scenarioName:`${cfg.label} ${labelX(cell.x)} / ${labelY(cell.y)}`})}>{cell.value==null?'미산출':cfg.percent?pct(cell.value):nf.format(cell.value)}</button></td>)}</tr>)}</tbody></table></div>
      <p className="pf-mini-note">{cfg.percent?'초록: 목표 이익률 충족 및 기간 중 미조달액 0원. 붉은색: 둘 중 하나 이상 미충족.':'초록: 만기 도래 의무의 미조달액 0원. 기간 중 별도 자금 부족 여부는 최대 미조달액에서 확인하세요.'} {mode==='priceCost'?'가격과 본 도급비는 현재 입력값 대비 증감입니다.':mode==='rateLimit'?'금리는 현재값 대비 %p, 한도는 현재 누적인출 약정 대비 배수입니다.':'표의 숫자는 절대 가정값입니다.'}</p>
    </DataComponent>}
  </section>;
}
