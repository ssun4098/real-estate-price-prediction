import test from 'node:test';
import assert from 'node:assert/strict';
import {revenueFormula,wonM2ToEokPyeong,M2_PER_PYEONG} from './src/content/dashboard/price-formula.mjs';

test('unit conversion reconciles median and mean with assigned plan, including adjustment',()=>{
 for(const method of ['median','mean'])for(const adjustment of [0,-10,25]){
  const unit={median:6500000,mean:7000000},area=12894.75,total=unit[method]*area*(1+adjustment/100);
  const f=revenueFormula({unitPriceStats:unit,comparableWon:total},{supplyAreaM2:area,capacitySupplyAreaM2:12960},{revenueMethod:method,revenueAdjustmentPct:adjustment});
  assert.equal(f.ready,true);assert.equal(f.remainderAreaM2,65.25);
  assert(Math.abs(f.unitEokPyeong*f.areaPyeong-f.totalEok)<1e-9);
 }
 assert.equal(wonM2ToEokPyeong(3e8/M2_PER_PYEONG),3);
});
test('missing inputs and mismatched stored totals never show a false equality',()=>{
 assert.equal(revenueFormula().ready,false);
 assert.equal(revenueFormula({unitPriceStats:{median:100},comparableWon:100},{supplyAreaM2:2}).ready,false);
 assert.equal(revenueFormula({unitPriceStats:{median:100},comparableWon:0},{supplyAreaM2:0}).ready,true);
 assert.equal(wonM2ToEokPyeong(null),null);
});
