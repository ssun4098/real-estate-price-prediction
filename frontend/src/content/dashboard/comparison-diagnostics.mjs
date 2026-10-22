const finite=Number.isFinite;
const failed=value=>/fail|partial|실패|일부|미완료|error/i.test(String(value||''));

function supplyReason(input,result,development){
 // Browser previews keep errors on development; Python keeps them on the
 // linked scenario and validation results. Use those causes before guessing.
 const errors=[...(development.fieldErrors||[]),...(result.results?.linkedScenario?.fieldErrors||[]),...(result.results?.validation?.fieldErrors||[])]
  .filter(error=>/^(parcels(?:\.|$)|unitPlan(?:\.|\[|$)|linkedScenario\.|assumptions\.far)/.test(error.path||''));
 const messages=[...new Set(errors.map(error=>error.message).filter(Boolean))];
 if(messages.length)return messages.join(' / ');
 const linked=input.linkedScenario?.enabled===true||development.linkedMode===true;
 if(development.supplyAreaM2===0&&development.units===0&&finite(development.unitSupplyAreaM2)&&development.unitSupplyAreaM2>0&&finite(development.capacitySupplyAreaM2)&&development.capacitySupplyAreaM2>=0)
  return '현재 계획은 1호 미만으로 배정 공급면적이 0㎡입니다. 분양을 계획한다면 용적률·대지면적·호당 공급면적을 검토하세요.';
 if(linked&&(input.linkedScenario?.areaMode??'median')==='median'&&development.areaStats?.n===0&&!(finite(development.unitSupplyAreaM2)&&development.unitSupplyAreaM2>0))
  return '적합 분양사례의 호당 면적 중앙값이 없어 공급계획도 미산출입니다. 사례를 다시 조회하거나 확인한 호당 면적을 직접 입력하세요.';
 return linked?'개발규모 계산이 완료되지 않았습니다. 대지면적·용적률·호당 공급면적의 검증 상태를 확인하세요.':'분양 호수와 호당 공급면적을 입력해야 사례 단가를 총 분양수입으로 환산할 수 있습니다.';
}

// Explain independent blockers together; missing coordinates are not zero sales.
export function revenueDiagnostics(input={},result={}){
 const revenue=result.results?.revenue||{},development=result.results?.development||{};
 if(finite(revenue.representativeWon))return [];
 const rows=input.comparables?.revenueCases||[],source=[...(input.sources||[])].reverse().find(s=>s.id==='applyhome'),out=[];
 const scope=source?.queryScope||input.comparables?.query?.scope||input.comparisonFilters?.scope;
 if(!source)out.push({code:'query',message:input.parcels?.length?'현재 선택 필지의 실시간 분양자료를 조회해 주세요. 저장본에는 분양 위치 자료가 포함되지 않습니다.':'개발 대상 필지를 선택한 뒤 분양자료를 조회해 주세요.',action:'조회 조건 확인',target:'live-conditions'});
 else if(failed(source.collectionStatus||source.status))out.push({code:'collection',message:'분양자료 조회가 실패했거나 일부만 수집됐습니다. 실패 구간을 확인한 뒤 다시 조회하세요.',action:'수집 근거 보기',target:'live-evidence'});
 else if(scope==='dong'&&!rows.length&&(source.queriedBasicCount??source.basicCount)===0){
  const dong=input.comparables?.query?.dong||input.comparisonFilters?.dong||'선택 법정동';
  out.push({code:'dong-empty',message:`같은 법정동(${dong})의 해당 기간 원문 검색 공고가 0건입니다. 주변 분양이 없다는 뜻은 아닙니다. 사업·조회 조건에서 분양 범위를 반경으로 변경할 수 있으며 토지 조회 범위는 유지됩니다.`,action:'사업·조회 조건에서 분양 범위 변경',target:'live-conditions'});
 }
 else if(scope==='radius'&&source.withinRadiusCount===0){
  const located=source.locatedCount,unresolved=source.unresolvedLocationCount;
  out.push({code:'radius',message:`위치 일치가 확인된 ${finite(located)?located:'미확인'}건 중 반경 내 공고는 0건입니다.${unresolved>0?` 위치 미검증 ${unresolved}건은 포함을 보류했습니다.`:''} 주변 분양 자체가 없다는 뜻은 아닙니다.`,action:'공고별 위치 근거 보기',target:'live-compare'});
 }else if(!rows.some(r=>r.eligible!==false))out.push({code:'cases',message:rows.length?'수집 자료가 현재 포함 조건을 통과하지 못했습니다. 제외 사유를 확인하세요.':'현재 조건에 해당하는 가격·면적 자료를 확보하지 못했습니다.',action:'사례 포함·제외 보기',target:'live-compare'});
 if(!(finite(development.supplyAreaM2)&&development.supplyAreaM2>0))out.push({code:'supply',message:supplyReason(input,result,development),action:'개발규모 설정',target:'live-development'});
 if(!out.length)out.push({code:'validation',message:revenue.comparisonReason||revenue.status||'분양가격·면적·입력 검증 상태를 확인하세요.',action:'계산 근거 보기',target:'live-evidence'});
 return out;
}

export function landDiagnostics(input={},result={}){
 const land=result.results?.land||{},rows=input.comparables?.landCases||[];
 const source=[...(input.sources||[])].reverse().find(s=>s.id==='land');
 const blockers=[...new Set([land.comparisonReason,...(land.parcelProfiles||[]).flatMap(p=>p.reasons||[])].filter(Boolean))];
 return {rawCount:source?.rawCount??rows.length,includedCount:(land.caseDecisions||rows).filter(r=>r.eligible!==false||(r.fallbackGroupIds||[]).length>0).length,
  collectedMonths:source?.collectedMonths?.length??null,requestedMonths:source?.requestedMonths?.length??null,
  status:source?.collectionStatus||input.comparables?.landCollectionStatus||'조회 전',blockers,
  mixed:blockers.some(reason=>reason.includes('혼합 용도지역'))};
}
