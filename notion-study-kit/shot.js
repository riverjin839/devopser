// usage: node shot.js <html_dir> <out_dir> [width=900]
// 노션 임베드 폭 기준으로 렌더 → 잘림·가로스크롤·글자 넘침 확인용 스크린샷
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
const [dir,out,w='900']=process.argv.slice(2);fs.mkdirSync(out,{recursive:true});
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:+w,height:700}});
for(const f of fs.readdirSync(dir).filter(x=>x.endsWith('.html'))){
 await p.goto('file://'+path.resolve(dir,f));await p.waitForTimeout(1500);
 const r=await p.evaluate(()=>{const s=document.querySelector('.diagram-container svg');const R=s.getBoundingClientRect();let over=0;
  document.querySelectorAll('[data-node-id]').forEach(g=>{const rc=g.querySelector('rect:not(.c-mask)');if(!rc)return;const B=rc.getBoundingClientRect();
  g.querySelectorAll('text').forEach(t=>{const T=t.getBoundingClientRect();if(T.left<B.left-1||T.right>B.right+1)over++;});});
  return {h:Math.ceil(R.height),sw:document.documentElement.scrollWidth,fit:s.getAttribute('data-green-fit'),textOverflow:over};});
 await p.setViewportSize({width:+w,height:r.h});await p.waitForTimeout(300);
 await p.screenshot({path:path.join(out,f.replace('.html','.png'))});console.log(f,JSON.stringify(r));
 await p.setViewportSize({width:+w,height:700});}
await b.close();})();
