import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parcelInteriorPoint,parcelLabelAnchors,layoutParcelLabels} from './parcel-map-labels.mjs';
import {buildingSummary} from './survey-summary.mjs';
import {mercatorWorld} from './map-overlays.mjs';

const ring=points=>points.map(([x,y])=>[127+x*.001,37+y*.001]);
const square=(x,y,size)=>ring([[x,y],[x+size,y],[x+size,y+size],[x,y+size],[x,y]]);
const polygon=coordinates=>({type:'Polygon',coordinates});
const inside=(point,r)=>{
 let result=false;
 for(let i=0,j=r.length-1;i<r.length;j=i++)if((r[i][1]>point.lat)!==(r[j][1]>point.lat)&&point.lon<(r[j][0]-r[i][0])*(point.lat-r[i][1])/(r[j][1]-r[i][1])+r[i][0])result=!result;
 return result;
};
test('a concave parcel uses an interior point rather than the empty bounding-box center',()=>{
 const c=ring([[0,0],[6,0],[6,1],[1,1],[1,5],[6,5],[6,6],[0,6],[0,0]]),point=parcelInteriorPoint(polygon([c]));
 assert.ok(inside(point,c));assert.equal(inside({lon:127.003,lat:37.003},c),false);
});
test('parcel labels avoid polygon holes irrespective of ring orientation',()=>{
 const outer=square(0,0,10),hole=square(1,1,8);
 for(const holeRing of [hole,[...hole].reverse()]){
  const point=parcelInteriorPoint(polygon([outer,holeRing]));assert.ok(inside(point,outer));assert.equal(inside(point,hole),false);
 }
});
test('a MultiPolygon receives one anchor within its largest usable part',()=>{
 const small=square(0,0,1),large=square(10,10,5),point=parcelInteriorPoint({type:'MultiPolygon',coordinates:[[small],[large]]});
 assert.ok(inside(point,large));assert.equal(inside(point,small),false);
});
test('invalid and missing boundaries do not invent label positions',()=>{
 for(const geometry of [null,{type:'Point',coordinates:[127,37]},polygon([]),polygon([[[127,37],[127,37],[127,37],[127,37]]]),polygon([[[127,37],[NaN,37],[127,38],[127,37]]])])assert.equal(parcelInteriorPoint(geometry),null);
});
test('map numbers match building numbers after deduplication, missing geometry, and selection removal',()=>{
 const a={pnu:'a',geometry:polygon([square(0,0,1)]),buildings:[{buldIdntfcNo:'building-a',buldTotar:90}]},b={pnu:'b',buildings:[{buldIdntfcNo:'building-b',buldTotar:60}]},c={pnu:'c',geometry:polygon([square(2,2,1)]),buildings:[{buldIdntfcNo:'building-c',buldTotar:30}]};
 const parcels=[a,b,a,c],anchors=parcelLabelAnchors(parcels),buildings=buildingSummary(parcels).buildings;
 assert.deepEqual(anchors.map(p=>[p.pnu,p.number]),[['a',1],['c',3]]);
 assert.ok(buildings.find(b=>b.identifier==='building-c').label.startsWith('3번 /'));
 const changed=[b,c];assert.equal(parcelLabelAnchors(changed)[0].number,2);assert.ok(buildingSummary(changed).buildings.find(b=>b.identifier==='building-c').label.startsWith('2번 /'));
});
test('adjacent parcel badges retain identities and use leaders without overlapping controls or each other',()=>{
 const anchors=Array.from({length:12},(_,i)=>({id:String(i),pnu:String(i),number:i+1,lon:127+i*.00002,lat:37}));
 const [cx,cy]=mercatorWorld(127,37,17),blocked={x:175,y:185,width:60,height:38};
 const labels=layoutParcelLabels(anchors,{zoom:17,left:cx-160,top:cy-200,width:320,height:400,blocked:[blocked]});
 const overlaps=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
 assert.equal(labels.length,12);assert.ok(labels.some(l=>l.displaced));
 for(let i=0;i<labels.length;i++){
  assert.equal(labels[i].number,i+1);assert.equal(overlaps(labels[i],blocked),false);
  for(let j=i+1;j<labels.length;j++)assert.equal(overlaps(labels[i],labels[j]),false);
 }
 assert.equal(layoutParcelLabels(anchors,{zoom:17,left:cx+1000,top:cy+1000,width:320,height:400}).length,0);
});
