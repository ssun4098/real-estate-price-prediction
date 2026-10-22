import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanPortfolioValue,portfolioMeta} from './portfolio-samples.mjs';

test('portfolio snapshots retain canonical revenue, coordinates, results and evidence times without mutating input',()=>{
 const input={snapshot:{inputs:{project:{asOf:'2026-10-11'},parcels:[{pnu:'A',geometry:{type:'Point',coordinates:[127.123,37.345]},areaM2:100}],comparables:{revenueCases:[{id:'r',priceManwon:50000,lon:127.1,lat:37.3,geocodingState:'verified',refinedAddress:'안산시 장상동',realtimeOnly:true}]}},results:{revenue:{representativeWon:123456789},development:{units:620},validation:{status:'complete'}}},displayState:{survey:{facilities:{items:[{id:'school',distanceKm:1.2,lon:127,lat:37}],queriedAt:'2026-10-11T08:00:00Z'}},address:'안산시 장상동'},sourceUrl:'https://www.data.go.kr/data/15013205/standard.do',capturedAt:'2026-10-11T08:05:00Z'};
 const output=cleanPortfolioValue(input);
 assert.deepEqual(output,input);assert.notEqual(output,input);assert.notEqual(output.snapshot,input.snapshot);
 output.snapshot.inputs.parcels[0].areaM2=200;assert.equal(input.snapshot.inputs.parcels[0].areaM2,100);
});
test('portfolio scrub removes nested credentials, raw transport and authenticated URLs while keeping safe source URLs',()=>{
 const source={credentials:{apiKey:'SECRET_1'},api_key:'SECRET_2',key:'SECRET_3',accessToken:'SECRET_4',apiUrl:'https://api.example.com/list?serviceKey=SECRET_5',signedUrl:'https://host.example/path?X-Amz-Signature=SECRET_6',tile:'https://api.vworld.kr/req/wmts/1.0.0/SECRET_7/Satellite/1/1/1.jpeg',rawResponse:{anything:'SECRET_8'},requestHeaders:{authorization:'SECRET_9'},response:{body:'SECRET_10'},nested:{client_secret:'SECRET_11',raw_payload:'SECRET_12',code:'A01',status:'empty'},authUrl:'https://user:SECRET_13@example.com/',message:'호출 실패 https://api.example.com/?api_key=SECRET_14',tokenMessage:'Bearer SECRET_15',sourceUrl:'https://www.data.go.kr/data/15013205/standard.do'};
 const clean=cleanPortfolioValue(source),text=JSON.stringify(clean);
 assert.equal(text.includes('SECRET_'),false);assert.equal(clean.apiUrl,undefined);assert.equal(clean.tile,undefined);assert.deepEqual(clean.nested,{code:'A01',status:'empty'});assert.equal(clean.sourceUrl,source.sourceUrl);assert.equal(clean.message,'호출 실패 [인증 URL 제외]');assert.equal(source.credentials.apiKey,'SECRET_1');
});
test('portfolio sanitizer permits shared objects but rejects cycles and strips prototype fields',()=>{
 const shared={status:'ready'};assert.deepEqual(cleanPortfolioValue({a:shared,b:shared}),{a:{status:'ready'},b:{status:'ready'}});
 const cyclic={};cyclic.self=cyclic;assert.throws(()=>cleanPortfolioValue(cyclic),/순환 참조/);
 const clean=cleanPortfolioValue(JSON.parse('{"__proto__":{"leaked":true},"constructor":{"secret":"X"},"id":"safe"}'));
 assert.deepEqual(clean,{id:'safe'});assert.equal({}.leaked,undefined);
});
test('portfolio metadata maps captured date and counts unique valid parcels without interpreting result values',()=>{
 const envelope={id:'p-1',name:'장상동 기준안',capturedAt:'2026-10-11T08:05:00Z',snapshot:{inputs:{project:{scenario:'기준안'},parcels:[{pnu:'A'},{pnu:'A'},{pnu:'B'},null,'bad',{}]},results:{revenue:{representativeWon:null}}}};
 assert.deepEqual(portfolioMeta(envelope),{id:'p-1',name:'장상동 기준안',scenario:'기준안',createdAt:envelope.capturedAt,capturedAt:envelope.capturedAt,parcelCount:3,readOnly:true,persistencePolicy:'portfolio_frozen_v1'});
 assert.equal(portfolioMeta({snapshot:{inputs:{parcels:'bad'}}}).parcelCount,0);
 assert.equal(portfolioMeta({...envelope,isDefault:true}).isDefault,true);
 assert.equal(portfolioMeta({...envelope,isDefault:false}).isDefault,false);
});

test('portfolio display preserves the chosen tab and map viewport exactly',()=>{
 const displayState={viewState:{main:'finance',tab:'parcels'},mapView:{lon:126.87536,lat:37.35761,z:18}};
 assert.deepEqual(cleanPortfolioValue({displayState}).displayState,displayState);
});
