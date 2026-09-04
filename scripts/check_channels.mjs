const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
import {readFile} from 'node:fs/promises';
const base=process.env.TEST_URL||'http://127.0.0.1:8791';
const local=new URL(base).hostname==='127.0.0.1';
const file=local?'.local-data/admin-access.txt':'.local-data/production-admin-access.txt';
const password=(await readFile(file,'utf8')).split('Password: ')[1].split('\n')[0];
const browser=await chromium.launch();
const page=await browser.newPage();
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
try {
 await page.goto(base+'/admin.html');
 await page.locator('#loginForm [name="password"]').fill(password);
 await page.locator('#loginForm button').click();
 await page.locator('#app').waitFor();
 await page.locator('[data-tab="channels"]').click();
 await page.locator('#channelConnections form').first().waitFor();
 if(await page.locator('#channelConnections form').count()!==2)throw Error('Missing channel forms');
 if(local){
  const form=page.locator('[data-channel="airbnb"]');
  await form.locator('[name="listing_id"]').fill('test-unit');
  const saved=page.waitForResponse(r=>r.url().endsWith('/channels/suite-max/airbnb')&&r.request().method()==='PATCH');
  await form.locator('button').click();
  if((await saved).status()!==200)throw Error('Save failed');
  await page.locator('#notice').filter({hasText:'Predisposizione salvata'}).waitFor();
  await page.locator('#refreshChannels').click();
  await page.waitForResponse(r=>r.url().endsWith('/channels'));
  if(await form.locator('[name="listing_id"]').inputValue()!=='test-unit')throw Error('Persistence failed');
  await form.locator('[name="listing_id"]').fill('');
  const cleared=page.waitForResponse(r=>r.url().endsWith('/channels/suite-max/airbnb')&&r.request().method()==='PATCH');
  await form.locator('button').click();
  await cleared;
 }
 for(const width of [320,768,1440]){
  await page.setViewportSize({width,height:900});
  await page.screenshot({path:'/tmp/dai-channels-'+width+'.png',fullPage:true});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width);
 }
 if(errors.length)throw Error(errors.join(', '));
 console.log(JSON.stringify({environment:local?'local':'production',channelForms:2,roomMappings:3,viewports:[320,768,1440],errors,productionWrites:false}));
}finally{await browser.close();}

