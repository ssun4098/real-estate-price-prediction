// 콘솔 빌드 전용: 기존 boundary-allocation.mjs 를 그대로 다시 내보내되,
// validateBoundaryAllocation 결과만 필지 객체마다 한 번 계산해 기억한다. (기존 파일은 고치지 않음)
//
// 왜: 이 검사는 필지마다 저장된 경계 원자료(필지 하나에 수십 KB, 27필지면 약 2MB)를 통째로 문자열로 바꿔 비교한다.
// 화면 곳곳(토지 사례 판정, 토지비 계산, 지도 경계 표시, 필지 목록)이 같은 필지를 계속 다시 검사해서,
// 필지 하나를 누를 때 일반 PC에서 수 초~수십 초 동안 화면이 멈췄다 (2026-10-30 사용자 PC에서 측정: 31초).
// 검사 결과는 필지 객체 내용으로만 정해지고, 화면은 필지가 바뀌면 새 객체를 만들므로 객체 단위로 기억해도 결과가 같다.
// 빌드(console/build.mjs)가 콘솔에 묶이는 모든 'boundary-allocation.mjs' import 를 이 파일로 돌린다.
export * from 'console-original:boundary-allocation';
import {validateBoundaryAllocation as checkOnce} from 'console-original:boundary-allocation';

const remembered=new WeakMap();
export function validateBoundaryAllocation(parcel={}){
 if(!parcel||typeof parcel!=='object')return checkOnce(parcel);
 let result=remembered.get(parcel);
 if(!result){result=checkOnce(parcel);remembered.set(parcel,result);}
 return result;
}
