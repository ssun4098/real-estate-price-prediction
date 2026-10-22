// Cross-runtime consistency checksum, not an authentication signature. It binds
// saved raw polygons to their calculated evidence; Python still recomputes them.
export const BOUNDARY_BINDING_ALGORITHM='fnv1a64-ieee754-v1';
const fields=['version','pnu','status','source','attributeBasis','parcelFeature','parcelGeometry','sourceFeatures','registerAreaM2','parcelGeometryAreaM2','coverageRatio','overlapAreaM2','gapAreaM2','parts','policy'];
function typedCanonical(value){
 if(value==null)return 'z';
 if(typeof value==='boolean')return value?'t':'f';
 if(typeof value==='number'){
  if(!Number.isFinite(value))throw new Error('경계 근거에 유효하지 않은 숫자가 있습니다.');
  const buffer=new ArrayBuffer(8),view=new DataView(buffer);view.setFloat64(0,value,false);
  return 'n'+Array.from(new Uint8Array(buffer),byte=>byte.toString(16).padStart(2,'0')).join('');
 }
 if(typeof value==='string')return 's'+JSON.stringify(value);
 if(Array.isArray(value))return 'a['+value.map(typedCanonical).join(',')+']';
 if(typeof value==='object')return 'o{'+Object.keys(value).sort().map(key=>typedCanonical(key)+':'+typedCanonical(value[key])).join(',')+'}';
 throw new Error('경계 근거 형식을 확인하세요.');
}
export function boundaryEvidenceChecksum(allocation={}){
 const payload=Object.fromEntries(fields.map(field=>[field,allocation[field]??null]));
 let hash=14695981039346656037n;
 for(const byte of new TextEncoder().encode(typedCanonical(payload)))hash=BigInt.asUintN(64,(hash^BigInt(byte))*1099511628211n);
 return hash.toString(16).padStart(16,'0');
}
export function boundaryEvidenceMatches(allocation){
 try{return allocation?.evidenceBinding?.algorithm===BOUNDARY_BINDING_ALGORITHM&&allocation.evidenceBinding.value===boundaryEvidenceChecksum(allocation);}catch{return false;}
}
