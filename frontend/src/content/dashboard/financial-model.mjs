/** All currency is 억원; displayed/input rates are percentages. Pure, dependency-free. */
export const MODEL_NOTES = [
  '월 단위 신규사업 시나리오입니다. 과거 계약·수납 실적을 고정하는 운영 모델은 포함하지 않습니다.',
  '월초 차입, 월중 계약·수납 및 비용 발생, 월말 지급·원금상환을 가정합니다. 이자는 월초 잔액과 당월 인출액 전액에 연이율/12를 적용합니다.',
  '브릿지는 0개월에 인출하고 PF 개시월에 상환할 의무가 있다고 가정합니다. 본 PF는 개시월부터 만기 전월까지만 누적인출 한도 내에서 부족액을 인출하며, 상환한 금액의 약정한도는 복원하지 않는 비회전 구조입니다.',
  '운영비·미지급금·이자·수수료·브릿지 상환 후 남은 현금은 PF 원금을 상환합니다. 향후 공사비 유보계정·인출 선행조건·트랜치별 워터폴은 생략한 단순화입니다.',
  '대출원금과 자기자본 투입은 사업비가 아닙니다. 현금이 부족한 의무액은 미지급으로 남기며 자동으로 자금이 생기지 않습니다.',
  '헤드라인 이익률은 전량 판매 가정 잠재매출 기준입니다. 미분양은 수납으로 잡지 않으며 분석 종료 이후 미분양 보유·판매에 필요한 추가 금융비는 미포함입니다.',
  '판매수수료는 계약금액에 따라 현금비용을 계산하고, 전량판매 손익에는 미계약분 판매수수료 예산도 포함합니다.',
  '신탁보수는 입력 기준금액(공란이면 전량판매 잠재매출)×약정요율에 연장보수 총액을 합산합니다. 신탁기간 전체 보수이며 연이율이 아닙니다.',
  '차입형을 선택해도 신탁계정대 별도 모델이 생기지 않습니다. 해당 조달 구조의 금액·금리·상환조건을 별도 확정해야 하며 현재 비교는 입력한 금융조건의 시나리오입니다.',
  '만기 이후에도 미상환 원금에 일반 약정금리의 이자가 발생합니다. 별도 연체이율·차환·보증 실행·세후 손익은 모델링하지 않습니다.',
  '최대 미조달액은 지급기일이 지난 미지급 운영비·이자·수수료·도래 원금의 합계 최댓값입니다. 추가자금 투입시 실제 필요액은 금융비를 재계산해야 합니다.',
  '준공 지연은 공사기간·잔금 회수·월 운영비·금융비에 반영하고, 공사비 증액률은 본 도급 및 별도 공사에만 적용합니다.'
];

const REQUIRED = ['revenue','targetMargin','startDate','land','construction','separate','design','taxes','salesFeeRate','monthlyOpex','reserve','trustRate','trustExtension','initialCash','bridgeAmount','pfLimit','pfStart','completion','pfMaturity','salesStart','salesMonths','soldPct','depositPct','interimPct','balanceLagMonths','delayMonths','costIncreasePct'];
const NONNEGATIVE = ['land','construction','separate','design','taxes','salesFeeRate','monthlyOpex','reserve','trustRate','trustExtension','initialCash','bridgeAmount','bridgeRate','bridgeFeeRate','pfLimit','pfRate','pfFeeRate','trustBasis','costIncreasePct'];
const INTEGER = ['pfStart','completion','pfMaturity','salesStart','salesMonths','balanceLagMonths','delayMonths'];
const EPS = 1e-8;
const roundZero = x => Math.abs(x) < EPS ? 0 : x;

export function defaultAssumptions() {
  return {
    revenue:null,targetMargin:null,startDate:null,land:null,construction:null,separate:null,design:null,taxes:null,
    salesFeeRate:null,monthlyOpex:null,reserve:null,trustType:'managed',trustRate:null,trustBasis:null,
    trustExtension:null,initialCash:null,bridgeAmount:null,bridgeRate:null,bridgeFeeRate:null,pfLimit:null,
    pfRate:null,pfFeeRate:null,pfStart:null,completion:null,pfMaturity:null,salesStart:null,salesMonths:null,
    soldPct:null,depositPct:null,interimPct:null,balanceLagMonths:null,delayMonths:null,costIncreasePct:null
  };
}

export function exampleAssumptions() {
  // Entirely invented educational scenario. These values are not quotes or market benchmarks.
  return {...defaultAssumptions(),revenue:1000,targetMargin:15,startDate:'2026-10',land:230,construction:360,
    separate:25,design:20,taxes:25,salesFeeRate:2,monthlyOpex:0.7,reserve:15,trustType:'managed',trustRate:0.5,
    trustBasis:null,trustExtension:0,initialCash:100,bridgeAmount:160,bridgeRate:9,bridgeFeeRate:1,
    pfLimit:650,pfRate:7,pfFeeRate:1,pfStart:6,completion:30,pfMaturity:36,salesStart:8,salesMonths:18,
    soldPct:85,depositPct:10,interimPct:60,balanceLagMonths:1,delayMonths:0,costIncreasePct:0};
}

function normalize(input) {
  const a = defaultAssumptions();
  for (const key of Object.keys(a)) if (Object.prototype.hasOwnProperty.call(input,key)) a[key] = input[key];
  if (a.balanceLagMonths == null && input?.balanceLag != null) a.balanceLagMonths = input.balanceLag;
  for (const key of Object.keys(a)) if (typeof a[key] === 'string') a[key] = a[key].trim();
  for (const key of Object.keys(a)) if (!['trustType','startDate'].includes(key) && a[key] !== null && a[key] !== '') a[key] = Number(a[key]);
  for (const key of Object.keys(a)) if (a[key] === '') a[key] = null;
  return a;
}

function validate(a) {
  const missing = REQUIRED.filter(k => a[k] == null || (k !== 'startDate' && !Number.isFinite(a[k])));
  for (const [amount,rate,fee] of [['bridgeAmount','bridgeRate','bridgeFeeRate'],['pfLimit','pfRate','pfFeeRate']]) {
    if (a[amount] > 0) for (const k of [rate,fee]) if (!Number.isFinite(a[k])) missing.push(k);
  }
  const errors = [];
  for (const [k,v] of Object.entries(a)) if (!['trustType','startDate'].includes(k) && v !== null && !Number.isFinite(v)) errors.push(`${k}: 유한한 숫자가 필요합니다.`);
  if (a.startDate != null && !/^\d{4}-(0[1-9]|1[0-2])$/.test(a.startDate)) errors.push('startDate: YYYY-MM 형식이 필요합니다.');
  for (const k of NONNEGATIVE) if (Number.isFinite(a[k]) && a[k] < 0) errors.push(`${k}: 0 이상이어야 합니다.`);
  for (const k of INTEGER) if (Number.isFinite(a[k]) && (!Number.isInteger(a[k]) || a[k] < 0 || a[k] > 180)) errors.push(`${k}: 0~180 범위의 정수여야 합니다.`);
  if (Number.isFinite(a.revenue) && a.revenue <= 0) errors.push('revenue: 양수여야 합니다.');
  if (Number.isFinite(a.targetMargin) && (a.targetMargin < 0 || a.targetMargin >= 100)) errors.push('targetMargin: 0 이상 100 미만이어야 합니다.');
  for (const k of ['soldPct','depositPct','interimPct']) if (Number.isFinite(a[k]) && (a[k]<0 || a[k]>100)) errors.push(`${k}: 0~100%이어야 합니다.`);
  if (a.depositPct+a.interimPct > 100) errors.push('계약금과 중도금 비율 합계는 100% 이하여야 합니다.');
  if (a.salesMonths !== null && a.salesMonths < 1) errors.push('salesMonths: 1개월 이상이어야 합니다.');
  if (a.completion !== null && a.pfStart !== null && a.completion < a.pfStart) errors.push('준공월은 PF 개시월 이후여야 합니다.');
  if (a.pfMaturity !== null && a.pfStart !== null && a.pfMaturity < a.pfStart) errors.push('PF 만기는 PF 개시월 이후여야 합니다.');
  if ((a.pfRate||0)/1200+(a.pfFeeRate||0)/100 >= 1) errors.push('PF 금리·인출수수료 조합을 확인하세요.');
  if (!['managed','completion','borrowed'].includes(a.trustType)) errors.push('신탁 종류가 올바르지 않습니다.');
  return {missing:[...new Set(missing)],errors};
}

function monthDate(start,offset) {
  const [year,month]=start.split('-').map(Number);
  const n=year*12+month-1+offset;
  return `${Math.floor(n/12)}-${String(n%12+1).padStart(2,'0')}`;
}

export function calculateModel(input={}) {
  const a = normalize(input);
  const {missing,errors}=validate(a);
  if (missing.length || errors.length) return {valid:false,missing,errors,warnings:[],assumptions:a,summary:null,months:[],reconciliation:null};
  const actualCompletion=a.completion+a.delayMonths;
  const lastSale=a.salesStart+a.salesMonths-1;
  const lastBalance=Math.max(actualCompletion,lastSale)+a.balanceLagMonths;
  const lastMonth=Math.max(lastBalance,actualCompletion,a.pfMaturity,a.pfStart);
  const n=lastMonth+1;
  const contract=Array(n).fill(0),receipts=Array(n).fill(0),baseCosts=Array(n).fill(0),trustCosts=Array(n).fill(0);
  const add=(arr,m,v)=>{arr[m]+=v;};
  const contractedRevenue=a.revenue*a.soldPct/100;
  for(let t=a.salesStart;t<=lastSale;t++) {
    const amount=contractedRevenue/a.salesMonths;
    add(contract,t,amount);add(receipts,t,amount*a.depositPct/100);
    const count=Math.max(0,actualCompletion-1-t);
    if(count>0) for(let m=t+1;m<=actualCompletion-1;m++) add(receipts,m,amount*a.interimPct/100/count);
    else add(receipts,t,amount*a.interimPct/100);
    add(receipts,Math.max(actualCompletion,t)+a.balanceLagMonths,amount*(100-a.depositPct-a.interimPct)/100);
  }
  const construction=a.construction*(1+a.costIncreasePct/100);
  const separate=a.separate*(1+a.costIncreasePct/100);
  add(baseCosts,0,a.land+a.design*0.2+a.taxes*0.5);
  add(baseCosts,a.pfStart,a.design*0.8+separate*0.3);
  for(let m=a.pfStart;m<=actualCompletion;m++) add(baseCosts,m,construction/(actualCompletion-a.pfStart+1));
  add(baseCosts,actualCompletion,separate*0.7+a.taxes*0.5+a.reserve);
  for(let m=0;m<n;m++) add(baseCosts,m,a.monthlyOpex+contract[m]*a.salesFeeRate/100);
  const trustBasis=a.trustBasis==null?a.revenue:a.trustBasis;
  const trustFee=trustBasis*a.trustRate/100+a.trustExtension;
  add(trustCosts,a.pfStart,trustFee*0.3);add(trustCosts,actualCompletion,trustFee*0.4);add(trustCosts,lastMonth,trustFee*0.3);

  let cash=0,bridge=0,pf=0,unpaidOperating=0,unpaidBridgeInterest=0,unpaidPfInterest=0,unpaidBridgeFees=0,unpaidPfFees=0;
  let peakUnfunded=0,peakUnfundedMonth=null,pfPeak=0,pfMaturityShortfall=0,bridgeAtPfMaturity=0,pfDrawTotal=0;
  let totalBridgeInterest=0,totalPfInterest=0,interestPaid=0,totalFees=0,bridgeInterestPaid=0,pfInterestPaid=0,feesPaid=0;
  const months=[];
  for(let m=0;m<n;m++) {
    const openingCash=cash,openingBridge=bridge,openingPf=pf;
    const equityIn=m===0?a.initialCash:0,bridgeDraw=m===0?a.bridgeAmount:0;
    const bridgeFee=m===0?a.bridgeAmount*(a.bridgeFeeRate||0)/100:0;
    bridge+=bridgeDraw;
    const bridgeInterest=bridge*(a.bridgeRate||0)/1200;
    const operatingCost=baseCosts[m]+trustCosts[m];
    cash+=equityIn+bridgeDraw+receipts[m];
    unpaidOperating+=operatingCost;
    unpaidBridgeInterest+=bridgeInterest;
    unpaidBridgeFees+=bridgeFee;
    let pfDraw=0;
    const pfMonthlyRate=(a.pfRate||0)/1200,pfDrawFee=(a.pfFeeRate||0)/100;
    if(m>=a.pfStart && m<a.pfMaturity) {
      const currentNeeds=unpaidOperating+unpaidBridgeInterest+unpaidPfInterest+unpaidBridgeFees+unpaidPfFees+pf*pfMonthlyRate+bridge;
      const needed=Math.max(0,(currentNeeds-cash)/(1-pfMonthlyRate-pfDrawFee));
      pfDraw=Math.min(Math.max(0,a.pfLimit-pfDrawTotal),needed);
      cash+=pfDraw;pf+=pfDraw;pfDrawTotal+=pfDraw;
    }
    const pfInterest=pf*pfMonthlyRate,pfFee=pfDraw*pfDrawFee;
    unpaidPfInterest+=pfInterest;unpaidPfFees+=pfFee;
    pfPeak=Math.max(pfPeak,pf);
    const pay=(outstanding)=>Math.min(Math.max(0,cash),Math.max(0,outstanding));
    let paid=pay(unpaidOperating);cash-=paid;unpaidOperating-=paid;const operatingPaid=paid;
    paid=pay(unpaidBridgeInterest);cash-=paid;unpaidBridgeInterest-=paid;const bridgeInterestPayment=paid;
    paid=pay(unpaidPfInterest);cash-=paid;unpaidPfInterest-=paid;const pfInterestPayment=paid;
    paid=pay(unpaidBridgeFees);cash-=paid;unpaidBridgeFees-=paid;const bridgeFeePayment=paid;
    paid=pay(unpaidPfFees);cash-=paid;unpaidPfFees-=paid;const pfFeePayment=paid;
    let bridgePrincipalPaid=0,pfPrincipalPaid=0;
    if(m>=a.pfStart) {bridgePrincipalPaid=pay(bridge);cash-=bridgePrincipalPaid;bridge-=bridgePrincipalPaid;}
    if(m>=a.pfStart) {pfPrincipalPaid=pay(pf);cash-=pfPrincipalPaid;pf-=pfPrincipalPaid;}
    cash=roundZero(cash);bridge=roundZero(bridge);pf=roundZero(pf);
    const unfunded=roundZero(unpaidOperating+unpaidBridgeInterest+unpaidPfInterest+unpaidBridgeFees+unpaidPfFees+(m>=a.pfStart?bridge:0)+(m>=a.pfMaturity?pf:0));
    if(unfunded>peakUnfunded+EPS){peakUnfunded=unfunded;peakUnfundedMonth=monthDate(a.startDate,m);}
    if(m===a.pfMaturity){pfMaturityShortfall=pf+unpaidPfInterest+unpaidPfFees;bridgeAtPfMaturity=bridge+unpaidBridgeInterest+unpaidBridgeFees;}
    const outflows=operatingPaid+bridgeInterestPayment+pfInterestPayment+bridgeFeePayment+pfFeePayment+bridgePrincipalPaid+pfPrincipalPaid;
    const inflows=equityIn+bridgeDraw+pfDraw+receipts[m];
    const reconciliationError=roundZero(openingCash+inflows-outflows-cash);
    totalBridgeInterest+=bridgeInterest;totalPfInterest+=pfInterest;totalFees+=bridgeFee+pfFee;
    interestPaid+=bridgeInterestPayment+pfInterestPayment;bridgeInterestPaid+=bridgeInterestPayment;pfInterestPaid+=pfInterestPayment;feesPaid+=bridgeFeePayment+pfFeePayment;
    months.push({index:m,date:monthDate(a.startDate,m),contractValue:contract[m],receipts:receipts[m],operatingCost,baseOperatingCost:baseCosts[m],trustCost:trustCosts[m],operatingPaid,
      bridgeInterest,pfInterest,interestAccrued:bridgeInterest+pfInterest,interestPaid:bridgeInterestPayment+pfInterestPayment,fees:bridgeFee+pfFee,feesPaid:bridgeFeePayment+pfFeePayment,
      equityIn,bridgeDraw,pfDraw,pfDrawTotal,pfUndrawnCommitment:Math.max(0,a.pfLimit-pfDrawTotal),bridgePrincipalPaid,pfPrincipalPaid,openingBridge,openingPf,bridgeBalance:bridge,pfBalance:pf,openingCash,cash,
      inflows,outflows,unfunded,monthlyGap:unfunded-(months.length?months[months.length-1].unfunded:0),unpaidOperating,unpaidBridgeInterest,unpaidPfInterest,unpaidBridgeFees,unpaidPfFees,reconciliationError});
  }
  const cashOperatingCost=baseCosts.reduce((s,v)=>s+v,0)+trustFee;
  const unsoldSellingCost=a.revenue*(1-a.soldPct/100)*a.salesFeeRate/100;
  const interestAccrued=totalBridgeInterest+totalPfInterest;
  const totalCost=cashOperatingCost+interestAccrued+totalFees+unsoldSellingCost;
  const profit=a.revenue-totalCost,margin=profit/a.revenue*100;
  const targetProfit=a.revenue*a.targetMargin/100,allowableCost=a.revenue-targetProfit;
  const warnings=[];
  if(a.soldPct<100)warnings.push('전량 판매 가정 이익률입니다. 미분양분의 분석 종료 후 추가 금융비·운영비는 별도 검토해야 합니다.');
  if(a.trustType==='borrowed')warnings.push('차입형 신탁계정대는 별도 구현되지 않았습니다. 입력한 대출조건에 한한 시나리오입니다.');
  if(actualCompletion>a.pfMaturity)warnings.push('준공이 PF 만기 이후입니다. 만기 이전 잔금 회수와 차환 조건을 확인하세요.');
  if(peakUnfunded>EPS)warnings.push('미조달 의무액이 발생합니다. 지급계획이 전액 이행되는 현금흐름이 아닙니다.');
  const summary={revenue:a.revenue,potentialRevenue:a.revenue,contractedRevenue,inventoryPotential:a.revenue-contractedRevenue,receipts:receipts.reduce((s,v)=>s+v,0),
    totalCost,profit,margin,targetProfit,allowableCost,costHeadroom:allowableCost-totalCost,construction,separate,trustBasis,trustFee,
    interestAccrued,interestPaid,bridgeInterestAccrued:totalBridgeInterest,pfInterestAccrued:totalPfInterest,bridgeInterestPaid,pfInterestPaid,
    lenderFeeIncome:totalFees,lenderFeesPaid:feesPaid,lenderGrossIncome:interestAccrued+totalFees,lenderCashIncome:interestPaid+feesPaid,
    pfPeak,pfDrawTotal,pfMaturityShortfall:roundZero(pfMaturityShortfall),bridgeAtPfMaturity:roundZero(bridgeAtPfMaturity),bridgeRemaining:bridge,pfRemaining:pf,
    peakUnfunded,peakUnfundedMonth,requiredAdditionalEquity:peakUnfunded,endingCash:cash,unpaidOperating,actualCompletion,lastMonth,unsoldSellingCost,
    maturitySalesPct:contract.slice(0,a.pfMaturity+1).reduce((s,v)=>s+v,0)/a.revenue*100,
    targetMet:margin+EPS>=a.targetMargin,pfRepayable:pfMaturityShortfall<EPS,
    liquidityClear:peakUnfunded<EPS};
  return {valid:true,missing:[],errors:[],warnings,assumptions:a,summary,months,reconciliation:{maxCashError:Math.max(...months.map(m=>Math.abs(m.reconciliationError))),
    bridgeError:roundZero(a.bridgeAmount-months.reduce((s,m)=>s+m.bridgePrincipalPaid,0)-bridge),
    pfError:roundZero(months.reduce((s,m)=>s+m.pfDraw-m.pfPrincipalPaid,0)-pf),receiptError:roundZero(summary.receipts-contractedRevenue)}};
}

export function solveConstructionCap(input={}) {
  const validation=calculateModel(input);
  if(!validation.valid)return {status:'missing',constructionCap:null,marginAtCap:null,missing:validation.missing,errors:validation.errors};
  const a=validation.assumptions;
  const zero=calculateModel({...a,construction:0});
  if(zero.summary.margin<a.targetMargin-EPS)return {status:'unattainable',constructionCap:null,marginAtCap:zero.summary.margin,reason:'공사비를 0으로 두어도 다른 비용이 허용 총사업비를 초과합니다.'};
  let lo=0,hi=Math.max(a.revenue,a.construction,1);
  for(let i=0;i<20&&calculateModel({...a,construction:hi}).summary.margin>=a.targetMargin;i++)hi*=2;
  for(let i=0;i<50;i++) {const mid=(lo+hi)/2;const model=calculateModel({...a,construction:mid});if(model.summary.margin>=a.targetMargin)lo=mid;else hi=mid;}
  const result=calculateModel({...a,construction:lo});
  return {status:'solved',constructionCap:lo,effectiveConstructionCap:result.summary.construction,marginAtCap:result.summary.margin,
    liquidityClear:result.summary.liquidityClear,peakUnfunded:result.summary.peakUnfunded,note:'목표 이익률 기준 본 도급비 상한입니다. 실행 가능한 견적·자금조달 한도를 뜻하지 않습니다.'};
}

export function calculateExit(input={}) {
  const validation=calculateModel(input);
  if(!validation.valid)return {status:'missing',exitPct:null,additionalPct:null,missing:validation.missing,errors:validation.errors};
  const a=validation.assumptions;
  const isClear=m=>m.summary.pfMaturityShortfall<EPS && m.summary.bridgeAtPfMaturity<EPS && m.months[a.pfMaturity].unfunded<EPS;
  const at0=calculateModel({...a,soldPct:0});
  // Increased contracts can create pre-maturity selling fees while balances arrive later.
  // A global monotonicity assumption is therefore unsafe. Scan to the first feasible band.
  const searchStepPct=0.1;
  let low=0,high=isClear(at0)?0:null;
  if(high===null)for(let step=1;step<=1000;step++){
    const pct=step*searchStepPct;
    if(isClear(calculateModel({...a,soldPct:pct}))){low=(step-1)*searchStepPct;high=pct;break;}
  }
  const at100=calculateModel({...a,soldPct:100});
  if(high===null)return {status:'unattainable',exitPct:null,additionalPct:null,searchStepPct,maturityShortfallAt100:at100.months[a.pfMaturity].unfunded,
    pfShortfallAt100:at100.summary.pfMaturityShortfall,reason:'동일한 판매·수납 경로를 0~100%에서 0.1%p 간격으로 탐색했으나 만기 지급·상환 가능 구간이 없으며, 100% 계약해도 부족액이 남습니다.'};
  if(high>0)for(let i=0;i<35;i++){const mid=(low+high)/2;if(isClear(calculateModel({...a,soldPct:mid})))high=mid;else low=mid;}
  const solved=calculateModel({...a,soldPct:high});
  const exitPct=solved.summary.maturitySalesPct;
  return {status:'solved',exitPct,requiredTotalTakeupPct:high,additionalPct:Math.max(0,exitPct-validation.summary.maturitySalesPct),
    expectedMaturitySalesPct:validation.summary.maturitySalesPct,headroomPct:validation.summary.maturitySalesPct-exitPct,searchStepPct,maturityShortfallAt100:at100.months[a.pfMaturity].unfunded,
    note:'동일한 주택형 구성·균등 월별 계약·수납 경로를 0.1%p 간격 탐색한 뒤 첫 가능구간을 정밀화한 추정치입니다. 더 좁은 가능구간은 놓칠 수 있으며 과거 실적은 고정하지 않습니다. 판매수수료 선지급으로 분양률 증가가 만기 상환능력을 항상 높이지는 않습니다.'};
}
