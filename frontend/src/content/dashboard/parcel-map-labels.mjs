import {uniqueSurveyParcels} from './survey-summary.mjs';
import {mercatorWorld} from './map-overlays.mjs';

const ringArea=ring=>{
 const [ox,oy]=ring[0];let area=0;
 for(let i=0,j=ring.length-1;i<ring.length;j=i++)area+=(ring[j][0]-ox)*(ring[i][1]-oy)-(ring[i][0]-ox)*(ring[j][1]-oy);
 return Math.abs(area)/2;
};
const segmentDistance=(x,y,a,b)=>{
 const dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy,t=den?Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/den)):0;
 return Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy);
};

// Scan through polygon interiors instead of using a bounding-box center, which
// may lie outside a concave parcel or inside a courtyard. Holes participate in
// the even/odd intersections. Use the largest actual part of a MultiPolygon.
export function parcelInteriorPoint(geometry){
 const polygons=geometry?.type==='Polygon'?[geometry.coordinates]:geometry?.type==='MultiPolygon'?geometry.coordinates:[];
 if(!Array.isArray(polygons))return null;
 const valid=polygons.filter(p=>Array.isArray(p)&&p.length&&p.every(r=>Array.isArray(r)&&r.length>=4&&r.every(c=>Array.isArray(c)&&Number.isFinite(c[0])&&Number.isFinite(c[1])&&Math.abs(c[0])<=180&&Math.abs(c[1])<=85.05112878)))
  .map(p=>p.map(r=>r.map(([lon,lat])=>mercatorWorld(lon,lat,0))))
  .map(rings=>({rings,area:ringArea(rings[0])-rings.slice(1).reduce((n,r)=>n+ringArea(r),0)})).filter(p=>p.area>0).sort((a,b)=>b.area-a.area);
 const rings=valid[0]?.rings;if(!rings)return null;
 const ys=[...new Set(rings.flat().map(c=>c[1]))].sort((a,b)=>a-b),lo=ys[0],hi=ys.at(-1);
 if(!(hi>lo))return null;
 const levels=Array.from({length:33},(_,i)=>lo+(hi-lo)*(i+.5)/33);
 // Vertex bands catch thin interior corridors missed by the uniform scan.
 const stride=Math.max(1,Math.ceil((ys.length-1)/128));
 for(let i=0;i<ys.length-1;i+=stride)levels.push((ys[i]+ys[i+1])/2);
 let best=null;
 for(const y of levels){
  const crossings=[];
  for(const ring of rings)for(let i=0,j=ring.length-1;i<ring.length;j=i++){
   const a=ring[j],b=ring[i];if((a[1]>y)!==(b[1]>y))crossings.push(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]));
  }
  crossings.sort((a,b)=>a-b);
  for(let i=0;i+1<crossings.length;i+=2){
   const x=(crossings[i]+crossings[i+1])/2;if(!(crossings[i+1]>crossings[i]))continue;
   let clearance=Infinity;
   for(const ring of rings)for(let k=0,j=ring.length-1;k<ring.length;j=k++)clearance=Math.min(clearance,segmentDistance(x,y,ring[j],ring[k]));
   if(clearance>0&&(!best||clearance>best.clearance))best={x,y,clearance};
  }
 }
 if(!best)return null;
 return {lon:best.x/256*360-180,lat:Math.atan(Math.sinh(Math.PI*(1-2*best.y/256)))*180/Math.PI};
}

export function parcelLabelAnchors(parcels){
 // Keep missing-geometry parcels in this enumeration so chart numbering never
 // shifts when only some parcel boundaries are available.
 return uniqueSurveyParcels(parcels).flatMap((parcel,index)=>{
  const point=parcelInteriorPoint(parcel.geometry);
  return point?[{...point,pnu:String(parcel.pnu||''),number:index+1,address:parcel.address||'',id:String(parcel.pnu||`missing-${index}`)}]:[];
 });
}

const overlaps=(a,b)=>a.x<b.x+b.width+3&&a.x+a.width+3>b.x&&a.y<b.y+b.height+3&&a.y+a.height+3>b.y;
export function layoutParcelLabels(anchors,{zoom,left,top,width,height,blocked=[]}){
 const occupied=[...blocked],labels=[];
 for(const anchor of anchors){
  const [wx,wy]=mercatorWorld(anchor.lon,anchor.lat,zoom),anchorX=wx-left,anchorY=wy-top;
  if(anchorX<0||anchorY<0||anchorX>width||anchorY>height)continue;
  const labelWidth=Math.max(22,String(anchor.number).length*7+10),labelHeight=20,offsets=[[0,0]];
  for(const radius of [25,45,70,100,140])for(const [dx,dy] of [[0,-1],[1,0],[0,1],[-1,0],[.707,-.707],[.707,.707],[-.707,.707],[-.707,-.707]])offsets.push([radius*dx,radius*dy]);
  const candidates=offsets.map(([dx,dy])=>({x:anchorX+dx-labelWidth/2,y:anchorY+dy-labelHeight/2,width:labelWidth,height:labelHeight}))
   .filter(box=>box.x>=3&&box.y>=3&&box.x+box.width<=width-3&&box.y+box.height<=height-3);
  // Retain every selected number even in a fully occupied zoomed-out view;
  // zooming in resolves the remaining overlap without changing its identity.
  const box=candidates.find(b=>!occupied.some(o=>overlaps(b,o)))||candidates[0];
  if(!box)continue;
  occupied.push(box);labels.push({...anchor,...box,anchorX,anchorY,displaced:Math.hypot(box.x+box.width/2-anchorX,box.y+box.height/2-anchorY)>2});
 }
 return labels;
}
