// 콘솔 화면 빌드: src/main.js(+ 기존 화면의 계산 규칙 모듈 import)를 build/console.js 하나로 묶고, CSS 를 build/ 로 복사한다.
// (build/ 결과는 git 에 함께 올린다. 서버에는 node 가 없어도 된다. 'dist' 는 .gitignore 대상이라 쓰지 않음)
// 실행: frontend 폴더에서 `node console/build.mjs` (npm ci 로 rolldown 이 설치돼 있어야 함). 기존 build-content-template.mjs 와 별개.
import {rolldown} from 'rolldown';
import {copyFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
await mkdir(path.join(here,'build'),{recursive:true});
const bundle=await rolldown({input:path.join(here,'src','main.js'),platform:'browser'});
await bundle.write({file:path.join(here,'build','console.js'),format:'esm',minify:true,sourcemap:false});
await bundle.close();
await copyFile(path.join(here,'src','console.css'),path.join(here,'build','console.css'));
console.log('콘솔 화면을 만들었습니다: frontend/console/build/console.js, console.css');
