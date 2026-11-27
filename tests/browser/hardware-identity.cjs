const {chromium}=require('playwright'), fs=require('fs'), path=require('path'), assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'), out=path.join(root,'.github/screenshots');
 const original=JSON.parse(fs.readFileSync(path.join(__dirname,'hardware-fixture.json')));
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const results=[];
 try {
  const scenarios=[{name:'board-swap',firmware:'110U-V223',advanced:true}];
  for(const s of scenarios){
   const state=structuredClone(original);state.sr110u_tool=!s.missing;state.settings.CURRENT_SR_ADVANCED=s.advanced?'Enabled':'Disabled';
   state.settings.CURRENT_PORT='/dev/ttyAMA0';
   const modules=s.multi?[{port:'/dev/ttyUSB0',speed:'9600',firmware:'110U-V223'},{port:'/dev/serial0',speed:'9600',firmware:s.firmware,aliases:['/dev/serial0','/dev/ttyAMA0']}]:[{port:'/dev/serial0',speed:'9600',firmware:s.firmware,aliases:['/dev/serial0','/dev/ttyAMA0']}];
   let swapped=false, scans=0;
   const ctx=await browser.newContext({viewport:{width:1440,height:1100},locale:'en-US',deviceScaleFactor:1});
   const page=await ctx.newPage(), errors=[], mutations=[];page.on('pageerror',e=>errors.push(String(e)));
   await page.route('**/*',route=>{
    const u=new URL(route.request().url()),p=u.pathname;
    if(u.origin!=='http://hardware-preview.test')return route.abort();
    if(route.request().method()!=='GET'&&!p.endsWith('/auth/ws-ticket')&&!p.endsWith('/sa818/detect')){mutations.push(p);return route.abort();}
    if(p.endsWith('/api/v1/auth/session'))return route.fulfill({json:{user:'example-operator',hostname:'example-node',csrf:'fixture'}});
    if(p.endsWith('/api/v1/auth/ws-ticket'))return route.fulfill({json:{ticket:'fixture'}});
    if(p.endsWith('/api/v1/system'))return route.fulfill({json:{hostname:'example-node',os:'Debian GNU/Linux 13',kernel:'example',uptime:86400,asl_web_ui:'1.2',certificate:null}});
    if(p.endsWith('/api/v1/sa818/detect')){if(route.request().method()==='POST'){swapped=true;scans++;}return route.fulfill({json:{found:modules.map(m=>({...m,firmware:swapped?'SA818S_V1.2':m.firmware})),probed:modules.map(m=>m.port),reachable:true,saved:true}});}
    if(p.endsWith('/api/v1/sa818'))return route.fulfill({json:state});
    if(p.includes('/api/'))throw new Error('Unexpected API '+p);
    const file=path.join(root,'frontend/dist',p==='/asl-web-ui/'?'index.html':p.replace(/^\/asl-web-ui\//,''));
    return fs.existsSync(file)&&fs.statSync(file).isFile()?route.fulfill({path:file}):route.fulfill({status:404});
   });
   await page.routeWebSocket('**/api/v1/ws/events*',()=>{});
   await page.goto('http://hardware-preview.test/asl-web-ui/#/'+(s.route||'hardware/radio'));
   await page.locator('#sa818-rx').waitFor();
   assert.equal(await page.getByRole('tab',{name:'Radio programming'}).count(),1);
   const body=await page.locator('body').innerText();
   assert.ok(!body.includes('Module identity is unverified'));
   assert.ok(!body.includes('saved connection does not reach it'));
   assert.equal(await page.locator('#sr-power').isEnabled(),true);
   assert.equal(await page.getByRole('button',{name:'Look again',exact:true}).isEnabled(),true);
   await page.getByRole('button',{name:'Look again',exact:true}).click();
   await page.getByText(/SA818S module found/).waitFor();
   assert.equal(await page.locator('#sr-power').isDisabled(),true);
   assert.equal(scans,1);
   assert.deepEqual(errors,[]);assert.deepEqual(mutations,[]);results.push({scenario:s.name,passed:true,noProgrammingCalls:true});await ctx.close();
  }
 }finally{await browser.close();}
 console.log(results);
})().catch(e=>{console.error(e);process.exit(1)});
