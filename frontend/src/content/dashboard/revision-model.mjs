import {comparisonIdentity,revenueComparisonIdentity} from './comparison-scope.mjs';
import {calculateLand,LAND_RULE_VERSION} from './land-comparison.mjs';
import {expensePriorityBasis} from './budget-priority.mjs';

export const LINKED_DEFAULTS={enabled:true,farDefaultPct:200,farMaxPct:500,farPct:200,areaMode:'median',supplyAreaM2:null};
export const BUDGET_DEFAULTS={constructionPct:60,indirectPct:4,salesPct:4,taxPct:3,financePct:4,trustType:'',trustRatePct:1};
export const BUDGET_ROWS=[['construction','허용 공사비'],['indirect','허용 간접 공사비'],['sales','허용 분양제비용'],['tax','허용 제세공과금'],['finance','허용 금융비용']];
export const FINANCE_DEFAULTS={revenue:{mode:'comparablePct',value:100},land:{mode:'comparablePct',value:100},expenses:{construction:{mode:'budgetPct',value:60},indirect:{mode:'budgetPct',value:4},sales:{mode:'budgetPct',value:4},tax:{mode:'budgetPct',value:3},finance:{mode:'budgetPct',value:4},trust:{mode:'revenuePct',value:1}}};
const finite=Number.isFinite,positive=x=>finite(x)&&x>0;
const blank=value=>value==null||typeof value==='string'&&value.trim()==='';
// Restore previously unset defaults on file/draft load. In-session explicit
// editor blanks still mean missing input; zero and user-selected bases survive.
export function needsTrustDefaultRestore(input){
 if(!input)return false;
 const trust=input.financeEditor?.expenses?.trust;
 return blank(input.budgetAllocation?.trustRatePct)||!!trust&&[undefined,'revenuePct'].includes(trust.mode)&&blank(trust.value);
}
export function restoreTrustDefaults(input){
 const next={...input,budgetAllocation:{...BUDGET_DEFAULTS,...input.budgetAllocation}};
 if(blank(next.budgetAllocation.trustRatePct))next.budgetAllocation.trustRatePct=1;
 const trust=input.financeEditor?.expenses?.trust;
 if(trust&&[undefined,'revenuePct'].includes(trust.mode)&&blank(trust.value))next.financeEditor={...input.financeEditor,expenses:{...input.financeEditor.expenses,trust:{...trust,mode:'revenuePct',value:next.budgetAllocation.trustRatePct}}};
 return next;
}
export function financeRowSetting(input,id){
 if(['revenue','land'].includes(id))return {...FINANCE_DEFAULTS[id],...input.financeEditor?.[id]};
 const legacy=id==='trust'?input.budgetAllocation?.trustRatePct:input.budgetAllocation?.[id+'Pct'];
 return {...FINANCE_DEFAULTS.expenses[id],...(legacy!==undefined&&!(id==='trust'&&blank(legacy))?{value:legacy}:{}),...input.financeEditor?.expenses?.[id]};
}
export function applyFinanceAmount(setting,baseline=null,budget=null,revenue=null){
 const {mode,value}=setting||{};
 if(!finite(value)||value<0||(mode==='comparablePct'?value>200:mode!=='amount'&&value>100))return null;
 const basis={comparablePct:baseline,budgetPct:budget,revenuePct:revenue}[mode];
 const amount=mode==='amount'?value:finite(basis)?basis*(value/100):null;
 return finite(amount)?amount:null;
}
export function revisionStats(values){
 const x=values.filter(finite).sort((a,b)=>a-b),n=x.length;
 const q=p=>{const k=(n-1)*p,i=Math.floor(k);return x[i]+(x[Math.min(i+1,n-1)]-x[i])*(k-i)};
 if(!n)return {n:0,min:null,q1:null,median:null,mean:null,q3:null,max:null,iqr:null,whiskerLow:null,whiskerHigh:null,outliers:[],showBox:false,status:'비교사례 없음'};
 const q1=q(.25),median=q(.5),q3=q(.75),iqr=q3-q1,inside=x.filter(v=>v>=q1-1.5*iqr&&v<=q3+1.5*iqr);
 return {n,min:x[0],q1,median,mean:x.reduce((a,b)=>a+b/n,0),q3,max:x[n-1],iqr,whiskerLow:inside[0],whiskerHigh:inside.at(-1),outliers:x.filter(v=>v<inside[0]||v>inside.at(-1)),showBox:n>=5,status:n<5?'사례 부족':x[0]===x.at(-1)?'동일 금액 관측':'산출 완료'};
}
export function integerUnits(capacity,area){
 if(!finite(capacity)||capacity<0||!positive(area))return {units:null,assigned:null,remainder:null};
 const tolerance=Math.max(1e-8,Math.abs(capacity)*1e-12),raw=capacity/area;if(!finite(raw)||raw>Number.MAX_SAFE_INTEGER)return {units:null,assigned:null,remainder:null};const rounded=Math.floor(raw+.5);
 const units=rounded*area>capacity+tolerance?Math.floor((capacity+tolerance)/area):rounded;
 if(!Number.isSafeInteger(units)||!finite(units*area))return {units:null,assigned:null,remainder:null};
 return {units,assigned:units*area,remainder:Math.max(0,capacity-units*area)};
}
export function manualDevelopment(input){
 const unique=new Map();for(const p of input.parcels||[])if(!unique.has(p.pnu))unique.set(p.pnu,p);
 const parcels=[...unique.values()],known=parcels.reduce((s,p)=>s+(positive(p.areaM2)?p.areaM2:0),0),missing=parcels.filter(p=>!positive(p.areaM2)).length,plan=input.unitPlan||[];
 let units=0,supply=0,farArea=0,missingPlan=false,missingFar=false;
 for(const r of plan){if(!Number.isInteger(r.units)||r.units<0||(r.units>0&&!positive(r.supplyAreaM2))){missingPlan=true;continue;}units+=r.units;supply+=r.units*(r.supplyAreaM2||0);if(r.units&&!finite(r.farAreaM2))missingFar=true;else farArea+=r.units*(r.farAreaM2||0);}
 const a=input.assumptions||{},limit=finite(a.farBaseAreaM2)&&a.farBaseAreaM2>=0&&finite(a.farPct)&&a.farPct>=0?a.farBaseAreaM2*a.farPct/100:null,planned=plan.length&&!missingPlan&&!missingFar?farArea:null;
 return {landAreaM2:parcels.length&&!missing?known:null,knownLandAreaM2:known,missingParcelCount:missing,parcelCount:parcels.length,supplyAreaM2:plan.length&&!missingPlan&&positive(supply)?supply:null,units:!missingPlan?units:null,farLimitAreaM2:limit,plannedFarAreaM2:planned,status:planned!==null&&limit!==null?(planned>limit+1e-6?'제약 위반':'사용자 가정'):'미확인'};
}
function sampleSignature(input,kind){
 const f=input?.comparisonFilters||{};
 return JSON.stringify([(kind==='revenue'?revenueComparisonIdentity:comparisonIdentity)(input||{}),(input?.comparables?.[kind+'Cases']||[]).map(r=>Object.fromEntries(Object.entries({...r,eligible:r.eligible!==false,exclusionReason:r.eligible===false?(r.exclusionReason||''):''}).filter(([k])=>!['baseEligible','baseExclusionReason','apiEligible','distanceKm'].includes(k)).sort(([a],[b])=>a.localeCompare(b)))),kind==='revenue'?[f.minSupplyM2,f.maxSupplyM2,f.search]:[f.jimok,f.landUse],kind==='land'?(input?.parcels||[]).map(p=>[p.pnu,p.areaM2,p.group]):null]);
}
export function acceptedComplexes(input,base){
 if(!base?.inputs||sampleSignature(input,'revenue')!==sampleSignature(base.inputs,'revenue'))return [];
 const revenue=base.results?.revenue||{};
 if(revenue.comparisonReason||/재조회|부분 수집/.test(revenue.status||''))return [];
 const cases=new Map((input.comparables?.revenueCases||[]).map(c=>[String(c.id),c]));
 return (revenue.eligibleComplexes||revenue.points||[]).filter(p=>positive(p.unitPriceWonM2)).map(p=>{
  const areas=(p.caseIds||[]).map(id=>cases.get(String(id))?.supplyAreaM2).filter(positive);
  return {...p,medianSupplyAreaM2:positive(p.medianSupplyAreaM2)?p.medianSupplyAreaM2:revisionStats(areas).median};
 }).filter(p=>positive(p.medianSupplyAreaM2));
}
export function linkedDevelopment(input,complexes=[]){
 const conf={...LINKED_DEFAULTS,...input.linkedScenario},fieldErrors=[];
 const err=(path,message)=>fieldErrors.push({section:'development',path,message});
 const unique=new Map();for(const [i,p] of (input.parcels||[]).entries()){const key=p.pnu||`missing-${i}`;if(!unique.has(key))unique.set(key,p)}const parcels=[...unique.values()],known=parcels.reduce((s,p)=>s+(positive(p.areaM2)?p.areaM2:0),0),missing=parcels.filter(p=>!positive(p.areaM2)).length;
 const areaPoints=complexes.map(p=>({id:p.id,label:p.label,valueM2:p.medianSupplyAreaM2,caseIds:p.caseIds})),areaStats=revisionStats(areaPoints.map(p=>p.valueM2));
 if(!['median','manual'].includes(conf.areaMode))err('linkedScenario.supplyAreaM2','호당 면적 적용 방식 확인 필요 → 지원하지 않는 방식입니다 → 중앙값 적용 또는 직접 입력을 선택하세요.');
 const A=parcels.length&&!missing?known:null,a=conf.areaMode==='median'?areaStats.median:conf.supplyAreaM2;
 if(!positive(A))err('parcels','대지면적 미확보 → 선택 필지의 확인 면적이 없습니다 → 02-A에서 필지와 양수 대장 면적을 확인하세요.');
 if(!positive(conf.farMaxPct))err('linkedScenario.farMaxPct',`최대 용적률 ${conf.farMaxPct??'미입력'}% → 양수 최대값이 필요합니다 → 분석할 최대 용적률을 입력하세요.`);
 if(!finite(conf.farDefaultPct)||conf.farDefaultPct<0||conf.farDefaultPct>conf.farMaxPct)err('linkedScenario.farDefaultPct',`기본 용적률 ${conf.farDefaultPct??'미입력'}% → 0~${conf.farMaxPct??'미입력'}% 범위를 벗어납니다 → 기본값 또는 최대값을 수정하세요.`);
 if(!finite(conf.farPct)||conf.farPct<0||conf.farPct>conf.farMaxPct)err('linkedScenario.farPct',`용적률 ${conf.farPct??'미입력'}% → 0~${conf.farMaxPct??'미입력'}% 범위가 필요합니다 → 현재 용적률 또는 최대값을 수정하세요.`);
 if(!positive(a))err('linkedScenario.supplyAreaM2',conf.areaMode==='median'?'호당 공급면적 기본값 미확보 → 적합 분양사례의 면적 중앙값이 없습니다 → 비교조건을 확인하거나 호당 면적을 직접 입력하세요.':'호당 공급면적 미입력 또는 0 이하 → 호수 계산에 양수 면적이 필요합니다 → 확인한 ㎡/호를 입력하세요.');
 let S=positive(A)&&finite(conf.farPct)&&conf.farPct>=0&&!fieldErrors.some(e=>e.path.startsWith('linkedScenario.far'))?A*(conf.farPct/100):null;if(S!==null&&!finite(S)){err('linkedScenario.farPct','용적률 계산 범위 초과 → 입력값이 너무 큽니다 → 대지면적과 용적률 단위를 확인하세요.');S=null}let counts=integerUnits(S,['median','manual'].includes(conf.areaMode)?a:null);
 if(S!==null&&positive(a)&&counts.units===null){err('linkedScenario.farPct','분양 호수 계산 범위 초과 → 면적 단위가 잘못됐을 수 있습니다 → 대지·호당 면적의 ㎡ 단위를 확인하세요.');S=null;counts={units:null,assigned:null,remainder:null}}
 return {linkedMode:true,landAreaM2:A,knownLandAreaM2:known,missingParcelCount:missing,parcelCount:parcels.length,capacitySupplyAreaM2:S,farLimitAreaM2:S,assignedSupplyAreaM2:counts.assigned,unassignedSupplyAreaM2:counts.remainder,supplyAreaM2:counts.assigned,units:counts.units,unitSupplyAreaM2:positive(a)?a:null,farAreaPerUnitM2:counts.units>0?S/counts.units:null,areaPoints,areaStats,fieldErrors,status:fieldErrors.length?'입력 확인 필요':counts.units===0?'1호 미만 · 분양수입 0원 시나리오':'간이 규모 가정 · 인허가 미확인'};
}
export function calculateBudget(input,revenueWon,landWon){
 const b={...BUDGET_DEFAULTS,...input.budgetAllocation},margin=input.assumptions?.targetMarginPct,fieldErrors=[];
 const trustType=b.trustType??'',trustAllowed=['','management','completion'].includes(trustType);
 const err=(path,message)=>fieldErrors.push({section:'budget',path,message});
 const validMargin=finite(margin)&&margin>=0&&margin<=99;
 if(!validMargin)err('assumptions.targetMarginPct','목표 수익률을 0~99% 범위로 입력하세요.');
 const requestedAllowable=finite(revenueWon)&&validMargin?revenueWon*(1-margin/100):null;
 const row=(id,label)=>{
  const setting=financeRowSetting(input,id),{mode,value}=setting;
  const valid=['amount','budgetPct','revenuePct'].includes(mode)&&finite(value)&&value>=0&&(mode==='amount'||value<=100);
  if(!valid)err('financeEditor.expenses.'+id+'.value',`${label}: 금액은 0 이상, 비율은 0~100%로 입력하세요.`);
  const amountWon=valid?applyFinanceAmount(setting,null,requestedAllowable,revenueWon):null;
  if(valid&&mode==='amount'&&amountWon===null)err('financeEditor.expenses.'+id+'.value',`${label}: 계산 가능한 금액 범위를 초과했습니다.`);
  return {id,label:label.replace(/^허용 /,''),...setting,pct:mode==='budgetPct'?value:null,amountWon,sourceStatus:mode==='amount'?'사용자 가정':'사용자 비율 가정'};
 };
 const allocationRows=BUDGET_ROWS.map(([id,label])=>row(id,label)),trust=row('trust','신탁보수');
 if(trustType==='distribution')err('budgetAllocation.trustType','분양관리신탁은 순수 아파트에 동일 요율을 적용할 수 없습니다. 적용 대상·보수 조건을 확인하세요.');
 else if(!trustAllowed)err('budgetAllocation.trustType','관리형 또는 책임준공관리형 신탁상품을 선택하세요.');
 if(!trustAllowed)trust.amountWon=null;
 const allRows=[...allocationRows,trust],ready=!fieldErrors.length&&finite(revenueWon)&&revenueWon>=0&&finite(landWon)&&landWon>=0&&allRows.every(r=>finite(r.value));
 const priority=expensePriorityBasis(revenueWon,landWon,validMargin?margin:null,allRows,ready),allowable=priority.allowableWon;
 if(priority.adjustmentError)err('financeEditor.expenses',priority.adjustmentError);
 for(const r of allRows)if(r.mode==='budgetPct')r.amountWon=applyFinanceAmount(r,null,allowable,revenueWon);
 if(!trustAllowed)trust.amountWon=null;
 const trustWon=trustAllowed?trust.amountWon:null;
 let knownAllocatedWon=allocationRows.reduce((s,r)=>s+(r.amountWon??0),0)+(landWon??0)+(trustWon??0);
 if(!finite(knownAllocatedWon)){knownAllocatedWon=null;err('financeEditor','금액 합계가 계산 범위를 초과했습니다. 입력 단위를 확인하세요.');}
 const complete=!fieldErrors.length&&knownAllocatedWon!==null&&allowable!==null&&finite(landWon)&&finite(trustWon)&&allocationRows.every(r=>finite(r.amountWon));
 const allocatedWon=complete?knownAllocatedWon:null,rawGap=complete?allowable-allocatedWon:null,tolerance=Math.max(1e-7,Number.EPSILON*Math.max(1,Math.abs(allowable??0),Math.abs(allocatedWon??0))*32),gap=rawGap!==null&&Math.abs(rawGap)<=tolerance?0:rawGap,profitWon=complete?revenueWon-allocatedWon:null;
 return {revenueWon,...priority,targetMarginPct:margin,landWon,trustWon,trustType,trustRatePct:trust.mode==='revenuePct'?trust.value:null,trustRow:trust,allocationRows,allocationPctTotal:allocationRows.every(r=>finite(r.pct))?allocationRows.reduce((s,r)=>s+r.pct,0):null,knownAllocatedWon,allocatedWon,profitWon,profitMarginPct:profitWon!==null&&revenueWon>0?profitWon/revenueWon*100:null,unallocatedWon:gap===null?null:Math.max(0,gap),overallocatedWon:gap===null?null:Math.max(0,-gap),status:priority.targetAdjustmentStatus==='infeasible'?'지출 비율 조합 확인 필요':!complete?'입력 확인 필요':priority.targetAdjustmentStatus==='zero-revenue'?'수입 0원 · 수익률 산정 불가':priority.targetAdjusted?'지출 설정 유지 · 목표 수익률 조정':'예산 배분 완료',complete,fieldErrors,note:'지출 입력 설정을 우선 유지한 허용 예산입니다. 독립 예상비용·현금흐름과 중복 합산하지 않습니다.'};
}
export function projectRevision(input,base,{preview=true,offline=false}={}){
 const old=base?.results||{},complexes=acceptedComplexes(input,base),enabled=input.linkedScenario?.enabled===true;
 let development=enabled?linkedDevelopment(input,complexes):manualDevelopment(input);
 const supply=development.supplyAreaM2,ac=input.assumptions||{},adj=ac.revenueAdjustmentPct??0,method=ac.revenueMethod==='mean'?'mean':'median';
 const validAdj=finite(adj)&&adj>-100;let points=complexes.map(p=>({...p,baseValueWon:finite(supply)&&supply>=0?p.unitPriceWonM2*supply:null,valueWon:finite(supply)&&supply>=0&&validAdj?p.unitPriceWonM2*supply*(1+adj/100):null}));const overflowRevenue=points.some(p=>(p.baseValueWon!==null&&!finite(p.baseValueWon))||(p.valueWon!==null&&!finite(p.valueWon)));if(overflowRevenue)points=points.map(p=>({...p,baseValueWon:null,valueWon:null}));const stats=revisionStats(points.map(p=>p.valueWon)),comparableWon=stats[method],revenueSetting=financeRowSetting(input,'revenue'),R=applyFinanceAmount(revenueSetting,comparableWon);
 const disc=ac.discountPct??0,sales=ac.finalSalesPct??100,full=finite(R)&&finite(disc)&&disc>=0&&disc<=100?R*(1-disc/100):null;
 const revenue={...old.revenue,points,eligibleComplexes:complexes,stats,baseStats:revisionStats(points.map(p=>p.baseValueWon)),unitPriceStats:revisionStats(complexes.map(p=>p.unitPriceWonM2)),supplyAreaStats:revisionStats(complexes.map(p=>p.medianSupplyAreaM2)),comparableWon,appliedSetting:revenueSetting,sourceStatus:revenueSetting.mode==='amount'?'사용자 가정':'비교사례 적용',representativeWon:R,potentialRevenueWon:R,fullNetRevenueWon:full,netRevenueWon:finite(full)&&finite(sales)&&sales>=0&&sales<=100?full*sales/100:null,status:revenueSetting.mode==='amount'&&finite(R)?'사용자 가정':!complexes.length?'비교사례 확인 필요':!finite(supply)?'공급면적 필요':!validAdj?'분양가격 보정 입력 오류':stats.status};
 const baselineLand=calculateLand(input),landSetting=financeRowSetting(input,'land'),land={...baselineLand,comparableWon:baselineLand.representativeWon,appliedSetting:landSetting,representativeWon:applyFinanceAmount(landSetting,baselineLand.representativeWon),sourceStatus:landSetting.mode==='amount'?'사용자 가정':'공개자료 기반 추정'};
 const budget=calculateBudget(input,R,land.representativeWon??null),fieldErrors=[...(enabled?development.fieldErrors||[]:[]),...budget.fieldErrors,...(baselineLand.fieldErrors||[])];
 for(const [id,setting] of [['revenue',revenueSetting],['land',landSetting]])if(!['amount','comparablePct'].includes(setting.mode)||!finite(setting.value)||setting.value<0||(setting.mode==='comparablePct'&&setting.value>200))fieldErrors.push({section:id,path:'financeEditor.'+id+'.value',message:'금액은 0 이상, 사례 적용 비율은 0~200%로 입력하세요.'});
 if(overflowRevenue)fieldErrors.push({section:'revenue',path:'linkedScenario.farPct',message:'분양수입 계산 범위 초과 → 면적·단가의 단위를 확인하고 용적률을 수정하세요.'});
 if(!validAdj)fieldErrors.push({section:'revenue',path:'assumptions.revenueAdjustmentPct',message:'분양가격 보정률 → -100%보다 커야 합니다 → 가격 보정값을 확인하세요.'});
 const pendingFinance={status:offline?'저장 자료 계산 · 금융 재검증 필요':'입력 변경 · Python 검증 대기',rows:[],summary:{},exit:{status:'재검증 필요',requiredPct:null,additionalRequiredPct:null}};
 const previousErrors=new Set((old.validation?.fieldErrors||[]).map(e=>e.message));
 const warnings=[...(base?.warnings||[]).filter(w=>!previousErrors.has(typeof w==='string'?w:w?.message)),...fieldErrors.map(e=>e.message)];
 return {...base,schemaVersion:1,analysisVersion:'pf-study-5',appVersion:'V5',landRulesVersion:LAND_RULE_VERSION,createdAt:base?.createdAt||new Date().toISOString(),name:input.project?.name||'미지정 사업',scenario:input.project?.scenario||'기준안',inputs:input,sources:input.sources||[],warnings,calculationStatus:offline?'저장 자료 기반 계산 · Python 검증 미실시':'화면 즉시 계산 · Python 검증 대기',results:{...old,development,revenue,land,budget,validation:{...old.validation,mode:'browser-preview',fieldErrors},...(preview?{cashflow:pendingFinance,kpis:{},okr:{},costs:{...old.costs,allowableWon:null,totalWon:null,gapWon:null,profitWon:null,marginPct:null,status:pendingFinance.status}}:{})}};
}
