import React from 'react';
import './saved-samples-bar.css';

function savedDate(value){
 const date=new Date(value);
 return value&&!Number.isNaN(date.getTime())?new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'}).format(date):'저장일 미확인';
}

export default function SavedSamplesBar({library,onSettings}){
 const {items=[],activeId,onSave,onLoad,saving,loading,disabled,notice,error,local}=library||{};
 const pending=!!saving||!!loading,locked=!!disabled||pending;
 return <section className="v6-samples-bar" aria-label="분석 저장 및 예시">
  {(error||notice)&&<span className={'v6-samples-message'+(error?' is-error':'')} role={error?'alert':'status'} title={error||notice}>{error||notice}</span>}
  <div className="v6-samples-controls">
   <button className="primary" type="button" disabled={locked||!onSave} onClick={()=>onSave?.()} title={local?'현재 화면의 분석 결과 저장':'현재 화면의 분석 결과를 이 브라우저에 저장'}>{saving?'저장 중…':'현재 저장'}</button>
   <button type="button" className="v6-samples-settings" onClick={onSettings} disabled={!onSettings}>설정·저장</button>
  </div>
  <div className="v6-samples-library">
   <span className="v6-samples-heading">예시</span>
   {items.length?<div className="v6-samples-list" role="list" aria-label="저장된 분석 목록" data-reviewed-rows>
    {items.map(item=><div className="v6-sample-item" role="listitem" key={item.id}>
     <button type="button" className={activeId===item.id?'is-active':undefined} disabled={pending||!onLoad} onClick={()=>onLoad?.(item.id)} aria-current={activeId===item.id?'true':undefined} aria-label={`${item.name} 분석 열기`} title={`${item.name} · ${Number.isFinite(item.parcelCount)?item.parcelCount+'필지 · ':''}${savedDate(item.capturedAt||item.createdAt)}`}>
      {loading===item.id?'여는 중…':item.name}
     </button>
    </div>)}
   </div>:<span className="v6-samples-empty">저장 후 표시</span>}
  </div>
 </section>;
}
