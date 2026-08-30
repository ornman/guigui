/* app.js — GG 适配器:桥接契约 v1.0.0(docs/tech/guigui-bridge-api-v1.md)的前端侧绑定。
   三级探测:window.guigui(后端注入别名)→ pywebview.js api → GGMock(契约可执行规范)。
   后端就位后前端零改动切真;浏览器里自动回落 mock。
   html.in-app 仅在真后端绑定时挂上(透明无边框窗口样式,见 index.html #app-overrides)。 */
(function(){
'use strict';
const SUBS={};
let mode='mock',raw=null,readyResolve=null;
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
if(!tryBind()){
  window.addEventListener('pywebviewready',tryBind,{once:true});
  /* 兜底:真后端的 pywebviewready 通常 <500ms 就位;过了宽限期仍无事件 → 浏览器 mock */
  setTimeout(readyResolve,1200);
}

/* 每个契约方法都经 dispatch:等绑定就绪后分发,信封原样透传。
   注意 rest 参数——bind 传参是散参,apply 需要真数组,否则对象会被当空参列表 */
function dispatch(name,...args){
  return ready.then(()=>{
    const impl=raw||window.GGMock;
    if(!impl||typeof impl[name]!=='function')
      return{ok:false,code:'INTERNAL',message:'桥接方法缺失: '+name};
    return impl[name].apply(impl,args);
  });
}

window.GG={
  get mode(){return mode},
  ready,
  on(type,fn){(SUBS[type]=SUBS[type]||[]).push(fn);return()=>{SUBS[type]=SUBS[type].filter(f=>f!==fn)}},
  api:new Proxy({},{get:(t,name)=>dispatch.bind(null,name)}),
  win(cmd){if(mode==='real'&&raw){cmd==='minimize'?raw.winMinimize():raw.winClose()}}
};

/* 后端 → 前端事件统一入口(契约 §3);mock 模拟的事件也走这里 */
window.guiguiEmit=function(type,payload){
  (SUBS[type]||[]).forEach(fn=>{try{fn(payload)}catch(e){console.warn('[gg] handler',type,e)}});
};
})();
