// 콘솔 차트 (SVG 문자열). 색은 CSS 변수(--s1 --s2 --s3 --fore --good --warn --bad --land --build --soft --fin --grid --muted --ink --surface)로만 칠한다.
// 모든 차트는 값을 직접 라벨로 붙이고, 점·막대에 data-tip 을 달아 마우스를 올리면 값이 보이게 한다.
export const fin=Number.isFinite;
export const nf=(v,d=0)=>fin(v)?v.toLocaleString('ko-KR',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
export const eok=(w,d=1)=>fin(w)?nf(w/1e8,d)+'억':'—';
export const man=(w,d=1)=>fin(w)?nf(w/1e4,d)+'만':'—';
export const m2=v=>fin(v)?nf(v,0)+'㎡':'—';
export const pct=(v,d=1)=>fin(v)?nf(v,d)+'%':'—';
export const signed=(v,d=1,u='%')=>fin(v)?(v>0?'+':v<0?'−':'')+nf(Math.abs(v),d)+u:'—';
export const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const PY=3.3058;
const ym=s=>{const [y,m]=String(s).split('-').map(Number);return y*12+m-1};
const niceMax=v=>{if(!(v>0))return 1;const p=Math.pow(10,Math.floor(Math.log10(v))),n=v/p;return (n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*p};
const COLORS=['var(--s1)','var(--s2)','var(--s3)','var(--s4)','var(--s5)'];
export const groupLabel=key=>{const [,j,z]=String(key).split('|');return `${j||'?'} · ${z||'?'}`};

/* 12개월 이동 중앙값 (거래 있는 달이 3개 이상일 때만) */
export function rolling(points){
 return points.map((p,i)=>{const win=points.slice(0,i+1).filter(q=>ym(q[0])>ym(p[0])-12&&fin(q[1])).map(q=>q[1]).sort((a,b)=>a-b);
  return [p[0],p[1],p[2],win.length>=3?(win[Math.floor((win.length-1)/2)]+win[Math.ceil((win.length-1)/2)])/2:null]});
}
/* 토지 그룹 단가 추이와 예측. groups=[{key,label,unit,targetMonth,fromMonth,areaM2,points:[[월,단가,건수,이동중앙값]]}] */
export function forecastChart(groups,{w=820,h=320,from='2021-01',asOf}={}){
 if(!groups.length)return '<p class="empty">모델 예측이 있는 토지 그룹이 없습니다.</p>';
 const x0=ym(from),x1=Math.max(...groups.map(g=>ym(g.targetMonth||from)),ym(asOf||from))+1;
 const pad={l:62,r:215,t:40,b:76},cH=30,iw=w-pad.l-pad.r,ih=h-pad.t-pad.b;
 const vals=groups.flatMap(g=>g.points.filter(p=>ym(p[0])>=x0).flatMap(p=>[p[3],p[1]]).concat(g.unit)).filter(fin).sort((a,b)=>a-b);
 const ymax=niceMax((vals[Math.floor(vals.length*.97)]||1)*1.08);
 const X=i=>pad.l+(i-x0)/(x1-x0)*iw,Y=v=>pad.t+ih-Math.min(v,ymax)/ymax*ih;
 let g='';
 for(let k=0;k<=5;k++){const v=ymax/5*k,y=Y(v);g+=`<line x1="${pad.l}" x2="${pad.l+iw}" y1="${y}" y2="${y}" stroke="var(--grid)"/><text x="${pad.l-8}" y="${y+4}" text-anchor="end" class="ax">${nf(v/1e4,0)}</text>`}
 g+=`<text x="4" y="16" class="ax">만원/㎡</text>`;
 for(let i=x0;i<=x1;i++)if(i%12===0)g+=`<line x1="${X(i)}" x2="${X(i)}" y1="${pad.t}" y2="${pad.t+ih}" stroke="var(--grid)" stroke-dasharray="2 4"/><text x="${X(i)}" y="${pad.t+ih+21}" text-anchor="middle" class="ax">${Math.floor(i/12)}</text>`;
 if(asOf){const a=ym(asOf);g+=`<rect x="${X(a)}" y="${pad.t}" width="${Math.max(0,pad.l+iw-X(a))}" height="${ih}" fill="var(--fore)" fill-opacity=".08"/><line x1="${X(a)}" x2="${X(a)}" y1="${pad.t}" y2="${pad.t+ih}" stroke="var(--fore)" stroke-dasharray="3 3"/><text x="${X(a)+5}" y="${pad.t+12}" class="ax" style="fill:var(--fore)">예측 구간</text>`}
 const labels=[];
 groups.forEach((s,si)=>{
  const c=COLORS[si%COLORS.length],pts=s.points.filter(p=>ym(p[0])>=x0);
  pts.forEach(p=>{if(fin(p[1]))g+=`<circle cx="${X(ym(p[0]))}" cy="${Y(p[1])}" r="2.2" fill="${c}" fill-opacity=".3" data-tip="${esc(s.label)} · ${p[0]} · ${man(p[1])}원/㎡ · 거래 ${p[2]}건"/>`});
  let d='',last=null;pts.forEach(p=>{if(fin(p[3])){d+=(d?'L':'M')+X(ym(p[0])).toFixed(1)+','+Y(p[3]).toFixed(1);last=p}});
  if(d)g+=`<path d="${d}" fill="none" stroke="${c}" stroke-width="2.2" stroke-linejoin="round"/>`;
  if(!fin(s.unit)||!s.targetMonth)return;
  const fx=X(ym(s.targetMonth)),fy=Y(s.unit);
  if(last){const lx=X(ym(last[0])),ly=Y(last[3]);g+=`<path d="M${lx},${ly}L${fx},${fy}" stroke="${c}" stroke-width="2" stroke-dasharray="5 4" fill="none"/><circle cx="${lx}" cy="${ly}" r="3.5" fill="${c}"/>`}
  g+=`<circle cx="${fx}" cy="${fy}" r="6" fill="var(--surface)" stroke="${c}" stroke-width="2.5" data-tip="${esc(s.label)} 예측 · ${s.targetMonth} · ${man(s.unit)}원/㎡${s.fromMonth?` (${s.fromMonth} 기준 6개월 뒤)`:''}"/>`;
  labels.push({y:fy,c,s,chg:last?(s.unit/last[3]-1)*100:null});
 });
 labels.sort((p,q)=>p.y-q.y);let prev=-99;
 labels.forEach(l=>{const y=Math.max(l.y,prev+44);prev=y;g+=`<text x="${pad.l+iw+12}" y="${y-3}" class="lb" style="fill:${l.c}">${esc(l.s.label)}</text><text x="${pad.l+iw+12}" y="${y+17}" class="ax">${man(l.s.unit)} · ${fin(l.chg)?signed(l.chg,0):'—'}</text>`});
 const base=h-14;g+=`<text x="${pad.l-8}" y="${base}" text-anchor="end" class="ax">거래</text>`;
 const cnt={};groups.forEach(s=>s.points.forEach(p=>{if(ym(p[0])>=x0)cnt[p[0]]=(cnt[p[0]]||0)+p[2]}));
 const mx=Math.max(...Object.values(cnt),1),bw=Math.max(1.5,iw/(x1-x0)-1.5);
 Object.entries(cnt).forEach(([m,n])=>{if(n)g+=`<rect x="${X(ym(m))-bw/2}" y="${base-n/mx*cH}" width="${bw}" height="${n/mx*cH}" fill="var(--muted)" fill-opacity=".45" data-tip="${m} · 거래 ${n}건"/>`});
 return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="토지 그룹별 ㎡당 거래 단가 추이와 모델 예측">${g}</svg>`;
}
/* 수지 폭포: 총수입 → 지출 항목 → 사업이익. items=[{label,amt,kind}] */
/* 폭포 차트 항목 이름: 4글자 이상이면 두 줄 (간접/공사비, 분양/제비용 …) — 큰 글씨에서 이름끼리 겹치지 않게 */
const wfLabel=(label,x,y)=>{const t=String(label);if(t.length<4)return `<text x="${x}" y="${y}" text-anchor="middle" class="ax">${esc(t)}</text>`;
 return `<text x="${x}" y="${y}" text-anchor="middle" class="ax">${esc(t.slice(0,2))}<tspan x="${x}" dy="18">${esc(t.slice(2))}</tspan></text>`};
export function waterfall(R,items,profit,{w=760,h=290}={}){
 if(!fin(R)||!fin(profit)||items.some(x=>!fin(x.amt)))return '<p class="empty">수지 계산이 끝나면 표시됩니다.</p>';
 const all=[{label:'총수입',v:R,kind:'total'},...items.map(x=>({label:x.label,v:-x.amt,kind:x.kind})),{label:'사업이익',v:profit,kind:'result'}];
 const pad={l:70,r:10,t:48,b:66},iw=w-pad.l-pad.r,ih=h-pad.t-pad.b,n=all.length,bw=iw/n*.62;
 const lo=Math.min(0,profit),hi=Math.max(R,1),Y=v=>pad.t+(hi-v)/(hi-lo)*ih;
 let g='',run=0;
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)/4*k;g+=`<line x1="${pad.l}" x2="${w-pad.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${pad.l-8}" y="${Y(v)+4}" text-anchor="end" class="ax">${nf(v/1e8,0)}</text>`}
 g+=`<line x1="${pad.l}" x2="${w-pad.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--muted)"/><text x="4" y="16" class="ax">억원</text>`;
 const col={total:'var(--s1)',land:'var(--land)',construction:'var(--build)',result:profit>=0?'var(--good)':'var(--bad)',finance:'var(--fin)',trust:'var(--fin)'};
 all.forEach((it,i)=>{
  const cx=pad.l+iw/n*(i+.5);let y0,y1;
  if(it.kind==='total'){y0=0;y1=it.v;run=it.v}else if(it.kind==='result'){y0=0;y1=it.v}else{y0=run;y1=run+it.v;run=y1}
  const top=Y(Math.max(y0,y1)),bot=Y(Math.min(y0,y1));
  g+=`<rect x="${cx-bw/2}" y="${top}" width="${bw}" height="${Math.max(1,bot-top)}" rx="2" fill="${col[it.kind]||'var(--soft)'}" data-tip="${esc(it.label)} ${eok(Math.abs(it.v),1)}"/>`;
  if(i<n-1){const ny=Y(run);g+=`<line x1="${cx+bw/2}" x2="${cx+iw/n-bw/2}" y1="${ny}" y2="${ny}" stroke="var(--muted)" stroke-dasharray="2 2"/>`}
  const big=Math.abs(it.v)/(hi-lo)>.06,strong=it.kind==='total'||it.kind==='result';
  g+=`<text x="${cx}" y="${top-6}" text-anchor="middle" class="${strong?'lb':'ax'}">${strong?(it.v<0?'−':''):'−'}${nf(Math.abs(it.v)/1e8,big?0:1)}</text>${wfLabel(it.label,cx,h-pad.b+22)}`;
 });
 return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="총수입에서 지출을 빼 사업이익을 구하는 폭포 차트">${g}</svg>`;
}
/* 분양 비교단지 평당가 띠. points=[{label,value(원/평),on,km}] applied=원/평 */
export function strip(points,applied,{w=420,h=150}={}){
 if(!points.length)return '<p class="empty">분양 비교단지가 없습니다.</p>';
 const vals=points.map(p=>p.value).concat(fin(applied)?applied:[]),mn=Math.min(...vals)*.94,mx=Math.max(...vals)*1.04||1,pad=28,X=v=>pad+(v-mn)/(mx-mn||1)*(w-2*pad),yA=74;
 let g=`<line x1="${pad}" x2="${w-pad}" y1="${yA}" y2="${yA}" stroke="var(--grid)" stroke-width="6" stroke-linecap="round"/>`;
 const step=niceMax((mx-mn)/4);for(let v=Math.ceil(mn/step)*step;v<=mx;v+=step)g+=`<text x="${X(v)}" y="${yA+56}" text-anchor="middle" class="ax">${nf(v/1e4,0)}만</text><line x1="${X(v)}" x2="${X(v)}" y1="${yA+8}" y2="${yA+26}" stroke="var(--grid)"/>`;
 points.forEach((p,i)=>{const x=X(p.value);g+=`<circle cx="${x}" cy="${yA}" r="8" fill="${p.on?'var(--s1)':'var(--surface)'}" stroke="var(--s1)" stroke-width="2" data-tip="${esc(p.label)} · 평당 ${man(p.value,0)}원${fin(p.km)?` · ${nf(p.km,1)}km`:''}"/><text x="${x}" y="${i%2?yA+32:yA-18}" text-anchor="middle" class="ax">${esc(String(p.label).split(' ')[0])}</text>`});
 if(fin(applied)){const x=X(applied);g+=`<line x1="${x}" x2="${x}" y1="${yA-34}" y2="${yA+12}" stroke="var(--fore)" stroke-width="2"/><text x="${Math.min(w-110,Math.max(110,x))}" y="${yA-42}" text-anchor="middle" class="lb" style="fill:var(--fore)">적용 ${man(applied,0)}원/평</text>`}
 return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="비교단지 평당 분양가와 적용값">${g}</svg>`;
}
/* 민감도 표: rows×cols 목표 수익률 */
export function heatmap(rows,cols,matrix,current,{w=420,h=250,rowLabel=v=>v,colLabel=v=>v,corner=''}={}){
 const pad={l:104,t:36,r:6,b:8},cw=(w-pad.l-pad.r)/cols.length,ch=(h-pad.t-pad.b)/rows.length;
 const color=m=>!fin(m)?'var(--grid)':m<0?`color-mix(in srgb,var(--bad) ${Math.min(85,25+(-m)*2)}%,var(--surface))`:m<10?`color-mix(in srgb,var(--warn) ${30+m*3}%,var(--surface))`:`color-mix(in srgb,var(--good) ${Math.min(85,20+m*1.4)}%,var(--surface))`;
 let g=cols.map((c,j)=>`<text x="${pad.l+cw*(j+.5)}" y="${pad.t-10}" text-anchor="middle" class="ax">${esc(colLabel(c))}</text>`).join('')+`<text x="${pad.l-8}" y="${pad.t-10}" text-anchor="end" class="ax">${esc(corner)}</text>`;
 rows.forEach((r,i)=>{g+=`<text x="${pad.l-8}" y="${pad.t+ch*(i+.5)+4}" text-anchor="end" class="ax">${esc(rowLabel(r))}</text>`;cols.forEach((c,j)=>{const m=matrix[i][j],cur=current&&current[0]===r&&current[1]===c;g+=`<rect x="${pad.l+cw*j+2}" y="${pad.t+ch*i+2}" width="${cw-4}" height="${ch-4}" rx="5" fill="${color(m)}" ${cur?'stroke="var(--ink)" stroke-width="2.5"':''} data-tip="${esc(rowLabel(r))} · ${esc(colLabel(c))} → ${pct(m)}"/><text x="${pad.l+cw*(j+.5)}" y="${pad.t+ch*(i+.5)+4}" text-anchor="middle" class="lb" style="font-size:18px">${pct(m,0)}</text>`})});
 return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="민감도 표">${g}</svg>`;
}
/* 가정별 ±10% 민감도 막대. items=[{label,down,up}] (%p) */
export function tornado(items,{w=420,h=210}={}){
 const list=items.filter(x=>fin(x.down)&&fin(x.up));
 if(!list.length)return '<p class="empty">수지 계산이 끝나면 표시됩니다.</p>';
 const pad={l:124,r:70,t:14,b:30},rowH=(h-pad.t-pad.b)/list.length,m=Math.max(...list.flatMap(x=>[Math.abs(x.up),Math.abs(x.down)]),.5)*1.1;
 const cx=pad.l+(w-pad.l-pad.r)/2,half=(w-pad.l-pad.r)/2-56,X=v=>cx+v/m*half;
 let g=`<line x1="${cx}" x2="${cx}" y1="${pad.t-4}" y2="${h-pad.b+4}" stroke="var(--muted)"/>`;
 list.forEach((d,i)=>{const y=pad.t+rowH*i+rowH*.2,bh=rowH*.6;[[d.down,'−10%'],[d.up,'+10%']].forEach(([v,l])=>{const x=Math.min(X(0),X(v)),wd=Math.abs(X(v)-X(0));g+=`<rect x="${x}" y="${y}" width="${Math.max(1,wd)}" height="${bh}" rx="3" fill="${v<0?'var(--bad)':'var(--good)'}" fill-opacity=".8" data-tip="${esc(d.label)} ${l} → 수익률 ${signed(v,1,'%p')}"/><text x="${v<0?x-5:x+wd+5}" y="${y+bh/2+4}" text-anchor="${v<0?'end':'start'}" class="ax">${signed(v,1,'p')}</text>`});g+=`<text x="${pad.l-10}" y="${y+bh/2+4}" text-anchor="end" class="lb" style="font-size:18px">${esc(d.label)}</text>`});
 g+=`<text x="${cx}" y="${h-4}" text-anchor="middle" class="ax">각 가정 ±10% → 목표 수익률 변화(%p)</text>`;
 return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="가정별 민감도">${g}</svg>`;
}
export function lineSeries(points,{w=620,h=150,unit='',color='var(--s2)',label=''}={}){
 if(points.length<2)return '<p class="empty">지표 자료가 없습니다.</p>';
 const vals=points.map(p=>p[1]),mn=Math.min(...vals,0),mx=Math.max(...vals),pad={l:50,r:78,t:14,b:26},X=i=>pad.l+i/(points.length-1)*(w-pad.l-pad.r),Y=v=>pad.t+(mx-v)/(mx-mn||1)*(h-pad.t-pad.b);
 let g=`<line x1="${pad.l}" x2="${w-pad.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--grid)"/><text x="${pad.l-6}" y="${Y(mx)+4}" text-anchor="end" class="ax">${nf(mx,1)}</text><text x="${pad.l-6}" y="${Y(mn)+4}" text-anchor="end" class="ax">${nf(mn,1)}</text>`;
 points.forEach((p,i)=>{if(String(p[0]).endsWith('-01'))g+=`<text x="${X(i)}" y="${h-4}" text-anchor="middle" class="ax">${String(p[0]).slice(0,4)}</text>`});
 g+=`<path d="${points.map((p,i)=>(i?'L':'M')+X(i).toFixed(1)+','+Y(p[1]).toFixed(1)).join('')}" fill="none" stroke="${color}" stroke-width="2"/>`;
 points.forEach((p,i)=>{g+=`<rect x="${X(i)-2}" y="${pad.t}" width="4" height="${h-pad.t-pad.b}" fill="transparent" data-tip="${esc(p[0])} · ${nf(p[1],2)}${unit}"/>`});
 const l=points.at(-1);g+=`<circle cx="${X(points.length-1)}" cy="${Y(l[1])}" r="3.5" fill="${color}"/><text x="${X(points.length-1)+6}" y="${Y(l[1])+4}" class="lb" style="font-size:18px">${nf(l[1],2)}${unit}</text>`;
 return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="${esc(label)}">${g}</svg>`;
}
/* 주변시설 거리 분포 (가운데 = 선택 필지 중심) */
export function radar(items,center,{size=320,radiusKm=5,groups={}}={}){
 if(!center)return '<p class="empty">필지를 선택하면 주변시설이 표시됩니다.</p>';
 const S=size/2,R=S-16,pos=f=>{const dx=(f.lon-center.lon)*111.32*Math.cos(center.lat*Math.PI/180),dy=(f.lat-center.lat)*110.57;return [S+dx/radiusKm*R,S-dy/radiusKm*R]};
 let g=[1,3,5].filter(k=>k<=radiusKm).map(k=>`<circle cx="${S}" cy="${S}" r="${k/radiusKm*R}" fill="none" stroke="var(--grid)" ${k===radiusKm?'':'stroke-dasharray="3 4"'}/><text x="${S+4}" y="${S-k/radiusKm*R+12}" class="ax">${k}km</text>`).join('');
 g+=`<line x1="${S}" y1="${S-R}" x2="${S}" y2="${S+R}" stroke="var(--grid)"/><line x1="${S-R}" y1="${S}" x2="${S+R}" y2="${S}" stroke="var(--grid)"/>`;
 items.forEach(f=>{if(!fin(f.lon)||!fin(f.lat))return;const [x,y]=pos(f);if(Math.hypot(x-S,y-S)>R+2)return;g+=`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.5" fill="${(groups[f.group]||[])[1]||'var(--soft)'}" stroke="var(--surface)" stroke-width="1.2" data-tip="${esc(f.name)} · ${fin(f.distanceKm)?nf(f.distanceKm,2)+'km':''}"/>`});
 g+=`<circle cx="${S}" cy="${S}" r="6" fill="var(--ink)"/>`;
 return `<svg viewBox="0 0 ${size} ${size}" class="chart" style="max-width:${size}px;margin:0 auto" role="img" aria-label="주변 시설 거리 분포">${g}</svg>`;
}
