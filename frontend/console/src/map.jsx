// 지도: 기존 화면(/)의 지도 부품(SatelliteMap)을 그대로 가져와 쓴다.
// 필지 조회(/api/parcels), 클릭 선택·해제, 선택 필지 색칠, 용도지역 경계, 주변시설, 반경 표시가 모두 기존 화면과 같다.
// (2026-10-29 요청: 콘솔에서 따로 만든 지도는 클릭이 느리고 색칠 범위가 기존과 달라서 기존 코드를 그대로 쓰기로 함)
import React from 'react';
import {createRoot} from 'react-dom/client';
import {flushSync} from 'react-dom';
import {SatelliteMap} from '../../src/content/dashboard/pf-live-widgets.jsx';

let root=null;
// now: 필지를 누른 직후처럼 바로 화면에 반영해야 할 때 true
export function renderMap(element,props,{now=false}={}){
 if(!root)root=createRoot(element);
 const draw=()=>root.render(<SatelliteMap {...props}/>);
 if(now)flushSync(draw);else draw();
}
