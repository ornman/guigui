/* app.js — GG 适配器:桥接契约的前端侧绑定。
   生产:index.html 不引用任何 mock;后端未绑定时诚实报错(BRIDGE_MISSING),绝不回落假数据。
   开发:URL 带 ?dev=1(devshell / 浏览器联调)才动态注入 dev/mock.js,未实现的方法可经 GGMock 兜底。
   html.in-app 仅在真后端绑定时挂上(透明无边框窗口样式,见 index.html #app-overrides)。 */
(function(){
'use strict';
const SUBS={};
const DEV=new URLSearchParams(location.search).has('dev');
let mode=DEV?'dev':'connecting',raw=null,readyResolve=null;
const ready=new Promise(r=>readyResolve=r);

function bind(api){
  if(!api)return;
  raw=api;mode='real';
  document.documentElement.classList.add('in-app');
  readyResolve();
}
function tryBind(){
  if(window.guigui){bind(window.guigui);return true}
  if(window.pywebview&&window.pywebview.api){bind(window.pywebview.api);return true}
  return false;
}
if(tryBind()){
  /* 真后端已在(同步注入的别名) */
}else if(DEV){
  window.addEventListener('pywebviewready',tryBind,{once:true});
  const s=document.createElement('script');
  s.src='dev/mock.js';
  s.onload=()=>readyResolve();
  s.onerror=()=>{mode='dead';readyResolve()};
  document.head.appendChild(s);
  setTimeout(readyResolve,1500);
}else{
  window.addEventListener('pywebviewready',tryBind,{once:true});
  /* 生产铁律:宽限期内后端没绑上 → dead,所有调用返回 BRIDGE_MISSING,由 UI 明说 */
  setTimeout(()=>{if(mode!=='real'){mode='dead';readyResolve()}},1200);
}

/* 每个契约方法经 dispatch:真实现优先;仅 dev 模式允许 mock 兜底;信封原样透传 */
function dispatch(name,...args){
  return ready.then(()=>{
    if(raw&&typeof raw[name]==='function')return raw[name].apply(raw,args);
    if(DEV&&window.GGMock&&typeof GGMock[name]==='function')return GGMock[name].apply(GGMock,args);
    return{ok:false,code:'BRIDGE_MISSING',message:'后端未就绪'+(DEV?'(mock 亦缺失)':'')};
  });
}

window.GG={
  get mode(){return mode},
  ready,
  on(type,fn){(SUBS[type]=SUBS[type]||[]).push(fn);return()=>{SUBS[type]=SUBS[type].filter(f=>f!==fn)}},
  api:new Proxy({},{get:(t,name)=>dispatch.bind(null,name)}),
  win(cmd){if(raw){cmd==='minimize'?raw.winMinimize():raw.winClose()}}
};

/* 后端 → 前端事件统一入口(契约 §3);dev 模式下 mock 模拟的事件也走这里 */
window.guiguiEmit=function(type,payload){
  (SUBS[type]||[]).forEach(fn=>{try{fn(payload)}catch(e){console.warn('[gg] handler',type,e)}});
};
})();
