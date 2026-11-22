// usage: node shot.js <html_dir> <out_dir> [width=900] [height]
// height 없음 : 내용 높이로 잘라 찍음 (잘림·가로스크롤·글자 넘침 확인)
// height 있음 : 노션 임베드 프레임 크기 그대로 찍음 (예 838 625). fill = 프레임 중 그림이 차지하는 비율
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
const [dir,out,w='900',fh]=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:+w,height:+(fh||700)}});
for(const f of fs.readdirSync(dir).filter(x=>x.endsWith('.html'))){
 await p.goto('file://'+path.resolve(dir,f));await p.waitForTimeout(1500);
 const r=await p.evaluate(()=>{const s=document.querySelector('.diagram-container svg');const R=s.getBoundingClientRect();let over=0;
  document.querySelectorAll('[data-node-id]').forEach(g=>{const rc=g.querySelector('rect:not(.c-mask)');if(!rc)return;const B=rc.getBoundingClientRect();
  g.querySelectorAll('text').forEach(t=>{const T=t.getBoundingClientRect();if(T.left<B.left-1||T.right>B.right+1)over++;});});
  const vb=s.viewBox.baseVal,vw=innerWidth,vh=innerHeight,k=Math.min(vw/vb.width,vh/vb.height);
  return {h:Math.ceil(R.height),sw:document.documentElement.scrollWidth,fit:s.getAttribute('data-green-fit'),textOverflow:over,
   drawn:[Math.round(vb.width*k),Math.round(vb.height*k)],fill:+((vb.width*k*vb.height*k)/(vw*vh)).toFixed(2)};});
 if(!fh){await p.setViewportSize({width:+w,height:Math.min(r.h,r.drawn[1])});await p.waitForTimeout(300);}
 await p.screenshot({path:path.join(out,f.replace('.html','.png'))});console.log(f,JSON.stringify(r));
 if(!fh) await p.setViewportSize({width:+w,height:700});}
await b.close();})();
