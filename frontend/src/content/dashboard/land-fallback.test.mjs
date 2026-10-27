import test from 'node:test';
import assert from 'node:assert/strict';
import {calculateLand,LAND_RULE_VERSION} from './land-comparison.mjs';
import {classifyZone,classifyJimok} from './land-classification.mjs';
import {boundaryAttributeBasis} from './boundary-allocation.mjs';
import {boundaryEvidenceChecksum,BOUNDARY_BINDING_ALGORITHM} from './boundary-binding.mjs';

const pnu='4136025321107100000',geometry={type:'Polygon',coordinates:[[[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]]};
function parcel(zoneName='제1종일반주거지역',jimok='대',id=pnu){
 const zone=classifyZone(zoneName),category=classifyJimok(jimok),row={pnu:id,areaM2:100,attributes:{landRegister:{status:'success',rows:[{pnu:id,lndpclAr:100,lndcgrCodeNm:jimok,lndcgrCode:category.code}]},landUse:{status:'success',rows:[{pnu:id,prposAreaDstrcCode:zone.code,prposAreaDstrcCodeNm:zoneName,cnflcAt:'1'}]}}};
 const layers=['LT_C_UQ111','LT_C_UQ112','LT_C_UQ113','LT_C_UQ114'];
 const evidence={version:'boundary-overlay-v1',pnu:id,status:'ready',reasons:[],source:{complete:true,queriedAt:'2026-10-10T00:00:00Z',crs:'EPSG:4326',parcelLayer:'LP_PA_CBND_BUBUN',zoningLayers:layers,pages:['LP_PA_CBND_BUBUN',...layers].map((layer,i)=>({layer,complete:true,totalCount:i<2?1:0,rawCount:i<2?1:0,uniqueCount:i<2?1:0,pageCount:1}))},parcelGeometry:geometry,parcelFeature:{geometry,properties:{pnu:id}},sourceFeatures:[{geometry,sourceLayer:'LT_C_UQ111'}],attributeBasis:boundaryAttributeBasis(row),registerAreaM2:100,parcelGeometryAreaM2:90,gapAreaM2:0,overlapAreaM2:0,coverageRatio:1,parts:[{zoneName,zoneCode:zone.code,zoneMatchKey:zone.matchKey,geometry,geometryAreaM2:90,ratio:1,allocatedAreaM2:100}]};
 evidence.evidenceBinding={algorithm:BOUNDARY_BINDING_ALGORITHM,value:boundaryEvidenceChecksum(evidence)};row.boundaryAllocation=evidence;return row;
}
const trade=(id,unit=1e6,patch={})=>({id,areaM2:100,priceManwon:unit/100,date:'2026-01-01',landUse:'자연녹지지역',jimok:'전',sourceEligible:true,...patch});
const fixture=(cases,extra={})=>({project:{asOf:'2026-10-11'},parcels:[parcel()],assumptions:{landMethod:'median'},comparables:{landCases:cases},...extra});

test('empty target borrows the pooled transaction median from all eligible other groups, never group medians',()=>{
 const input=fixture([trade('one',1e6),trade('two',2e6),trade('three',3e6),trade('four',100e6,{landUse:'일반상업지역',jimok:'대'})]),original=structuredClone(input),land=calculateLand(input),group=land.groups[0];
 assert.equal(land.representativeWon,250e6);assert.equal(group.representativeUnitPriceWonM2,2.5e6);assert.equal(group.points.length,0);assert.equal(group.stats.n,0);assert.equal(group.unitPriceStats.n,0);assert.equal(group.unitPriceStats.median,null);
 assert.equal(group.fallback.reason,'동일 그룹 비교사례 없음 · 중앙값 대체');assert.equal(group.fallback.sourceCaseCount,4);assert.equal(group.fallback.sourceGroupCount,2);assert.equal(land.fallback.parcelCount,1);assert.equal(land.fallback.sourceCaseCount,4);
 assert.equal(land.referenceGroups[0].points.length,0);assert.equal(land.referenceGroups[0].stats.n,0);assert.equal(land.referenceGroups[0].representativeUnitPriceWonM2,2.5e6);assert.deepEqual(land.referenceGroups[0].fallback,group.fallback);
 assert.equal(land.parcelAssignments[0].appliedUnitPriceWonM2,2.5e6);assert.equal(land.boundaryParts[0].pricingStatus,group.fallback.reason);assert.equal(land.completeness.complete,true);
 assert.ok(land.caseDecisions.every(row=>!row.eligible&&row.fallbackEligible&&row.classificationBasis.fallbackUsed));assert.deepEqual(land.caseDecisions[0].fallbackGroupIds,[group.id]);assert.equal(land.ruleVersion,LAND_RULE_VERSION);assert.deepEqual(input,original);
});

test('direct cases retain the selected representative method while fallback is always median and adjustment applies once',()=>{
 const direct=[trade('direct-1',1e6,{landUse:'제1종일반주거지역',jimok:'대'}),trade('direct-2',2e6,{landUse:'제1종일반주거지역',jimok:'대'}),trade('direct-3',100e6,{landUse:'제1종일반주거지역',jimok:'대'})];
 const input=fixture(direct,{parcels:[parcel(),parcel('일반상업지역','대','4136025321107100001')],assumptions:{landMethod:'mean',landAdjustmentPct:10}}),land=calculateLand(input),[matched,borrowed]=land.groups;
 assert.equal(matched.fallback.used,false);assert.equal(matched.stats.n,3);assert.ok(Math.abs(matched.representativeUnitPriceWonM2-103e6/3)<1e-7);
 assert.equal(borrowed.fallback.used,true);assert.equal(borrowed.representativeUnitPriceWonM2,2e6);assert.ok(Math.abs(borrowed.representativeWon-220e6)<1e-6);assert.ok(Math.abs(land.parcelAssignments[1].appliedUnitPriceWonM2-2.2e6)<1e-7);
 assert.deepEqual(land.fallback.groupIds,[borrowed.id]);assert.equal(land.fallback.parcelCount,1);
});

test('cancelled, shared, manual, bad price, invalid classification and source-excluded cases never become donors',()=>{
 const patches=[{cancelled:true},{cancellationDate:'2026-02-01'},{shareTrade:true},{shareDealingType:'지분'},{userExcluded:true},{manualExclusion:true},{sourceEligible:false},{priceManwon:0},{areaM2:0},{priceManwon:Number.MAX_VALUE},{date:'2030-01-01'},{landUse:'주거지역'},{landUse:'제1종일반주거지역',landUseCode:'UQA220'},{jimok:'대',jimokCode:'01'}];
 const land=calculateLand(fixture([trade('valid',5e6),...patches.map((patch,i)=>trade(`excluded-${i}`,99e6,patch)),trade('valid',99e6)]));
 assert.equal(land.representativeWon,500e6);assert.deepEqual(land.groups[0].fallback.sourceCaseIds,['valid']);assert.equal(land.fallback.sourceCaseCount,1);assert.ok(land.caseDecisions.slice(1).every(row=>!row.fallbackEligible&&!row.classificationBasis.fallbackUsed));
});

test('missing donors, incomplete collection, stale scope and invalid boundary still hold',()=>{
 for(const cases of [[],[trade('cancelled',1e6,{cancelled:true})]])assert.equal(calculateLand(fixture(cases)).representativeWon,null);
 const partial=fixture([trade('valid')]);partial.comparables.landCollectionStatus='partial';assert.equal(calculateLand(partial).representativeWon,null);assert.equal(calculateLand(partial).fallback.used,false);
 const stale=fixture([trade('valid')]);stale.comparisonFilters={sgg:'11110',dong:'다른동',start:'2026-01',end:'2026-09'};assert.equal(calculateLand(stale).representativeWon,null);assert.equal(calculateLand(stale).fallback.used,false);
 const boundary=fixture([trade('valid')]);delete boundary.parcels[0].boundaryAllocation;const land=calculateLand(boundary);assert.equal(land.representativeWon,null);assert.equal(land.fallback.used,false);assert.equal(land.referenceGroups[0].fallback.used,false);
});

test('current region, date window and manual category filters also apply to donor groups',()=>{
 const input=fixture([trade('valid',3e6,{sggCode:'41360',dong:'장상동'}),trade('other-dong',99e6,{sggCode:'41360',dong:'다른동'}),trade('old',99e6,{sggCode:'41360',dong:'장상동',date:'2025-01-01'}),trade('future',99e6,{sggCode:'41360',dong:'장상동',date:'2026-10-01'})]);
 input.parcels[0].dong='장상동';input.comparisonFilters={sgg:'41360',dong:'장상동',start:'2026-01',end:'2026-09',landScope:'dong'};input.comparables.landQuery={...input.comparisonFilters,collectionStatus:'complete'};
 const land=calculateLand(input);assert.equal(land.representativeWon,300e6);assert.deepEqual(land.groups[0].fallback.sourceCaseIds,['valid']);
 input.comparisonFilters.jimok='대';assert.equal(calculateLand(input).representativeWon,null);
});
