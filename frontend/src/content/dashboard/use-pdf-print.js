import {useCallback,useEffect,useRef,useState} from 'react';
import {flushSync} from 'react-dom';
import {captureScreen,buildScreenPdf} from './screen-pdf.mjs';
import './screen-pdf.css';

export const PDF_VIEWS=Object.freeze([
 {main:'survey',tab:'parcels',label:'필지'},
 {main:'survey',tab:'regulation',label:'규제'},
 {main:'survey',tab:'location',label:'입지'},
 {main:'survey',tab:'development',label:'개발규모'},
 {main:'finance',tab:'development',label:'사업 수지분석'},
]);
const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
const scrollState=root=>[root,...root.querySelectorAll('*')].filter(n=>n.scrollHeight>n.clientHeight||n.scrollWidth>n.clientWidth).map(n=>({node:n,id:n.id,classes:n.className,top:n.scrollTop,left:n.scrollLeft}));
function restoreScroll(root,entries){
 for(const item of entries){
  let node=item.node.isConnected?item.node:null;
  if(!node&&item.id)node=[...root.querySelectorAll('[id]')].find(n=>n.id===item.id);
  if(!node&&typeof item.classes==='string'&&item.classes)node=[...root.querySelectorAll('[class]')].find(n=>n.className===item.classes);
  if(node){node.scrollTop=item.top;node.scrollLeft=item.left;}
 }
}
async function settle(root,signal){
 if(document.fonts?.ready){
  let timer;
  try{await Promise.race([document.fonts.ready,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('화면 글꼴 로딩이 지연되고 있습니다. 잠시 후 다시 저장하세요.')),30000);})]);}
  finally{clearTimeout(timer);}
 }
 let previous='',stable=0;
 const started=performance.now();
 while(performance.now()-started<4500){
  if(signal.aborted)throw new Error('PDF 저장이 취소되었습니다.');
  await frame();
  const charts=[...root.querySelectorAll('.recharts-surface,.live-box svg,.live-map')];
  const signature=charts.map(n=>n.outerHTML).join('');
  stable=signature===previous?stable+1:0;previous=signature;
  if(stable>=5&&performance.now()-started>450)break;
 }
}

// Capture the authored screen before print styles can replace its layout.
// Temporary view changes never write inputs, public samples or saved defaults.
export function usePdfPrint(rootRef,{blocked,blockedReason,onNotice,onError,viewState,onViewState,projectName}){
 const [printing,setPrinting]=useState(false),[printedAt,setPrintedAt]=useState(''),[printProgress,setPrintProgress]=useState(''),[pdfDownload,setPdfDownload]=useState(null);
 useEffect(()=>()=>{if(pdfDownload)URL.revokeObjectURL(pdfDownload.url);},[pdfDownload]);
 const state=useRef(),running=useRef(null);state.current={blocked,blockedReason,onNotice,onError,viewState,onViewState,projectName};
 useEffect(()=>()=>running.current?.abort(),[]);
 const startPrint=useCallback(async()=>{
  const current=state.current,root=rootRef.current;
  if(running.current)return;
  if(current.blocked||!root){current.onNotice?.(current.blockedReason||'조회·계산을 마친 뒤 PDF로 저장하세요.');return;}
  const controller=new AbortController();running.current=controller;
  const originalView={...current.viewState},originalStyle=root.getAttribute('style'),originalInert=root.inert,originalScroll=scrollState(root),focused=document.activeElement;
  const rect=root.getBoundingClientRect(),compact=window.innerWidth<1101;
  const width=compact?1280:Math.round(rect.width),height=compact?800:Math.round(rect.height);
  const timestamp=new Date(),pages=[],resourceCache=new Map();
  let completed=false;
  try{
   setPdfDownload(null);
   root.classList.add('v6-pdf-capture');if(compact)root.classList.add('v6-pdf-desktop');
   root.style.width=width+'px';root.style.height=height+'px';root.style.minHeight='0';root.style.maxWidth='none';root.style.overflow='hidden';root.inert=true;
   flushSync(()=>{setPrinting(true);setPrintedAt(timestamp.toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}));});
   for(const [index,view]of PDF_VIEWS.entries()){
    setPrintProgress((index+1)+'/5 · '+view.label);
    flushSync(()=>current.onViewState({main:view.main,tab:view.tab}));
    await settle(root,controller.signal);
    if(view.main===originalView.main&&(view.main==='finance'||view.tab===originalView.tab))restoreScroll(root,originalScroll);
    pages.push(await captureScreen(root,{width,height,pixelRatio:4,backgroundColor:'#101114',signal:controller.signal,resourceCache}));
   }
   const bytes=buildScreenPdf(pages),url=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
   const link=document.createElement('a'),name=(current.projectName||'개발사업성 분석').replace(/[\\/:*?"<>|\x00-\x1f]/g,' ').trim().slice(0,70);
   link.download=name+'_V6_고해상도_화면보고서_5페이지_'+new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(timestamp)+'.pdf';link.href=url;
   setPdfDownload({url,name:link.download});
   document.body.appendChild(link);link.click();link.remove();completed=true;
  }catch(error){(current.onError||current.onNotice)?.('PDF 저장 실패: '+(error?.message||'화면을 준비하지 못했습니다. 잠시 후 다시 시도하세요.'));}
  finally{
   if(originalStyle===null)root.removeAttribute('style');else root.setAttribute('style',originalStyle);
   root.classList.remove('v6-pdf-capture','v6-pdf-desktop');root.inert=originalInert;
   flushSync(()=>{current.onViewState(originalView);setPrinting(false);setPrintProgress('');});
   await frame();restoreScroll(root,originalScroll);if(focused?.isConnected)focused.focus?.({preventScroll:true});running.current=null;
   if(completed)current.onNotice?.('무손실 PNG · 4배 해상도의 A4 가로 PDF 5페이지를 준비했습니다. 다운로드가 시작되지 않으면 PDF 받기를 누르세요.');
  }
 },[rootRef]);
 return {printing,printedAt,printProgress,startPrint,pdfDownload,dismissPdfDownload:()=>setPdfDownload(null)};
}
