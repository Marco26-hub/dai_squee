const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import { readdir } from 'node:fs/promises';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const base=process.env.TEST_URL||'http://127.0.0.1:8791';
const failures=[];
for(const width of [320,768,1440]){
 await page.setViewportSize({width,height:900});
 for(const file of (await readdir('en')).filter(f=>f.endsWith('.html'))){
  await page.goto(base+'/en/'+file);
  await page.locator('body').waitFor();
  await page.evaluate(()=>document.fonts.ready);
  const check=await page.evaluate(()=>{
   const badImages=[...document.images].filter(i=>!i.loading||i.loading!=='lazy').filter(i=>i.complete&&!i.naturalWidth).map(i=>i.src);
   return {overflow:document.documentElement.scrollWidth>innerWidth+1,badImages,
    switchCount:document.querySelectorAll('.language-switch').length,lang:document.documentElement.lang,
    italianLinks:[...document.querySelectorAll('a[href]')].filter(a=>a.origin===location.origin&&!a.pathname.startsWith('/en/')&&!a.pathname.startsWith('/api/')&&!a.pathname.startsWith('/assets/')&&!a.hasAttribute('data-language-link')&&!a.pathname.endsWith('/admin.html')).map(a=>a.getAttribute('href'))};
  });
  if(check.overflow||check.badImages.length||check.switchCount!==1||check.lang!=='en'||check.italianLinks.length)failures.push({file,width,...check});
 }
 await page.goto(base+'/en/');
 await page.evaluate(async()=>{for(let y=0;y<document.body.scrollHeight;y+=600){scrollTo(0,y);await new Promise(r=>setTimeout(r,30));}scrollTo(0,0);});
 await page.waitForTimeout(500);
 await page.screenshot({path:'/tmp/daisquee-en-'+width+'.png',fullPage:true});
}
await page.goto(base+'/en/book.html?apartment=Michele&guests=2');
await page.locator('#calendarStatus').filter({hasText:'Availability updated'}).waitFor();
const date=new Date();date.setDate(date.getDate()+40);const a=date.toISOString().slice(0,10);date.setDate(date.getDate()+3);const b=date.toISOString().slice(0,10);
await page.locator('#arrivalDate').fill(a);await page.locator('#arrivalDate').dispatchEvent('change');
await page.locator('#departureDate').fill(b);await page.locator('#departureDate').dispatchEvent('change');
await page.locator('#quoteButton').click();
await page.locator('#checkoutStatus').filter({hasText:'Instant booking is not available'}).waitFor();
await page.screenshot({path:'/tmp/daisquee-en-book.png',fullPage:true});
await page.locator('[data-request-info]').click();
if(await page.locator('#modalStayType').inputValue()!=='Michele')failures.push('Enquiry apartment mapping');
if(!await page.locator('#bookingModal').isVisible())failures.push('Enquiry dialog did not open');
await page.route('**/api/availability',route=>route.abort());
await page.goto(base+'/en/book.html');
await page.locator('#calendarStatus.error').waitFor();
if(await page.locator('.calendar-day:not(:disabled)').count())failures.push('Availability failed open');
await page.unroute('**/api/availability');
await page.route('**/api/apartment-photos',route=>route.abort());
await page.route('**/api/config',route=>route.abort());
await page.goto(base+'/en/suite-max.html');
if(!await page.locator('.room-cover img').evaluate(img=>img.complete&&img.naturalWidth>0))failures.push('Original photo fallback unavailable');
if(await page.locator('[data-portal]:visible').count())failures.push('Unconfigured portal links visible');
console.log(JSON.stringify({pages:26,viewports:3,failures,errors},null,2));
await browser.close();
if(failures.length||errors.length)process.exitCode=1;
