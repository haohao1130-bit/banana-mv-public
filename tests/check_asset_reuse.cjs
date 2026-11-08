const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const html=fs.readFileSync('banana_mv/web/index.html','utf8');
const code=html.slice(html.indexOf('const assetFingerprints='),html.indexOf('\n}',html.indexOf('const assetFingerprints='))+2);
const assets=new Map(),uploads=[],lookups=[];
const context=vm.createContext({crypto:webcrypto,Uint8Array,WeakMap,api:async(url,options)=>{
 if(url==='api/assets/lookup'){const key=JSON.parse(options.body).sha256;lookups.push(key);return {asset:assets.get(key)||null};}
 uploads.push(options.body.name);
 const hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',await options.body.arrayBuffer())).toString('hex');
 const asset={id:'asset'+uploads.length};assets.set(hash,asset);return asset;
}});
vm.runInContext(code,context);
const file=(name,content)=>({name,size:Buffer.byteLength(content),arrayBuffer:async()=>Uint8Array.from(Buffer.from(content)).buffer});
async function upload(f){context.file=f;return vm.runInContext('upload(file)',context);}
(async()=>{
 const original=file('photo.png','same image');
 const first=await upload(original);
 assert.equal((await upload(original)).id,first.id);
 assert.equal((await upload(file('renamed.png','same image'))).id,first.id);
 assert.equal(uploads.length,1);
 assert.equal(lookups.length,3);
 assert.notEqual((await upload(file('photo.png','replacement'))).id,first.id);
 assert.equal(uploads.length,2);
 // A fresh page retains no browser cache but still reuses backend storage.
 const fresh=vm.createContext({crypto:webcrypto,Uint8Array,WeakMap,api:context.api,file:file('photo.png','same image')});
 vm.runInContext(code,fresh);assert.equal((await vm.runInContext('upload(file)',fresh)).id,first.id);
 assets.clear();await upload(original);assert.equal(uploads.length,3);
 console.log('Asset reuse UI checks passed');
})().catch(e=>{console.error(e);process.exit(1);});
