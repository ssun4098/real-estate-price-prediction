// 분석 콘솔 '가상 데이터' 단독 HTML 만들기 (2026-11-03 요청: 서버 없이 HTML 파일 하나로 열리는 화면).
// 결과: frontend/console/standalone/분석콘솔_가상데이터.html  — 더블클릭해 브라우저로 열면 된다.
//  - JS(콘솔 + 지도 + 계산 규칙 + 가짜 서버 mock.js)와 CSS, 가상 데이터(demo-data.json.gz)를 모두 HTML 안에 넣는다.
//  - 위성 타일 주소(/api/tiles/...)는 묶을 때 가짜 타일 함수(__mockTile)로 바꾼다 (원래 파일은 그대로).
// 실행: frontend 폴더에서 `node console/build.mjs` 다음 `node console/standalone/build-standalone.mjs`
//       (자료를 새로 만들 때만: 프로젝트 폴더에서 `python frontend/console/standalone/make_demo_data.py`)
import {rolldown} from 'rolldown';
import {readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const consoleDir=path.join(here,'..');
const dashboard=path.join(consoleDir,'..','src','content','dashboard');
const BOUNDARY_ORIGINAL=path.join(dashboard,'boundary-allocation.mjs'),BOUNDARY_CACHE=path.join(consoleDir,'src','boundary-cache.mjs');
const OUT=path.join(here,'분석콘솔_가상데이터.html');

// 위성 타일 주소 → 가짜 타일 (지도 부품과 도면 차트 두 곳)
const TILE_SWAPS=[
 ['pf-live-widgets.jsx','href={`/api/tiles/${view.z}/${t.y}/${t.x}.jpeg`}','href={globalThis.__mockTile(view.z,t.y,t.x)}'],
 ['charts.js','<image href="/api/tiles/${z}/${ty}/${tx}.jpeg"','<image href="${globalThis.__mockTile(z,ty,tx)}"'],
];

const bundle=await rolldown({
 input:path.join(here,'standalone.js'),
 platform:'browser',
 transform:{jsx:{runtime:'automatic'},define:{'process.env.NODE_ENV':'"production"'}},
 plugins:[{
  name:'console-standalone',
  // console/build.mjs 와 같은 규칙: 카드·표 부품은 빈 부품, CSS import 는 무시, 경계 검사는 기억 기능을 붙인 파일로
  resolveId(source){
   if(source.endsWith('/data-app-public.jsx')||source.endsWith('/data-component.jsx'))return '\0console-stub';
   if(source.endsWith('.css'))return '\0console-css';
   if(source==='console-original:boundary-allocation')return BOUNDARY_ORIGINAL;
   if(source.endsWith('/boundary-allocation.mjs'))return BOUNDARY_CACHE;
   return null;
  },
  load(id){
   if(id==='\0console-stub')return 'const Empty=()=>null;export const DataComponent=Empty,EvidenceChart=Empty,DataTable=Empty;';
   if(id==='\0console-css')return 'export default "";';
   return null;
  },
  transform(code,id){
   for(const [file,from,to] of TILE_SWAPS){
    if(!id.endsWith(path.sep+file)&&!id.endsWith('/'+file))continue;
    if(!code.includes(from))throw new Error(`${file}: 위성 타일 주소를 찾지 못했습니다. build-standalone.mjs 의 TILE_SWAPS 를 고치세요.`);
    return code.split(from).join(to);
   }
   return null;
  },
 }],
});
const {output}=await bundle.generate({format:'esm',minify:true,sourcemap:false});
await bundle.close();
const js=output[0].code.replace(/<\/script/gi,'<\\/script').replace(/<!--/g,'<\\!--');

const css=(await readFile(path.join(consoleDir,'build','console.css'),'utf8'))+`
/* 가상 데이터 표시 */
.demo-tag{display:inline-flex;align-items:center;padding:2px 10px;border-radius:999px;background:color-mix(in srgb,var(--fin) 25%,transparent);color:#E2D5FF;font-size:14px;font-weight:600;white-space:nowrap}`;
const data=(await readFile(path.join(here,'demo-data.json.gz'))).toString('base64');

let html=await readFile(path.join(consoleDir,'index.html'),'utf8');
const swap=(from,to)=>{if(!html.includes(from))throw new Error('index.html 에서 찾지 못했습니다: '+from);html=html.replace(from,()=>to)};
swap('<link rel="stylesheet" href="/console/build/console.css">',`<style>\n${css}\n</style>`);
swap('<script type="module" src="/console/build/console.js"></script>',`<script id="demo-data" type="application/octet-stream">${data}</script>\n<script type="module">\n${js}\n</script>`);
html=html.replace(/<title>([^<]*)<\/title>/,(m,t)=>`<title>${t} · 가상 데이터</title>`);
await writeFile(OUT,html);
console.log(`단독 HTML을 만들었습니다: ${path.relative(path.join(consoleDir,'..','..'),OUT)} (${(Buffer.byteLength(html)/1e6).toFixed(1)}MB)`);
