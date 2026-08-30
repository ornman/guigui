/* mock.js — 桥接契约 v1.0.0 的可执行规范(仅无真后端时被 GG 适配器选用)。
   方法名、信封、错误码、事件与契约一一对应;后端实现以本文件为行为参照,
   联调时两边对同一场景的返回必须逐字段一致。

   场景:URL ?scene=…(localStorage 记忆,默认 ok)
     ok        首装·已连已登(仪式 → v-ok)
     out       首装·连上未认证(仪式 → v-login)
     down      首装·不可达,当前网是热点「iphone17 pro max」(仪式 → v-guide)
     waiting   日常·网络未就绪(bootWait 等门,约 3.2s 门开推 net:state)
     daily     日常·一切正常(直进 v-main)
     rejected  登录一律被拒(QA 密码错误路径;网态同 out) */
(function(){
'use strict';
const LS_SCENE='gg-mock-scene',LS_CFG='gg-mock-cfg';
const qs=new URLSearchParams(location.search);
const SCENE=qs.get('scene')||(localStorage.getItem(LS_SCENE)||'ok');
if(qs.get('scene'))localStorage.setItem(LS_SCENE,SCENE);

const delay=ms=>new Promise(r=>setTimeout(r,ms));
const OK=d=>({ok:true,data:d});
const ERR=(code,message)=>({ok:false,code,message});
const emit=(type,payload)=>{if(typeof window.guiguiEmit==='function')window.guiguiEmit(type,payload)};
const nowTs=()=>{const d=new Date();
  return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0')};

const UID='2025000000001',UID_MASK='2025…7209',SERVER='10.1.2.3';

const S={
  configured:false,pwd:null,
  net:{state:'logged_in',ssid:'Campus-WiFi',server:SERVER},
  cfg:JSON.parse(localStorage.getItem(LS_CFG)||'null')||{
    trigger_time:'07:00',boot_login:true,heartbeat_minutes:5,
    wifi_fallback_enabled:false,wifi_fallback_ssid:null,
    patrol_enabled:false,patrol_minutes:30,wake_login:true,
    vacation_silence:true,notifications:true,show_gui:true,master:true,
    login_retries:3,retry_seconds:5},
  last:{when:'今早',time:'07:00',tries:1,outcome:'ok'},
  logs:[
    {label:'今天',entries:[
      {ts:'07:00:01',level:'ok',text:'网络可达'},
      {ts:'07:00:02',level:'ok',text:'已登录 · '+UID_MASK},
      {ts:'07:00:03',level:'note',text:'今天到这就下班啦 ☕'}]},
    {label:'昨天 · 8月29日',entries:[{ts:'06:55:02',level:'ok',text:'开门即试,一次登好 ✓'}]},
    {label:'8月28日 · 假期静默',entries:[{ts:'07:00:01',level:'silent',text:'连不上,今天先不打扰,明天再试一次'}]},
    {label:'8月27日 · 假期静默',entries:[{ts:'07:00:01',level:'silent',text:'连不上,今天先不打扰,明天再试一次'}]}]
};
if(SCENE==='out'){S.net.state='not_logged_in'}
if(SCENE==='down'){S.net.state='unreachable';S.net.ssid='iphone17 pro max'}
if(SCENE==='waiting'){S.configured=true;S.net.state='waiting'}
if(SCENE==='daily'){S.configured=true}
if(SCENE==='rejected'){S.net.state='not_logged_in'}

const saveCfg=()=>localStorage.setItem(LS_CFG,JSON.stringify(S.cfg));
const netEmit=()=>emit('net:state',{state:S.net.state,ssid:S.net.ssid});

window.GGMock={
  async probe(){
    await delay(650+Math.random()*450);
    if(S.net.state==='waiting')setTimeout(()=>{S.net.state='logged_in';netEmit()},3200);
    return OK({configured:S.configured,net:{...S.net}});
  },
  async identify(){
    await delay(250);
    if(S.net.state==='logged_in')return OK({uid:UID,source:'chkstatus'});
    if(S.configured)return OK({uid:UID,source:'config'});
    return OK({uid:null,source:'none'});
  },
  async login(a){
    emit('login:progress',{phase:'probe'});
    if(S.net.state==='unreachable')return ERR('NET_UNREACHABLE',SERVER+' 不可达,先连校园网');
    if(S.net.state==='waiting')return ERR('NET_UNREACHABLE','网络还没就绪,稍等一下再试');
    if(S.net.state==='logged_in')return OK({result:'already',uid:UID_MASK,attempts:0});
    const pwd=(a&&a.password)!=null&&a.password!==''?a.password:S.pwd;
    if(!pwd)return ERR('NOT_CONFIGURED','还没存密码,先填一次');
    emit('login:progress',{phase:'requesting',attempt:1,attempts:S.cfg.login_retries});
    await delay(900);
    if(SCENE==='rejected')return ERR('AUTH_REJECTED','密码被服务器拒绝了,改一下再试');
    S.pwd=pwd;S.net.state='logged_in';
    const e={ts:nowTs(),level:'ok',text:'已登录 · '+UID_MASK};
    S.logs[0].entries.push(e);
    emit('log:appended',{day_label:'今天',entry:e});
    netEmit();
    return OK({result:'success',uid:UID_MASK,attempts:1});
  },
  async scanWifi(){
    await delay(400);
    return OK({networks:[
      {ssid:'Campus-WiFi',signal:'strong'},
      {ssid:'Campus-5G',signal:'medium'},
      {ssid:'eduroam',signal:'weak'},
      ...(S.net.ssid&&S.net.ssid.indexOf('iphone')===0?[{ssid:S.net.ssid,signal:'strong'}]:[])
    ]});
  },
  async connectWifi(a){
    const ssid=a&&a.ssid;
    if(!ssid)return ERR('WIFI_CONNECT_FAILED','没指定网络');
    emit('login:progress',{phase:'connecting_wifi'});
    await delay(1800);
    S.net.ssid=ssid;S.net.state='not_logged_in';
    netEmit();
    return OK({connected:true,ssid});
  },
  async getConfig(){await delay(60);return OK({...S.cfg})},
  async saveConfig(patch){
    await delay(120);
    Object.assign(S.cfg,patch||{});saveCfg();
    return OK({...S.cfg});
  },
  async masterToggle(on){
    await delay(100);
    S.cfg.master=!!on;saveCfg();
    return OK({master:S.cfg.master});
  },
  async logs(a){
    await delay(80);
    const n=Math.min(Math.max((a&&a.days)||14,1),90);
    return OK({days:S.logs.slice(0,n)});
  },
  async recentResult(){await delay(50);return OK({...S.last})},
  async winMinimize(){},
  async winClose(){}
};
})();
