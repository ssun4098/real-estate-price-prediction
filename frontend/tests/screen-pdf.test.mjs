import test from 'node:test';
import assert from 'node:assert/strict';
import {deflateSync,inflateSync} from 'node:zlib';
import {buildScreenPdf,captureScreen,encodeOpaqueRgb} from '../src/content/dashboard/screen-pdf.mjs';

function crc32(bytes){let value=0xffffffff;for(const byte of bytes){value^=byte;for(let bit=0;bit<8;bit++)value=(value>>>1)^(value&1?0xedb88320:0);}return(value^0xffffffff)>>>0;}
function chunk(type,data){
  const head=Buffer.alloc(4),name=Buffer.from(type),crc=Buffer.alloc(4);head.writeUInt32BE(data.length);crc.writeUInt32BE(crc32(Buffer.concat([name,data])));
  return Buffer.concat([head,name,data,crc]);
}
function png(rgb,width,height){
  const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(width);ihdr.writeUInt32BE(height,4);ihdr[8]=8;ihdr[9]=2;
  const rows=Buffer.alloc((width*3+1)*height);
  for(let row=0;row<height;row++)rows.set(rgb.subarray(row*width*3,(row+1)*width*3),row*(width*3+1)+1);
  return new Uint8Array(Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),chunk('IDAT',deflateSync(rows)),chunk('IEND',Buffer.alloc(0))]));
}
const pages = () => [[16,10],[32,12],[9,19],[16,10],[16,18]].map(([width,height],page)=>{
  const rgb=new Uint8Array(width*height*3);for(let i=0;i<rgb.length;i++)rgb[i]=(i*13+page*51)%256;
  return {pngBytes:png(rgb,width,height),rgbDeflateBytes:new Uint8Array(deflateSync(rgb)),rgb,width,height};
});
const decode = bytes => new TextDecoder('latin1').decode(bytes);

test('binary PDF has exactly five A4 landscape pages in the supplied order',()=>{
  const inputs=pages(),pdf=buildScreenPdf(inputs),text=decode(pdf);
  assert.ok(pdf instanceof Uint8Array);
  assert.equal(text.match(/\/Type \/Page\b/g).length,5);
  assert.equal(text.match(/\/Count 5\b/g).length,1);
  assert.equal(text.match(/\/MediaBox \[0 0 841\.88976 595\.27559\]/g).length,5);
  assert.match(text,/\/Kids \[3 0 R 6 0 R 9 0 R 12 0 R 15 0 R\]/);
  for(let i=0;i<5;i++){
    const header=`${4+i*3} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${inputs[i].width} /Height ${inputs[i].height}`;
    const objectAt=Buffer.from(pdf).indexOf(Buffer.from(header));assert.ok(objectAt>0);
    const streamAt=Buffer.from(pdf).indexOf(Buffer.from('stream\n'),objectAt)+7;
    const stream=pdf.slice(streamAt,streamAt+inputs[i].rgbDeflateBytes.length);
    assert.deepEqual(stream,inputs[i].rgbDeflateBytes);
    assert.deepEqual(new Uint8Array(inflateSync(stream)),inputs[i].rgb);
  }
  assert.equal(text.match(/\/Filter \/FlateDecode/g).length,5);
  assert.equal(text.match(/\/Interpolate false/g).length,5);
  assert.doesNotMatch(text,/DCTDecode/);
});

test('xref contains actual byte offsets, including binary lossless streams',()=>{
  const pdf=buildScreenPdf(pages()),buffer=Buffer.from(pdf),text=decode(pdf);
  const xrefOffset=Number(text.match(/startxref\n(\d+)\n%%EOF/)[1]);
  assert.equal(buffer.subarray(xrefOffset,xrefOffset+5).toString(),'xref\n');
  const records=buffer.subarray(xrefOffset).toString().split('\n').slice(3,20);
  assert.equal(records.length,17);
  records.forEach((record,index)=>{
    const offset=Number(record.slice(0,10));assert.equal(buffer.subarray(offset,offset+`${index+1} 0 obj\n`.length).toString(),`${index+1} 0 obj\n`);
  });
});

test('all page matrices preserve aspect ratio and center without cropping',()=>{
  const inputs=pages(),text=decode(buildScreenPdf(inputs));
  const matrices=[...text.matchAll(/([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm\n\/Screen Do/g)];
  assert.equal(matrices.length,5);
  matrices.forEach((m,i)=>{
    const [w,h,x,y]=m.slice(1).map(Number);
    assert.ok(w<=841.889764+1e-5&&h<=595.275591+1e-5);
    assert.ok(x>=0&&y>=0);
    assert.ok(Math.abs(w/h-inputs[i].width/inputs[i].height)<1e-6);
    assert.ok(Math.abs(2*x+w-841.889764)<2e-5);
    assert.ok(Math.abs(2*y+h-595.275591)<2e-5);
  });
  assert.equal(text.match(/0\.06275 0\.07059 0\.07843 rg/g).length,5);
});

test('invalid or incomplete captures cannot produce a misleading PDF',()=>{
  assert.throws(()=>buildScreenPdf(pages().slice(0,4)),/총 5장/);
  assert.throws(()=>buildScreenPdf([...pages(),pages()[0]]),/총 5장/);
  const broken=pages();broken[2].pngBytes=new Uint8Array([1,2,3]);assert.throws(()=>buildScreenPdf(broken),/PNG/);
  const dimension=pages();dimension[2].height=0;assert.throws(()=>buildScreenPdf(dimension),/크기/);
  const notFinite=pages();notFinite[0].width=Infinity;assert.throws(()=>buildScreenPdf(notFinite),/크기/);
  const mismatch=pages();mismatch[0].width++;assert.throws(()=>buildScreenPdf(mismatch),/PNG 이미지 크기/);
  const truncated=pages();truncated[1].pngBytes=truncated[1].pngBytes.slice(0,-5);assert.throws(()=>buildScreenPdf(truncated),/완전하지/);
  const compressed=pages();compressed[0].rgbDeflateBytes=new Uint8Array([255,216,255,217]);assert.throws(()=>buildScreenPdf(compressed),/무손실 RGB/);
  const oversized=pages();oversized[0].width=10000;oversized[0].height=5000;assert.throws(()=>buildScreenPdf(oversized),/4천만 픽셀/);
});

test('capture rejects missing or detached screens before rendering',async()=>{
  await assert.rejects(captureScreen(null),/저장할 화면/);
  await assert.rejects(captureScreen({ownerDocument:{},isConnected:false}),/저장할 화면/);
});

test('opaque RGBA to compressed RGB round trip preserves every channel across stream chunks',async()=>{
  const pixels=70001,rgba=new Uint8ClampedArray(pixels*4),expected=new Uint8Array(pixels*3);
  for(let pixel=0;pixel<pixels;pixel++){
    const colors=[pixel%256,(pixel*7)%256,(pixel*19)%256];rgba.set([...colors,255],pixel*4);expected.set(colors,pixel*3);
  }
  const before=new Uint8ClampedArray(rgba),compressed=await encodeOpaqueRgb(rgba);
  assert.deepEqual(new Uint8Array(inflateSync(compressed)),expected);
  assert.deepEqual(rgba,before,'caller pixel data stays unchanged');
});

test('lossless encoder rejects alpha, malformed pixels, and cancellation',async()=>{
  await assert.rejects(encodeOpaqueRgb(new Uint8Array([1,2,3])),/RGBA/);
  await assert.rejects(encodeOpaqueRgb(new Uint8Array([1,2,3,128])),/투명 픽셀/);
  await assert.rejects(encodeOpaqueRgb(new Uint8Array()),/RGBA/);
  const controller=new AbortController();controller.abort();
  await assert.rejects(encodeOpaqueRgb(new Uint8Array([1,2,3,255]),{signal:controller.signal}),{name:'AbortError'});
});

test('PDF embeds the production compressor output with exact original pixels',async()=>{
  const expected=new Uint8Array([16,18,20,255,255,255,123,174,214,0,0,0]),rgba=new Uint8Array(16);
  for(let pixel=0;pixel<4;pixel++){rgba.set(expected.subarray(pixel*3,pixel*3+3),pixel*4);rgba[pixel*4+3]=255;}
  const page={width:2,height:2,pngBytes:png(expected,2,2),rgbDeflateBytes:await encodeOpaqueRgb(rgba)};
  const pdf=Buffer.from(buildScreenPdf(Array.from({length:5},()=>page)));
  const objectAt=pdf.indexOf(Buffer.from('4 0 obj\n')),streamAt=pdf.indexOf(Buffer.from('stream\n'),objectAt)+7;
  assert.deepEqual(new Uint8Array(inflateSync(pdf.subarray(streamAt,streamAt+page.rgbDeflateBytes.length))),expected);
});
