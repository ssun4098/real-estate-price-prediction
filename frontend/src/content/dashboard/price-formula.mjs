import {AREA_FACTORS} from './ui-tools.mjs';

// Display the same population, area and price adjustment used by the engine.
export const M2_PER_PYEONG=AREA_FACTORS['평'];
export const wonM2ToEokPyeong=value=>Number.isFinite(value)?value*M2_PER_PYEONG/1e8:null;
export function revenueFormula(revenue={},development={},assumptions={}){
 const method=assumptions.revenueMethod||revenue.method||'median';
 const rawUnit=revenue.unitPriceStats?.[method],pct=assumptions.revenueAdjustmentPct??0;
 const areaM2=development.supplyAreaM2,capacity=development.capacitySupplyAreaM2;
 const valid=Number.isFinite(rawUnit)&&rawUnit>0&&Number.isFinite(areaM2)&&areaM2>=0&&Number.isFinite(pct)&&pct>-100;
 const adjustedUnit=valid?rawUnit*(1+pct/100):null,unitEokPyeong=wonM2ToEokPyeong(adjustedUnit),areaPyeong=valid?areaM2/M2_PER_PYEONG:null;
 const expectedWon=valid?adjustedUnit*areaM2:null,displayedWon=revenue.comparableWon;
 const matches=valid&&Number.isFinite(displayedWon)&&Math.abs(expectedWon-displayedWon)<=Math.max(1,Math.abs(displayedWon)*1e-10);
 return {method,rawUnitWonM2:rawUnit??null,adjustmentPct:pct,unitEokPyeong,areaM2:valid?areaM2:null,areaPyeong,totalEok:matches?displayedWon/1e8:null,ready:matches,
   capacityAreaM2:Number.isFinite(capacity)?capacity:null,remainderAreaM2:Number.isFinite(capacity)&&Number.isFinite(areaM2)?Math.max(0,capacity-areaM2):null};
}
