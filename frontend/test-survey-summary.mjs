import test from 'node:test';
import assert from 'node:assert/strict';
import {buildingSummary,designationSummary,designationComposition} from './src/content/dashboard/survey-summary.mjs';

const pnu='4136025321107100000';
const parcel=(rows,other={})=>({pnu,attributes:{buildings:{status:'success',rows}},...other});
const building=(id,floors,other={})=>({buldIdntfcNo:id,groundFloorCo:floors,...other});
test('three buildings on one parcel form 8-floor 2/3 and 5-floor 1/3 composition',()=>{
 const result=buildingSummary([parcel([building('A',8),building('B',8),building('C',5)])]);
 assert.equal(result.knownCount,3);assert.deepEqual(result.distribution.map(r=>[r.label,r.count]),[['5층',1],['8층',2]]);
 assert.equal((result.distribution[1].share*100).toFixed(1),'66.7');
});
test('building labels distinguish apartment blocks and preserve their full source identifier',()=>{
 const result=buildingSummary([parcel([building('11101100203301',18,{buldNm:'진접 하우스토리아파트',buldDongNm:'106'}),building('11101100202755',20,{buldNm:'진접 하우스토리아파트',buldDongNm:'108'}),building('11101100203084',2,{buldNm:'진접 하우스토리아파트'})])]);
 assert.match(result.buildings[0].label,/진접 하우스토리아파트 · 106동$/);assert.match(result.buildings[1].label,/108동$/);
 assert.match(result.buildings[2].label,/식별자 …00203084$/);assert.equal(result.buildings[0].identifier,'11101100203301');assert.equal(result.buildings[0].identifierType,'buldIdntfcNo');
 assert.equal(new Set(result.buildings.map(b=>b.label)).size,3);
});
test('duplicate source IDs across selected parcels count as one building; aliases reconcile',()=>{
 const one=parcel([building('A',8,{gisIdntfcNo:'GIS-A'}),building('B',5)]);
 const two=parcel([{gisIdntfcNo:'GIS-A',groundFloorCo:8}],{pnu:'4136025321107100001'});
 const result=buildingSummary([one,one,two]);assert.equal(result.knownCount,2);assert.equal(result.duplicateCount,1);
});
test('conflicting floors, blank floors and unidentified source rows stay out of denominator',()=>{
 const result=buildingSummary([parcel([building('A',8),building('A',5),building('B',''),building('C',null),{groundFloorCo:7},building('D',3.5),building('E',-1),building('F',6)])]);
 assert.equal(result.knownCount,1);assert.equal(result.conflictCount,1);assert.equal(result.unknownCount,4);assert.equal(result.unidentifiedCount,1);
 assert.equal(result.distribution[0].share,1);
});
test('wrong parcel building record is visible as excluded evidence and no-data remains no-data',()=>{
 const result=buildingSummary([parcel([building('A',8,{pnu:'4136025321107100001'})])]);
 assert.equal(result.mismatchedCount,1);assert.equal(result.knownCount,0);assert.deepEqual(result.slices,[]);
 assert.equal(buildingSummary([]).knownCount,0);
});
test('many floor categories use at most five slices and retain full distribution',()=>{
 const result=buildingSummary([parcel(Array.from({length:12},(_,i)=>building('B'+i,i+1)))]);
 assert.equal(result.distribution.length,12);assert.equal(result.slices.length,5);assert.equal(result.slices.at(-1).label,'기타');
 assert.equal(result.slices.reduce((sum,r)=>sum+r.count,0),12);assert.ok(Math.abs(result.slices.reduce((sum,r)=>sum+r.share,0)-1)<1e-12);
});
const zone=(name,code,relation='2',other={})=>({pnu,prposAreaDstrcCodeNm:name,prposAreaDstrcCode:code,cnflcAt:relation,cnflcAtNm:relation==='3'?'접함':'저촉',...other});
test('one parcel with three designations is 3 overlapping assignments, not 3 parcels',()=>{
 const p={pnu,attributes:{landUse:{status:'success',rows:[zone('제1종일반주거지역','UQA121'),zone('제1종일반주거지역','UQA121'),zone('제3종일반주거지역','UQA123'),zone('자연녹지지역','UQA430'),zone('일반상업지역','UQA220','3')]}}};
 const result=designationSummary([p,p],'zone');assert.equal(result.parcelCount,1);assert.equal(result.assignments,3);assert.equal(result.multipleParcels,1);
 assert.deepEqual(result.rows.map(r=>r.value),[1,1,1]);assert.equal(result.evidence.filter(r=>r.decision==='접함 · 집계 제외').length,1);
 assert.match(result.note,/선택 1필지.*포함·저촉 3건/);
});
test('duplicate management records retain originals but same parcel+designation counted once',()=>{
 const p={pnu,attributes:{landUse:{status:'success',rows:[zone('제1종일반주거지역','UQA121','2',{prposAreaDstrcNo:'A'}),zone('제1종일반주거지역','UQA121','2',{prposAreaDstrcNo:'B'})]}}};
 const result=designationSummary([p],'zone');assert.equal(result.assignments,1);assert.equal(result.evidence.length,2);assert.equal(result.evidence[1].decision,'같은 필지·같은 지정 중복');
});
test('failed planning source is not counted as no-regulation',()=>{
 const result=designationSummary([{pnu,attributes:{landUse:{status:'failed',rows:[zone('자연녹지지역','UQA430')]}}}],'zone');
 assert.equal(result.assignments,0);assert.equal(result.unknownParcels,1);assert.deepEqual(result.rows,[{label:'미확인',value:1}]);
});
test('district with no designation is 미지정, but a failed lookup stays 미확인',()=>{
 const none={pnu,attributes:{landUse:{status:'success',rows:[zone('자연녹지지역','UQA430')]}}};
 const failed={pnu:'4136025321107100001',attributes:{landUse:{status:'failed',rows:[]}}};
 const result=designationSummary([none,failed],'district');
 assert.deepEqual(result.rows,[{label:'미지정',value:1},{label:'미확인',value:1}]);
 assert.equal(result.unknownParcels,2);assert.equal(result.unspecifiedParcels,1);
 assert.match(result.note,/미확인 1필지 · 미지정 1필지/);
 // 용도지역·용도구역은 그대로 '미확인'
 assert.deepEqual(designationSummary([{pnu,attributes:{landUse:{status:'success',rows:[]}}}],'useArea').rows,[{label:'미확인',value:1}]);
});
test('district plan area belongs to useArea, not district, while preserving its source row',()=>{
 const plan=zone('지구단위계획구역','UQQ300','1',{cnflcAtNm:'포함',manageNo:'PLAN-A'});
 const development=zone('택지개발지구','SOURCE-DISTRICT','1',{cnflcAtNm:'포함'});
 const p={pnu,attributes:{landUse:{status:'호출 확인',rows:[plan,development]}}};
 const area=designationSummary([p],'useArea'),district=designationSummary([p],'district');
 assert.deepEqual(area.rows,[{label:'지구단위계획구역',value:1}]);assert.equal(area.assignments,1);
 assert.equal(area.evidence[0].source.manageNo,'PLAN-A');assert.equal(area.evidence[0].relation,'포함');
 assert.deepEqual(district.rows,[{label:'택지개발지구',value:1}]);
});
test('adjacent district plan area stays out of chart but its explicit exclusion is explained',()=>{
 const p={pnu,attributes:{landUse:{status:'호출 확인',rows:[zone('지구단위계획구역','UQQ300','3'),zone('소하천구역','SOURCE-AREA','2')]}}};
 const result=designationSummary([p],'useArea');
 assert.deepEqual(result.rows,[{label:'소하천구역',value:1}]);assert.deepEqual(result.adjacentNames,['지구단위계획구역']);
 assert.match(result.note,/접함 제외: 지구단위계획구역/);assert.equal(result.evidence[0].decision,'접함 · 집계 제외');
});
test('conflicting relationship code and name cannot turn an adjacent district plan into inclusion',()=>{
 const p={pnu,attributes:{landUse:{status:'호출 확인',rows:[zone('지구단위계획구역','UQQ300','3',{cnflcAtNm:'포함'})]}}};
 const result=designationSummary([p],'useArea');assert.equal(result.assignments,0);
 assert.equal(result.evidence[0].decision,'관계 미확정');assert.deepEqual(result.adjacentNames,[]);
});

test('combined regulation composition gives 40/60 percent and each category its own denominator',()=>{
 const parcels=Array.from({length:20},(_,i)=>({pnu:String(BigInt(pnu)+BigInt(i)),attributes:{landUse:{status:'success',rows:[
  zone(i<8?'제1종일반주거지역':'제2종일반주거지역',i<8?'UQA121':'UQA122'),
  ...(i<8?[]:[zone('택지개발지구','SOURCE-DISTRICT')]),
  zone(i<8?'지구단위계획구역':i<16?'토지거래계약에관한허가구역':'가축사육제한구역','SOURCE-AREA')
 ].map(row=>({...row,pnu:String(BigInt(pnu)+BigInt(i))}))}}}));
 const original=JSON.stringify(parcels),groups=designationComposition(parcels);
 assert.equal(JSON.stringify(parcels),original);assert.deepEqual(groups.map(g=>g.total),[20,20,20]);
 assert.deepEqual(groups[0].rows.map(r=>[r.value,r.percentage]),[[8,40],[12,60]]);
 assert.deepEqual(groups[1].rows.map(r=>[r.label,r.value,r.percentage]),[['미지정',8,40],['택지개발지구',12,60]]);
 assert.deepEqual(groups[2].rows.map(r=>r.percentage),[40,40,20]);
});

test('overlapping designations use summed assignments; unknown and duplicate parcels stay honest',()=>{
 const one={pnu,attributes:{landUse:{status:'success',rows:[zone('제1종일반주거지역','UQA121'),zone('제2종일반주거지역','UQA122'),zone('제2종일반주거지역','UQA122'),zone('일반상업지역','UQA220','3')]}}};
 const unknown={pnu:'4136025321107100001',attributes:{landUse:{status:'failed',rows:[]}}};
 const groups=designationComposition([one,one,unknown]);
 assert.equal(groups[0].parcelCount,2);assert.equal(groups[0].multipleParcels,1);assert.equal(groups[0].total,3);
 assert.deepEqual(groups[0].rows.map(r=>r.value),[1,1,1]);assert.ok(groups[0].rows.every(r=>Math.abs(r.percentage-100/3)<1e-10));
 assert.equal(groups[1].total,2);assert.deepEqual(groups[1].rows.map(r=>[r.label,r.percentage]),[['미지정',50],['미확인',50]]);
 assert.ok(designationComposition([]).every(g=>g.total===0&&g.rows.length===0));
});
