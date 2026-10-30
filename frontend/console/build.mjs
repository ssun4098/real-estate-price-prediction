// 콘솔 화면 빌드: src/main.js(+ 기존 화면의 계산 규칙 모듈과 지도 부품 import)를 build/console.js 하나로 묶고,
// 콘솔 CSS 와 기존 화면의 지도 CSS 를 build/console.css 하나로 합친다.
// (build/ 결과는 git 에 함께 올린다. 서버에는 node 가 없어도 된다. 'dist' 는 .gitignore 대상이라 쓰지 않음)
// 실행: frontend 폴더에서 `node console/build.mjs` (npm ci 로 rolldown 이 설치돼 있어야 함). 기존 build-content-template.mjs 와 별개.
import {rolldown} from 'rolldown';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const dashboard=path.join(here,'..','src','content','dashboard');
// 기존 화면 지도(SatelliteMap)가 쓰는 CSS. 기존 화면과 같은 모양이 되도록 그대로 붙인다.
const MAP_CSS=['pf-live.css','ui-tools.css','v2-survey.css','v3-workbench.css','boundary-allocation.css'];
const BOUNDARY_ORIGINAL=path.join(dashboard,'boundary-allocation.mjs'),BOUNDARY_CACHE=path.join(here,'src','boundary-cache.mjs');

await mkdir(path.join(here,'build'),{recursive:true});
const bundle=await rolldown({
 input:path.join(here,'src','main.js'),
 platform:'browser',
 transform:{jsx:{runtime:'automatic'},define:{'process.env.NODE_ENV':'"production"'}},
 plugins:[{
  name:'console-stubs',
  // 지도 부품이 함께 불러오는 카드·표 부품(기존 화면 틀 전용)은 지도에 쓰이지 않으므로 빈 부품으로 바꾼다.
  resolveId(source){
   if(source.endsWith('/data-app-public.jsx')||source.endsWith('/data-component.jsx'))return '\0console-stub';
   if(source.endsWith('.css'))return '\0console-css';
   // 경계 검사 결과를 필지마다 한 번만 계산하도록, 콘솔에 묶이는 boundary-allocation.mjs import 는 모두 기억 기능을 붙인 파일로 돌린다.
   if(source==='console-original:boundary-allocation')return BOUNDARY_ORIGINAL;
   if(source.endsWith('/boundary-allocation.mjs'))return BOUNDARY_CACHE;
   return null;
  },
  load(id){
   if(id==='\0console-stub')return 'const Empty=()=>null;export const DataComponent=Empty,EvidenceChart=Empty,DataTable=Empty;';
   if(id==='\0console-css')return 'export default "";';
   return null;
  },
 }],
});
await bundle.write({file:path.join(here,'build','console.js'),format:'esm',minify:true,sourcemap:false});
await bundle.close();
const css=[await readFile(path.join(here,'src','console.css'),'utf8')];
for(const name of MAP_CSS)css.push(`/* ---- 기존 화면 지도 CSS: src/content/dashboard/${name} ---- */\n`+await readFile(path.join(dashboard,name),'utf8'));
await writeFile(path.join(here,'build','console.css'),css.join('\n'));
console.log('콘솔 화면을 만들었습니다: frontend/console/build/console.js, console.css');
