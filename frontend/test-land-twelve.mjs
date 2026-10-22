import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {calculateLand} from './src/content/dashboard/land-comparison.mjs';

const directory=path.dirname(fileURLToPath(import.meta.url));
const python=process.env.PF_TEST_PYTHON||'python';
const script=`import json,sys
sys.path.insert(0,sys.argv[1]);from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[1]).parent/'tests'))
from test_land_twelve import twelve_fixtures
from pf_engine import analyze
json.dump([dict(scenario,land=analyze(scenario['input'],partial=True)['results']['land']) for scenario in twelve_fixtures()],sys.stdout,ensure_ascii=False,allow_nan=False)`;
const response=spawnSync(python,['-X','utf8','-c',script,path.resolve(directory,'../backend')],{encoding:'utf8',maxBuffer:20e6});
assert.equal(response.status,0,response.stderr);
const scenarios=JSON.parse(response.stdout);
function compare(a,b,field){
 if(typeof a==='number'&&typeof b==='number')assert.ok(Math.abs(a-b)<=Math.max(1e-7,Math.abs(b)*1e-12),`${field}: ${a} != ${b}`);
 else if(Array.isArray(a)&&Array.isArray(b)){assert.equal(a.length,b.length,field);a.forEach((value,i)=>compare(value,b[i],field+'.'+i));}
 else if(a&&b&&typeof a==='object'&&typeof b==='object'){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),field);for(const key of Object.keys(a))compare(a[key],b[key],field+'.'+key);}
 else assert.deepEqual(a,b,field);
}
for(const scenario of scenarios)test('12-group Python/HTML parity: '+scenario.name,()=>{
 const js=calculateLand(scenario.input),py=scenario.land;
 compare(js.representativeWon,py.comparableWon,'representativeWon');
 for(const field of ['groups','referenceGroups','caseDecisions','parcelProfiles','parcelAssignments','partialRepresentativeWon','matchingPolicy','ruleVersion','referencePolicy'])compare(js[field],py[field],field);
});
test('HTML does not mutate source attributes or reuse stale supplied eligibility',()=>{
 const input=structuredClone(scenarios[12].input),before=structuredClone(input);
 calculateLand(input);assert.deepEqual(input,before);
 input.comparables.landCases[0].cancelled=true;input.comparables.landCases[0].eligible=true;
 assert.equal(calculateLand(input).caseDecisions[0].eligible,false);
});
