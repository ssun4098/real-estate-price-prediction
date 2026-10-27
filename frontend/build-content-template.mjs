// 화면 파일(build/V6.template.html)에서 "화면 내용" 부분만 다시 만들어 끼워 넣는다.
//
// 왜 필요한가
//   V6.template.html 은 Data 앱 도구로 만든 파일이라 안에 두 덩어리의 스크립트가 들어 있다.
//     1) 런타임 (보호 영역: 상단 바, 차트, 공통 부품)   ← 건드리지 않는다
//     2) 화면 내용 (src/content/ 의 코드를 묶은 것)      ← 이 스크립트가 다시 만든다
//   npm run build(vite)로 통째로 다시 만들면 런타임까지 바뀌므로, 내용 부분만 바꾼다.
//
// 사용법 (frontend 폴더에서, npm ci 후)
//   node build-content-template.mjs            → build/V6.template.html 을 고쳐 쓴다
//   node build-content-template.mjs --check    → 쓰지 않고 바뀔지만 알려 준다
//
// 제한: src/content 의 CSS 를 바꾼 경우에는 이 스크립트로 반영되지 않는다 (기존 CSS 클래스만 쓸 것).
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { rolldown } from "rolldown";

const root = dirname(fileURLToPath(import.meta.url));
const templatePath = join(root, "build", "V6.template.html");
const checkOnly = process.argv.includes("--check");

const MODULE_START = "(function(module,exports,require){\n'use strict';\n";
const MODULE_END = "\n})(__dataAuthoredModule,__dataAuthoredModule.exports,__dataAuthoredRequire);";
const CONTENT_MARK = 'const runtime = globalThis.CodexDataAppRuntime;';
const EXTERNAL = ["react", "react/jsx-runtime", "react-dom", "react-dom/client", "@openai/data-app"];

// 1) 템플릿에서 '화면 내용' 스크립트를 찾는다.
const template = readFileSync(templatePath, "utf8");
const scripts = [...template.matchAll(/<script src="data:text\/javascript;charset=utf-8;base64,([^"]+)"/g)];
const content = scripts
  .map((match) => ({ match, code: Buffer.from(match[1], "base64").toString("utf8") }))
  .find(({ code }) => code.includes(CONTENT_MARK));
if (!content) throw new Error("템플릿에서 화면 내용 스크립트를 찾지 못했습니다.");
const start = content.code.indexOf(MODULE_START);
const end = content.code.indexOf(MODULE_END);
if (start < 0 || end < start) throw new Error("화면 내용 스크립트의 모양이 예상과 다릅니다.");

// 2) src/content 를 CommonJS 한 덩어리로 묶는다. 런타임이 주는 모듈(react, 공통 부품)은 밖에서 받는다.
const ENTRY = "\0content-entry";
const bundle = await rolldown({
  input: ENTRY,
  external: EXTERNAL,
  platform: "browser",
  transform: { jsx: { runtime: "automatic" } },
  plugins: [{
    name: "data-app-content",
    resolveId(source, importer) {
      if (source === ENTRY) return ENTRY;
      if (source.endsWith("/data-app-public.jsx")) return { id: "@openai/data-app", external: true };
      if (source.endsWith(".css")) return "\0empty-css";  // CSS 는 템플릿에 이미 들어 있다
      if (importer === ENTRY) return join(root, source);
      return null;
    },
    load(id) {
      if (id === ENTRY) {
        return `export {DashboardContent} from "src/content/dashboard/DashboardContent.jsx";\n` +
               `export function ReportContent() { return null; }\n`;
      }
      if (id === "\0empty-css") return "";
      return null;
    },
  }],
});
const { output } = await bundle.generate({ format: "cjs", exports: "named" });
await bundle.close();
const body = output[0].code;
if (!/exports\.DashboardContent\b/.test(body)) throw new Error("묶은 결과에 DashboardContent 가 없습니다.");

// 3) 같은 자리에 끼워 넣고 템플릿을 다시 쓴다.
const newCode = content.code.slice(0, start + MODULE_START.length) + body + content.code.slice(end);
const encoded = Buffer.from(newCode, "utf8").toString("base64");
const updated = template.replace(content.match[1], () => encoded);
if (updated === template) {
  console.log("바뀐 내용이 없습니다.");
} else if (checkOnly) {
  console.log("화면 내용이 바뀝니다 (--check 이라 쓰지 않음).");
} else {
  writeFileSync(templatePath, updated);
  console.log(`화면 내용을 다시 만들어 넣었습니다: ${templatePath}`);
}
