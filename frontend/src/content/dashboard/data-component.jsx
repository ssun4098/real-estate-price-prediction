import React from 'react';
import {DataComponent as RuntimeDataComponent,EvidenceChart as RuntimeEvidenceChart} from '../../data-app-public.jsx';

// 화면의 모든 카드는 이 DataComponent 를 쓴다 (런타임 것을 감싼 것).
// 카드 오른쪽 위 '⋯' 메뉴의 'Copy data'(자료 복사) 항목을 모든 카드에서 뺀다 (2026-10-29 요청).
// onCopy 를 false 로 주면 런타임이 복사 항목을 만들지 않는다. 런타임(보호 영역)은 고치지 않는다.
// 'Copy link'는 공개 배포 화면에서만 나온다.
export function DataComponent(props){
 return <RuntimeDataComponent onCopy={false} {...props}/>;
}

// 차트 카드(EvidenceChart)도 같은 방식. 런타임이 복사 항목을 한 설정으로 켜고 끄기 때문에 'Copy as image'도 함께 빠진다.
// 차트 이미지는 메뉴의 'Export chart'로 내려받을 수 있다.
export function EvidenceChart(props){
 return <RuntimeEvidenceChart onCopy={false} {...props}/>;
}
