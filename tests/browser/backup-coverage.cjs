const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'), out=path.join(root,'.github/screenshots');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.setDefaultTimeout(10000);page.on('pageerror',e=>{errors.push(String(e));console.error('pageerror',String(e));});
 
 let content='# custom backup policy\n/etc/asterisk\n',saved=0;
 await page.route('**/*',route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  if(u.origin!=='http://backup-preview.test') return route.abort();
  if(p.endsWith('/api/v1/auth/session'))return route.fulfill({json:{user:'example-operator',hostname:'example-node',csrf:'fixture'}});
  if(p.endsWith('/api/v1/auth/ws-ticket'))return route.fulfill({json:{ticket:'fixture'}});
  if(p.endsWith('/api/v1/system'))return route.fulfill({json:{hostname:'example-node',os:'Debian GNU/Linux 13',kernel:'example',uptime:86400,asl_web_ui:'1.2',certificate:null}});
  if(p.endsWith('/api/v1/backups'))return route.fulfill({json:{local:[],cloud:{configured:false,node:null,reason:'Not configured in this example',sync:null},cloud_max:2000000,server:'https://backup.allstarlink.org',directory:'/var/asl-backups'}});
  if(p.endsWith('/api/v1/backups/include-list')){
   if(req.method()==='PUT'){content=req.postDataJSON().content;saved++;return route.fulfill({json:{hash:'updated'}});}
   return route.fulfill({json:{content,exists:true,hash:'fixture',missing_allmon3:content.includes('/etc/allmon3\n')?[]:['/etc/allmon3/favorites','/etc/allmon3/audio']}});
  }
  if(p.includes('/api/'))throw Error('Unexpected API '+req.method()+' '+p);
  const file=path.join(root,'frontend/dist',p==='/asl-web-ui/'?'index.html':p.replace(/^\/asl-web-ui\//,''));
  return fs.existsSync(file)&&fs.statSync(file).isFile()?route.fulfill({path:file}):route.fulfill({status:404});
 });
 await page.routeWebSocket('**/api/v1/ws/events*',()=>{});
 await page.goto('http://backup-preview.test/asl-web-ui/#/backups/settings');
 await page.getByText(/Some Allmon3 data is not included in backups/).waitFor();
 await page.screenshot({path:path.join(out,'backup-coverage-desktop.png')});
 await page.getByRole('textbox',{name:'Include list',exact:true}).fill(content+'/etc/allmon3\n');
 await page.getByRole('button',{name:'Save',exact:true}).click();
 await page.getByText(/Saved\./).waitFor();
 assert.equal(saved,1);assert.equal(await page.getByText(/Some Allmon3 data is not included in backups/).count(),0);
 await page.getByRole('tab',{name:'This server',exact:true}).click();
 await page.getByText(/stop Allmon3 at idle/).waitFor();
 await page.screenshot({path:path.join(out,'backup-idle-desktop.png')});
 assert.deepEqual(errors,[]);
 console.log('PASS: custom coverage warning, include-list edit/readback clears warning, idle/size guidance; two desktop captures; no real backup/restore.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
