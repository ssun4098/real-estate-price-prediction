import {cloneNode} from './pdf-vendor/clone-node.mjs';
import {nodeToDataURL,createImage} from './pdf-vendor/util.mjs';

const encoder = new TextEncoder();
const A4_LONG = 841.889764, A4_SHORT = 595.275591;
const BACKGROUND = '#101214';
const MAX_PIXELS = 40_000_000;
const PNG_SIGNATURE = [137,80,78,71,13,10,26,10];
const cssUrls = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*?))\s*\)/g;
const imageProperties = ['background-image','mask-image','-webkit-mask-image','border-image-source','list-style-image','content','filter','clip-path','fill','stroke'];
const aborted = signal => { if (signal?.aborted) throw signal.reason || new DOMException('PDF 저장을 취소했습니다.','AbortError'); };
const error = message => new Error('PDF 저장: '+message);
const familyName = text => text.trim().replace(/^['"]|['"]$/g,'').toLowerCase();

function bounded(promise, ms, signal, message) {
  aborted(signal);
  return new Promise((resolve,reject)=>{
    const finish=(fn,value)=>{clearTimeout(timer);signal?.removeEventListener('abort',cancel);fn(value);};
    const cancel=()=>finish(reject,signal.reason||new DOMException('PDF 저장을 취소했습니다.','AbortError'));
    const timer=setTimeout(()=>finish(reject,error(message)),ms);
    signal?.addEventListener('abort',cancel,{once:true});
    promise.then(value=>finish(resolve,value),cause=>finish(reject,cause));
  });
}

async function asDataUrl(blob) {
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(error('이미지·글꼴 파일을 읽지 못했습니다.'));reader.readAsDataURL(blob);
  });
}

// Cache keys retain the complete URL, including map tile query parameters.
// Supply one Map for all five calls; no persistent visitor/browser cache is used.
async function embedUrl(url,base,options,kind='image') {
  if (!url || url.startsWith('#') || url.startsWith('data:')) return url;
  let absolute;
  try {
    const resolved=new URL(url,base),documentUrl=new URL(base);
    if(resolved.hash && resolved.origin===documentUrl.origin && resolved.pathname===documentUrl.pathname && resolved.search===documentUrl.search)return resolved.hash;
    absolute=resolved.href;
  } catch {throw error('이미지·글꼴 주소가 올바르지 않습니다.');}
  const key=kind+':'+absolute,cache=options.resourceCache;
  if(cache.has(key))return cache.get(key);
  const operation=(async()=>{
    aborted(options.signal);
    const response=await bounded(fetch(absolute,{signal:options.signal,credentials:'same-origin',cache:'force-cache'}),options.timeoutMs,options.signal,'이미지·글꼴을 불러오는 시간이 초과됐습니다.');
    if(!response.ok)throw error('이미지·글꼴을 불러오지 못했습니다. 화면의 자료 로딩 후 다시 시도하세요.');
    const blob=await response.blob();
    if(!blob.size || (kind==='image' && !/^image\//i.test(blob.type)))throw error('지도·이미지 응답을 확인할 수 없습니다.');
    return asDataUrl(blob);
  })();
  cache.set(key,operation);
  try{return await operation;}catch(cause){cache.delete(key);throw cause;}
}

async function embedCss(text,base,options,kind='image') {
  const matches=[...text.matchAll(cssUrls)];
  let result=text;
  for(let i=matches.length-1;i>=0;i--){
    const match=matches[i],url=(match[1]??match[2]??match[3]??'').trim();
    const embedded=await embedUrl(url,base,options,kind);
    result=result.slice(0,match.index)+`url("${embedded.replaceAll('"','%22')}")`+result.slice(match.index+match[0].length);
  }
  return result;
}

async function decodeImage(url,doc,options) {
  const image=doc.createElement('img');image.decoding='sync';
  const loaded=image.decode?null:new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(error('지도·이미지를 렌더링하지 못했습니다. 빈 화면으로 저장하지 않았습니다.'));});
  image.src=url;
  await bounded(image.decode?image.decode():loaded,options.timeoutMs,options.signal,'이미지 렌더링 시간이 초과됐습니다.').catch(()=>{throw error('지도·이미지를 렌더링하지 못했습니다. 빈 화면으로 저장하지 않았습니다.');});
  if(!image.naturalWidth || !image.naturalHeight)throw error('빈 지도·이미지를 확인했습니다.');
}

function visibleForCapture(node) {
  const element=node.nodeType===1?node:node.parentElement;
  if(element?.closest('[data-pdf-exclude]'))return false;
  // Retain SVG defs/clip paths even when non-rendered; ordinary hidden panels
  // (including the former receipt print view) do not belong to the screenshot.
  return !element || element.namespaceURI==='http://www.w3.org/2000/svg' || element.ownerDocument.defaultView.getComputedStyle(element).display!=='none';
}

function collectPairs(source,clone,pairs) {
  pairs.push([source,clone]);
  // The library appends pseudo-element styles after cloned children. Preserve
  // this initial child order; canvas/video become images and have no children.
  if(['CANVAS','VIDEO','IFRAME'].includes(source.tagName))return;
  const children=[...source.children].filter(child=>source.namespaceURI==='http://www.w3.org/2000/svg'||visibleForCapture(child));
  children.forEach((child,index)=>{if(clone.children[index])collectPairs(child,clone.children[index],pairs);});
}

function copyControlValue(source,clone) {
  clone.removeAttribute?.('inert');
  // Export locks the live screen with inert. Removing disabled only from this
  // detached clone restores native range/checkbox colors without enabling the
  // actual UI or changing any value in React.
  if('disabled' in clone){clone.disabled=false;clone.removeAttribute('disabled');}
  if(source.tagName==='INPUT'){
    clone.value=source.value;clone.setAttribute('value',source.value);
    clone.checked=source.checked;clone.toggleAttribute('checked',source.checked);
    clone.indeterminate=source.indeterminate;
  }else if(source.tagName==='TEXTAREA'){
    clone.value=source.value;clone.textContent=source.value;
  }else if(source.tagName==='SELECT'){
    [...source.options].forEach((option,index)=>{const target=clone.options[index];if(target){target.selected=option.selected;target.toggleAttribute('selected',option.selected);}});
    clone.value=source.value;
  }
}

function preserveScroll(source,clone) {
  if(!source.scrollTop && !source.scrollLeft)return;
  // SVG foreignObject does not serialize scroll offsets. Translate only the
  // cloned contents inside their original clipping viewport instead. Layout
  // dimensions and the live page's scroll positions never change.
  clone.style.overflow='hidden';
  for(const child of clone.children){
    if(child.tagName==='STYLE')continue;
    const transform=child.style.transform;
    child.style.transform=`translate(${-source.scrollLeft}px, ${-source.scrollTop}px)${transform&&transform!=='none'?' '+transform:''}`;
  }
}

function hasUsedCharacters(unicodeRange,characters) {
  if(!unicodeRange)return true;
  return unicodeRange.split(',').some(part=>{
    const match=part.trim().match(/^U\+([0-9A-F?]+)(?:-([0-9A-F]+))?$/i);
    if(!match)return true;
    const start=parseInt(match[1].replaceAll('?','0'),16),end=parseInt(match[2]||match[1].replaceAll('?','F'),16);
    return [...characters].some(code=>code>=start&&code<=end);
  });
}

async function fontCss(source,pairs,options) {
  if(options.fontEmbedCSS!==undefined)return options.fontEmbedCSS;
  const doc=source.ownerDocument,win=doc.defaultView,families=new Set(),characters=new Set([...source.textContent].map(c=>c.codePointAt(0)));
  for(const [original] of pairs){
    win.getComputedStyle(original).fontFamily.split(',').forEach(name=>families.add(familyName(name)));
    if('value' in original)for(const c of String(original.value))characters.add(c.codePointAt(0));
  }
  const collected=[],visited=new Set();
  async function collectText(text,base){
    for(const match of text.matchAll(/@font-face\s*\{[^}]*\}/gi))collected.push({text:match[0],base});
    for(const match of text.matchAll(/@import\s+(?:url\(\s*)?["']([^"']+)["']\s*\)?[^;]*;/gi))await collectRemote(new URL(match[1],base).href);
  }
  async function collectRemote(url){
    if(visited.has(url))return;visited.add(url);
    const key='font-css:'+url;
    if(!options.resourceCache.has(key))options.resourceCache.set(key,(async()=>{
      const response=await bounded(fetch(url,{signal:options.signal,credentials:'same-origin',cache:'force-cache'}),options.timeoutMs,options.signal,'글꼴 스타일을 불러오는 시간이 초과됐습니다.');
      if(!response.ok)throw error('화면 글꼴 스타일을 불러오지 못했습니다.');return response.text();
    })());
    await collectText(await options.resourceCache.get(key),url);
  }
  async function collectRules(rules,base){
    for(const rule of rules){
      if(rule.type===5)collected.push({text:rule.cssText,base});
      else if(rule.type===3)await collectRemote(new URL(rule.href,base).href);
      else if(rule.cssRules)await collectRules(rule.cssRules,base);
    }
  }
  for(const sheet of doc.styleSheets){
    if(sheet.disabled)continue;
    try{await collectRules(sheet.cssRules,sheet.href||doc.baseURI);}
    catch(cause){if(sheet.href)await collectRemote(sheet.href);else throw cause;}
  }
  const output=[];
  for(const rule of collected){
    const family=rule.text.match(/font-family\s*:\s*([^;}]*)/i)?.[1];
    if(!family || !families.has(familyName(family)))continue;
    const range=rule.text.match(/unicode-range\s*:\s*([^;}]*)/i)?.[1];
    if(hasUsedCharacters(range,characters))output.push(await embedCss(rule.text,rule.base,options,'font'));
  }
  return [...new Set(output)].join('\n');
}

/** Capture the current, rendered authored screen without mutating it.
 * width/height are CSS pixels, normally the node's measured dimensions.
 * Reuse resourceCache:new Map() across pages. data-pdf-exclude is respected.
 */
export async function captureScreen(node,{width,height,pixelRatio=4,backgroundColor=BACKGROUND,signal,timeoutMs=30000,resourceCache=new Map(),fontEmbedCSS}={}) {
  if(!node?.ownerDocument || !node.isConnected)throw error('저장할 화면을 찾을 수 없습니다.');
  const doc=node.ownerDocument,win=doc.defaultView,rect=node.getBoundingClientRect();
  width=Math.ceil(width??rect.width);height=Math.ceil(height??rect.height);
  if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0||!Number.isFinite(pixelRatio)||pixelRatio<=0)throw error('화면 크기를 확인하세요.');
  if(width*height*pixelRatio**2>MAX_PIXELS)throw error('4배 해상도 화면이 4천만 픽셀을 초과합니다. 브라우저 창 크기를 줄인 뒤 다시 저장하세요.');
  const options={signal,timeoutMs,resourceCache,fontEmbedCSS};aborted(signal);
  if(doc.fonts?.ready)await bounded(doc.fonts.ready,timeoutMs,signal,'글꼴 로딩 시간이 초과됐습니다.');
  // Omitting font-size from the library's copy list avoids its built-in font
  // rounding. Exact computed sizes are copied below and retained as inline CSS.
  const includeStyleProperties=[...win.getComputedStyle(node)].filter(name=>name!=='font-size');
  const clone=await bounded(cloneNode(node,{filter:visibleForCapture,includeStyleProperties},true),timeoutMs*2,signal,'화면 복사 시간이 초과됐습니다.');
  const pairs=[];collectPairs(node,clone,pairs);
  const tasks=[];
  for(const [source,target] of pairs){
    if(source!==node && !visibleForCapture(source)){target.remove();continue;}
    copyControlValue(source,target);
    if(target.style){
      const computed=win.getComputedStyle(source);target.style.fontSize=computed.fontSize;
      // html-to-image deep-clones SVG trees; their descendants also need the
      // computed CSS from the live page (Recharts labels, fills, strokes).
      if(source.namespaceURI==='http://www.w3.org/2000/svg')for(const property of computed)target.style.setProperty(property,computed.getPropertyValue(property));
      for(const property of imageProperties){
        const value=target.style.getPropertyValue(property);
        if(value.includes('url('))tasks.push(async()=>target.style.setProperty(property,await embedCss(value,doc.baseURI,options)));
      }
    }
    const tag=source.tagName?.toLowerCase();
    if(tag==='img'||tag==='image')tasks.push(async()=>{
      const url=tag==='img'?(source.currentSrc||source.src):(source.href?.baseVal||source.getAttribute('href')||source.getAttribute('xlink:href'));
      if(!url)throw error('비어 있는 지도·이미지를 확인했습니다.');
      const embedded=await embedUrl(url,source.baseURI||doc.baseURI,options);
      await decodeImage(embedded,doc,options);
      if(tag==='img'){target.removeAttribute('srcset');target.removeAttribute('sizes');target.loading='eager';target.src=embedded;}
      else{target.setAttribute('href',embedded);target.removeAttribute('xlink:href');}
    });
    preserveScroll(source,target);
  }
  let next=0;
  await Promise.all(Array.from({length:Math.min(8,tasks.length)},async()=>{while(next<tasks.length){aborted(signal);await tasks[next++]();}}));
  const fonts=await fontCss(node,pairs,options);aborted(signal);
  const stage=doc.createElement('div');
  stage.inert=true;
  stage.setAttribute('aria-hidden','true');stage.style.cssText=`position:fixed;left:-100000px;top:0;width:${width}px;height:${height}px;pointer-events:none;z-index:-2147483647;`;
  Object.assign(clone.style,{width:`${width}px`,height:`${height}px`,maxWidth:'none',maxHeight:'none',position:'relative',top:'0',left:'0',margin:'0',transform:'none',boxSizing:'border-box'});
  stage.appendChild(clone);doc.body.appendChild(stage);
  let canvas,rendered;
  try{
    // The clone already has exact styles, control states, embedded images and
    // scroll translations. Serialize it directly: a second toCanvas clone
    // would recompute styles and can change native controls/font inheritance.
    if(fonts){const fontStyle=doc.createElement('style');fontStyle.textContent=fonts;clone.insertBefore(fontStyle,clone.firstChild);}
    const dataUrl=await nodeToDataURL(clone,width,height);
    rendered=await bounded(createImage(dataUrl),timeoutMs*2,signal,'화면 렌더링 시간이 초과됐습니다.');
    canvas=doc.createElement('canvas');canvas.width=Math.round(width*pixelRatio);canvas.height=Math.round(height*pixelRatio);
    const context=canvas.getContext('2d',{alpha:false,willReadFrequently:true});if(!context)throw error('화면 렌더링 영역을 만들지 못했습니다.');
    context.fillStyle=backgroundColor;context.fillRect(0,0,canvas.width,canvas.height);
    context.drawImage(rendered,0,0,canvas.width,canvas.height);
    aborted(signal);
    if(canvas.width!==Math.round(width*pixelRatio)||canvas.height!==Math.round(height*pixelRatio))throw error('화면이 잘리지 않았는지 확인할 수 없습니다.');
    const blob=await bounded(new Promise((resolve,reject)=>{try{canvas.toBlob(value=>value?resolve(value):reject(error('무손실 PNG 이미지를 만들지 못했습니다.')),'image/png');}catch{reject(error('지도·이미지의 보안 설정으로 PDF를 만들지 못했습니다.'));}}),timeoutMs*2,signal,'PNG 저장 시간이 초과됐습니다.');
    if(blob.type!=='image/png')throw error('무손실 PNG 형식을 지원하는 브라우저에서 다시 저장하세요.');
    const pngBytes=new Uint8Array(await blob.arrayBuffer());
    validatePng(pngBytes,canvas.width,canvas.height);
    // Only 64 rows are read at a time. The full 4x RGBA and RGB images are
    // never retained alongside the canvas; all five pages keep compressed data.
    let row=0;
    const rgbDeflateBytes=await bounded(deflateRgbChunks(()=>{
      if(row>=canvas.height)return null;
      const rows=Math.min(64,canvas.height-row),rgba=context.getImageData(0,row,canvas.width,rows).data;
      row+=rows;return opaqueRgb(rgba);
    },signal),timeoutMs*2,signal,'무손실 PDF 압축 시간이 초과됐습니다.');
    aborted(signal);
    return {pngBytes,rgbDeflateBytes,width:canvas.width,height:canvas.height};
  }finally{
    // Explicitly release each large backing store before the next page starts.
    if(canvas){canvas.width=0;canvas.height=0;}
    if(rendered)rendered.src='';
    pairs.length=0;tasks.length=0;stage.remove();
  }
}

function opaqueRgb(rgba){
  if(!(rgba instanceof Uint8Array)&&!(rgba instanceof Uint8ClampedArray))throw error('RGBA 픽셀 배열이 필요합니다.');
  if(!rgba.length||rgba.length%4!==0)throw error('RGBA 픽셀 배열의 길이가 올바르지 않습니다.');
  const rgb=new Uint8Array(rgba.length/4*3);
  for(let source=0,target=0;source<rgba.length;source+=4){
    if(rgba[source+3]!==255)throw error('투명 픽셀을 배경과 합성한 뒤 무손실 PDF로 저장해야 합니다.');
    rgb[target++]=rgba[source];rgb[target++]=rgba[source+1];rgb[target++]=rgba[source+2];
  }
  return rgb;
}

async function deflateRgbChunks(nextChunk,signal){
  if(typeof CompressionStream!=='function')throw error('이 브라우저는 무손실 PDF 압축을 지원하지 않습니다. 최신 Chrome 또는 Edge에서 저장하세요.');
  aborted(signal);
  const input=new ReadableStream({pull(controller){
    try{aborted(signal);const chunk=nextChunk();if(chunk===null)controller.close();else controller.enqueue(chunk);}
    catch(cause){controller.error(cause);}
  }});
  return new Uint8Array(await new Response(input.pipeThrough(new CompressionStream('deflate'))).arrayBuffer());
}

/** Losslessly encode opaque 8-bit RGBA pixels as PDF-compatible zlib RGB.
 * Exported independently so pixel preservation can be verified byte for byte.
 */
export async function encodeOpaqueRgb(rgba,{signal}={}){
  if((!(rgba instanceof Uint8Array)&&!(rgba instanceof Uint8ClampedArray))||!rgba.length||rgba.length%4!==0)throw error('RGBA 픽셀 배열의 길이가 올바르지 않습니다.');
  if(rgba.length/4>MAX_PIXELS)throw error('RGBA 픽셀 배열이 4천만 픽셀을 초과합니다.');
  let offset=0;
  return deflateRgbChunks(()=>{
    if(offset>=rgba.length)return null;
    const end=Math.min(offset+65536,rgba.length),rgb=opaqueRgb(rgba.subarray(offset,end));offset=end;return rgb;
  },signal);
}

function validatePng(bytes,width,height){
  if(!(bytes instanceof Uint8Array)||bytes.length<45||PNG_SIGNATURE.some((value,index)=>bytes[index]!==value))throw error('유효한 무손실 PNG 화면 이미지가 필요합니다.');
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  if(view.getUint32(8)!==13||view.getUint32(12)!==0x49484452||view.getUint32(16)!==width||view.getUint32(20)!==height)throw error('PNG 이미지 크기와 PDF 화면 크기가 일치하지 않습니다.');
  if(bytes[24]!==8||![2,6].includes(bytes[25])||bytes[26]!==0||bytes[27]!==0||bytes[28]!==0)throw error('지원하는 8비트 RGB PNG 화면 이미지가 필요합니다.');
  let offset=8,hasData=false,ended=false;
  while(offset+12<=bytes.length){
    const size=view.getUint32(offset),kind=view.getUint32(offset+4),end=offset+size+12;
    if(end>bytes.length)throw error('PNG 이미지 파일이 완전하지 않습니다.');
    if(kind===0x49444154&&size>0)hasData=true;
    if(kind===0x49454e44){if(size!==0||end!==bytes.length)throw error('PNG 이미지 파일의 끝이 올바르지 않습니다.');ended=true;break;}
    offset=end;
  }
  if(!hasData||!ended)throw error('PNG 이미지 파일이 완전하지 않습니다.');
}

const pdfNumber=value=>Number(value.toFixed(5)).toString();
function bytesOf(value){return typeof value==='string'?encoder.encode(value):value;}
function concat(chunks){const size=chunks.reduce((n,item)=>n+item.length,0),result=new Uint8Array(size);let at=0;for(const item of chunks){result.set(item,at);at+=item.length;}return result;}

/** One lossless RGB/Flate PDF, exactly five uncropped A4 pages: landscape by default (existing screen),
 *  portrait with {portrait:true} (분석 콘솔, 2026-10-30 요청: 세로 화면을 세로 A4 에). */
export function buildScreenPdf(pages, {portrait=false}={}) {
  const A4_WIDTH=portrait?A4_SHORT:A4_LONG, A4_HEIGHT=portrait?A4_LONG:A4_SHORT;
  if(!Array.isArray(pages)||pages.length!==5)throw error('사업 기본조사 4장과 수지분석 1장, 총 5장이 필요합니다.');
  for(const page of pages){
    if(!Number.isSafeInteger(page.width)||!Number.isSafeInteger(page.height)||page.width<=0||page.height<=0)throw error('화면 이미지 크기가 올바르지 않습니다.');
    if(page.width*page.height>MAX_PIXELS)throw error('화면 이미지가 4천만 픽셀을 초과합니다.');
    validatePng(page.pngBytes,page.width,page.height);
    const stream=page.rgbDeflateBytes;
    if(!(stream instanceof Uint8Array)||stream.length<6||(stream[0]&15)!==8||(stream[0]>>4)>7||((stream[0]<<8)+stream[1])%31!==0||(stream[1]&32)!==0)throw error('유효한 무손실 RGB 압축 데이터가 필요합니다.');
  }
  const objects=[];
  objects.push('<< /Type /Catalog /Pages 2 0 R >>');
  objects.push(`<< /Type /Pages /Count 5 /Kids [${pages.map((_,i)=>`${3+i*3} 0 R`).join(' ')}] >>`);
  pages.forEach((page,index)=>{
    const pageId=3+index*3,imageId=pageId+1,contentId=pageId+2;
    const scale=Math.min(A4_WIDTH/page.width,A4_HEIGHT/page.height),w=page.width*scale,h=page.height*scale,x=(A4_WIDTH-w)/2,y=portrait?A4_HEIGHT-h:(A4_HEIGHT-h)/2;  // 세로(콘솔): 짧은 화면은 위쪽에 붙인다
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pdfNumber(A4_WIDTH)} ${pdfNumber(A4_HEIGHT)}] /Resources << /XObject << /Screen ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`);
    objects.push([bytesOf(`<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Interpolate false /Length ${page.rgbDeflateBytes.length} >>\nstream\n`),page.rgbDeflateBytes,bytesOf('\nendstream')]);
    const commands=`q\n${pdfNumber(16/255)} ${pdfNumber(18/255)} ${pdfNumber(20/255)} rg\n0 0 ${pdfNumber(A4_WIDTH)} ${pdfNumber(A4_HEIGHT)} re f\n${[w,0,0,h,x,y].map(pdfNumber).join(' ')} cm\n/Screen Do\nQ\n`;
    objects.push(`<< /Length ${bytesOf(commands).length} >>\nstream\n${commands}endstream`);
  });
  const chunks=[bytesOf('%PDF-1.4\n'),new Uint8Array([0x25,0xe2,0xe3,0xcf,0xd3,0x0a])],offsets=[0];
  let position=chunks.reduce((n,c)=>n+c.length,0);
  objects.forEach((object,index)=>{
    offsets.push(position);
    for(const chunk of [bytesOf(`${index+1} 0 obj\n`),...(Array.isArray(object)?object:[bytesOf(object)]),bytesOf('\nendobj\n')]){chunks.push(chunk);position+=chunk.length;}
  });
  const xref=position;
  chunks.push(bytesOf(`xref\n0 ${objects.length+1}\n0000000000 65535 f \n${offsets.slice(1).map(offset=>`${String(offset).padStart(10,'0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`));
  return concat(chunks);
}
