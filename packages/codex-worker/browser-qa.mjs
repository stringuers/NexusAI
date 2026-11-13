import { chromium } from 'playwright';
const browser = await chromium.launch({chromiumSandbox:true});
const checks=[];
try {
 for (const [name,viewport] of [['desktop',{width:1280,height:900}],['mobile',{width:390,height:844}]]) {
  const context=await browser.newContext({viewport,serviceWorkers:'block'});
  await context.route('**/*',route=>{
   const url=new URL(route.request().url());
   return url.origin==='http://127.0.0.1:8765'?route.continue():route.abort();
  });
  const page=await context.newPage();
  const errors=[];
  page.on('pageerror',error=>{if(errors.length<20)errors.push(error.message.slice(0,200))});
  const response=await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle',timeout:15000});
  checks.push({name:`${name}: page loads`,passed:response?.ok()===true});
  checks.push({name:`${name}: no horizontal overflow`,passed:await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)});
  checks.push({name:`${name}: heading visible`,passed:await page.locator('h1').first().isVisible()});
  checks.push({name:`${name}: navigation visible`,passed:await page.locator('nav').first().isVisible()});
  checks.push({name:`${name}: images loaded`,passed:await page.evaluate(()=>[...document.images].every(image=>image.complete&&image.naturalWidth>0))});
  checks.push({name:`${name}: no JavaScript exceptions`,passed:errors.length===0,errors});
  await page.screenshot({path:`/output/${name}.png`});
  await context.close();
 }
 process.stdout.write(JSON.stringify({passed:checks.every(c=>c.passed),checks,scope:'Chromium desktop/mobile checks; no application-specific unit-test or build claim'}));
} finally {await browser.close();}
