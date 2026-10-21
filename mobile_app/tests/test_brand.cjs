const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function harness() {
 const store=new Map(); const ctx={mobile_app:{brand:{}}, sessionStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)}, frappe:{boot:{mobile_app_brands:['Siya Ayurveda','Seedfit']},provide(){},session:{user:'agent'},set_route(...route){this.route=route;}}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/mobile_app_brand.js'),'utf8'),ctx);
 return ctx;
}
test('brand selection follows workspace links; all clears stale filters',()=>{
 const c=harness(); c.mobile_app.brand.set('Seedfit'); c.mobile_app.brand.open(['List','Mobile App User']);
 assert.equal(c.frappe.route_options.custom_app_brand,'Seedfit');
 c.mobile_app.brand.set('');c.mobile_app.brand.open(['List','Mobile App User']);assert.equal(c.frappe.route_options.name[0],'is');assert.equal(c.frappe.route_options.custom_app_brand,undefined);
});
test('unknown brand is not silently assigned to Siya',()=>{
 const c=harness();c.mobile_app.brand.set('Unclassified');assert.equal(c.mobile_app.brand.matches(''),true);assert.equal(c.mobile_app.brand.matches('Siya Ayurveda'),false);
 c.mobile_app.brand.set('Siya Ayurveda');assert.equal(c.mobile_app.brand.matches(''),false);assert.equal(c.mobile_app.brand.matches('Seedfit'),false);
});
test('calendar navigation does not leak list filters',()=>{
 const c=harness();c.mobile_app.brand.set('Seedfit');c.mobile_app.brand.open(['doctor-clinical']);assert.equal(c.frappe.route_options,null);assert.equal(c.mobile_app.brand.get(),'Seedfit');
});

test('new master brands refresh filters and escape option labels', async()=>{
 const c=harness();c.frappe.xcall=async()=>['Siya Ayurveda','Seedfit','Third & "App"'];
 await c.mobile_app.brand.refresh(); c.mobile_app.brand.set('Third & "App"');
 c.mobile_app.brand.open(['List','Mobile App User']);
 assert.equal(c.frappe.route_options.custom_app_brand,'Third & "App"');
 assert.ok(c.mobile_app.brand.options().includes('Third &amp; &quot;App&quot;'));
 assert.equal(c.mobile_app.brand.matches('Seedfit'),false);
 c.frappe.xcall=async()=>['Siya Ayurveda','Seedfit'];await c.mobile_app.brand.refresh();
 assert.equal(c.mobile_app.brand.get(),'');
});
