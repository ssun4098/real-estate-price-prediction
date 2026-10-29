import {sanitizeInputs} from './v2-policy.mjs';
import {comparisonIdentity, selectedParcelRegion} from './comparison-scope.mjs';
import {periods,todayKorea,isLatest,isRolling,rollingPeriodValid,LAND_START_DATE,REVENUE_START_DATE} from './period-policy.mjs';
export {periods,todayKorea} from './period-policy.mjs';

export const DRAFT_KEY='pf-study-input-draft-v5';
export function periodErrors(input,coverage){
 const values=periods(input),asOf=input.project?.asOf,today=todayKorea(),errors=[];
 if(!/^\d{4}-\d{2}-\d{2}$/.test(asOf||'')||asOf>today)errors.push({path:'project.asOf',message:'오늘까지의 올바른 분석 기준일을 입력하세요.'});
 if(isRolling(input)&&!rollingPeriodValid(input))errors.push({path:'comparisonFilters.start',message:'최근 60개월은 매월 1일을 제외한 직전 월말까지여야 합니다. 필지를 선택해 조회기간을 갱신하세요.'});
 for(const [kind,label] of [['land','토지'],['revenue','분양']]){
  const start=values[kind+'Start'],end=values[kind+'End'],bounds=coverage?.[kind],prefix=input.comparisonFilters?.periodMode==='separate'?kind:'';
  const path='comparisonFilters.'+(prefix?prefix+'Start':'start');
  if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(start)||!/^\d{4}-(0[1-9]|1[0-2])$/.test(end)){errors.push({path,message:`${label} 비교 시작·종료월을 입력하세요.`});continue;}
  const months=(Number(end.slice(0,4))-Number(start.slice(0,4)))*12+Number(end.slice(5))-Number(start.slice(5))+1;
  if(months<1||(!isLatest(input)&&months>60))errors.push({path,message:`${label} 비교기간은 올바른 순서의 1~60개월이어야 합니다.`});
  if(end>String(asOf||today).slice(0,7)||end>today.slice(0,7))errors.push({path,message:`${label} 종료월은 분석 기준일과 오늘이 속한 월을 넘을 수 없습니다.`});
  if(isLatest(input)&&start!==(kind==='land'?LAND_START_DATE:REVENUE_START_DATE).slice(0,7))errors.push({path,message:`${label} 고정 시작일을 적용하려면 최신 범위를 확인하세요.`});
  if(!isRolling(input)&&bounds&&(start<(isLatest(input)?(kind==='land'?LAND_START_DATE:REVENUE_START_DATE).slice(0,7):bounds.minMonth)||end>bounds.maxMonth))errors.push({path,message:`${label} 확인 범위는 ${bounds.minMonth}~${bounds.maxMonth}입니다.`});
 }
 return errors.filter((x,i,a)=>a.findIndex(v=>v.path===x.path&&v.message===x.message)===i);
}
export function recentPeriod(asOf,n){if(!/^\d{4}-\d{2}-\d{2}$/.test(asOf||''))return null;const d=new Date(asOf.slice(0,7)+'-01T00:00:00Z');d.setUTCMonth(d.getUTCMonth()-n+1);return {start:d.toISOString().slice(0,7),end:asOf.slice(0,7)};}
function fingerprint(text){let hash=14695981039346656037n;for(let i=0;i<text.length;i++){hash^=BigInt(text.charCodeAt(i));hash=BigInt.asUintN(64,hash*1099511628211n)}return `basis-v1:${text.length}:${hash.toString(16)}`}
export function revenueBasis(input){return fingerprint(JSON.stringify([comparisonIdentity(input),input.unitPlan,input.linkedScenario,input.assumptions?.revenueMethod,input.assumptions?.revenueAdjustmentPct,(input.comparables?.revenueCases||[]).map(r=>[r.id,r.priceManwon,r.supplyAreaM2,r.baseEligible??r.eligible,r.manualExclusion]),input.comparisonFilters?.minSupplyM2,input.comparisonFilters?.maxSupplyM2,input.comparisonFilters?.search]));}
export function calculationIdentity(input){const {uiSettings,uiProgress,planHistory,...core}=input;return JSON.stringify(core);}
export function workflowState(input,result,coverage){
 const region=selectedParcelRegion(input.parcels),periodProblems=periodErrors(input,coverage);
 const regionKnown=!!input.uiProgress?.explorationRegion?.sgg||region.status==='ready';
 const step1=regionKnown&&!periodProblems.length;
 const area=!!input.parcels?.length&&input.parcels.every(p=>Number.isFinite(p.areaM2)&&p.areaM2>0);
 const manualSupply=!!input.unitPlan?.length&&input.unitPlan.every(r=>Number.isInteger(r.units)&&r.units>=0&&(r.units===0||(Number.isFinite(r.supplyAreaM2)&&r.supplyAreaM2>0)))&&input.unitPlan.some(r=>r.units>0);
 const supply=input.linkedScenario?.enabled===true?Number.isInteger(result?.results?.development?.units)&&result.results.development.units>0:manualSupply;
 const revenueReady=Number.isFinite(result?.results?.revenue?.representativeWon);
 const basisConfirmed=!!input.uiProgress?.confirmedRevenueBasis&&input.uiProgress.confirmedRevenueBasis===revenueBasis(input);
 // 목표 수익률은 입력값이 아니라 수지 계산 결과다 (2026-10-29). 사업 예상수지 단계는 수지 계산이 끝났는지로 본다.
 const target=result?.results?.budget?Number.isFinite(result.results.budget.targetMarginPct):true;
 const costsReady=Number.isFinite(result?.results?.costs?.totalWon);
 return {step1,area,supply,revenueReady,basisConfirmed,target,costsReady,periodProblems,region,
  steps:[{label:'사업·조회 조건',target:'live-conditions',ready:step1,hint:!regionKnown?'사업지 지역명을 선택하거나 지도에서 필지를 선택하세요.':periodProblems[0]?.message||'조회 조건 준비 완료'},
  {label:'필지·공급계획',target:'live-parcels',ready:area&&supply,hint:!area?'개발 필지와 대장 면적을 확인하세요.':!supply?'계획 호수·호당 공급면적을 입력하세요.':'필지·공급계획 입력 완료'},
  {label:'비교사례·예상액',target:'live-compare',ready:basisConfirmed,hint:!revenueReady?'비교사례를 조회하고 분양수입 산정 근거를 확인하세요.':!basisConfirmed?'분양수입 기준 확인 버튼을 누르세요.':'분양수입 기준 확인 완료'},
  {label:'사업 예상수지',target:'live-costs',ready:basisConfirmed&&target&&costsReady,hint:!basisConfirmed?'3단계에서 분양수입 기준을 확인하세요.':!target?'수지분석 지출 항목·공급계획을 확인하세요.':!costsReady?'미확보 비용을 확인하세요.':'비용 입력 완료'},
  {label:'현금흐름·기관별 결과',target:'live-cashflow',ready:Number.isFinite(result?.results?.cashflow?.summary?.maxUnfundedWon),hint:!basisConfirmed?'3단계에서 분양수입 기준을 먼저 확인하세요.':!target?'수지분석 지출 항목·공급계획을 먼저 확인하세요.':'지급·수납·조달 일정을 확인하세요.'}]};
}
export function makeDraft(input){
 input=sanitizeInputs(input);
 const selectedKeys=['project','unitPlan','linkedScenario','budgetAllocation','financeEditor','assumptions','costs','cashflow','okr','comparisonFilters','uiSettings','uiProgress','planHistory','siteEvaluation','comparables','sources','landRulesVersion','landMatchPolicy'];
 const data={};for(const k of selectedKeys)if(input[k]!==undefined)data[k]=input[k];
 data.parcels=(input.parcels||[]).map(p=>Object.fromEntries(['pnu','address','geometry','group','areaM2','areaInputMode','areaInputNote','areaBasis','legalDongCode','legalDongName','dong','sourceStatus','attributeRequestedYear','attributes','comparisonProfile','boundaryAllocation','sources','collectionStatus'].filter(k=>p[k]!==undefined).map(k=>[k,p[k]])));
 const result={draftVersion:1,appVersion:'V5',savedAt:new Date().toISOString(),input:data};
 const raw=JSON.stringify(result);if(raw.length>1800000)throw new Error('초안이 보관 용량을 초과했습니다. 분석 결과를 별도로 저장하세요.');
 if(/(?:serviceKey|confmKey|apiKey|credentials|authorization)\s*"\s*:/i.test(raw))throw new Error('인증정보가 포함된 초안은 보관하지 않습니다.');
 return result;
}
export function restoreDraft(draft){
 if(draft?.draftVersion!==1||!draft.input||typeof draft.input!=='object')throw new Error('지원하지 않는 입력 초안입니다. 기존 분석 JSON을 사용하세요.');
 const safe=makeDraft(draft.input).input;
 return {...safe,comparables:{...safe.comparables,revenueCases:[],landCases:safe.comparables?.landCases||[]},sources:safe.sources||[],collectionStatus:'V5 초안 복구 · 보관 토지자료 계산 · 새 필지 선택 후 조회',uiProgress:{...safe.uiProgress,confirmedRevenueBasis:null},parcels:(safe.parcels||[]).map(p=>({...p,sourceStatus:p.attributes?'보관된 조회 자료 · 출처 시점 확인':'초안 · 현재 속성 재확인 필요'})),selectionReviewRequired:true};
}
