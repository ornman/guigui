/* mock.js — 桥接契约的可执行规范。开发专用:仅当 URL 带 ?dev=1 时由 app.js 动态注入;
   生产 index.html 不引用本文件,打包必须整目录排除 static/dev/。
   方法名、信封、错误码、事件与契约一一对应;后端实现以本文件为行为参照,
   联调时两边对同一场景的返回必须逐字段一致。

   场景:URL ?scene=…(localStorage 记忆,默认 ok)
     ok        首装·已连已登(仪式 → v-ok)
     out       首装·连上未认证(仪式 → v-login)
     down      首装·不可达,当前网是热点「iphone17 pro max」(仪式 → v-guide)
     waiting   日常·网络未就绪(bootWait 等门,约 3.2s 门开推 net:state)
     daily     日常·一切正常(直进 v-main)
     rejected  登录一律被拒 reason=wrong_password(QA 密码错误路径;网态同 out)
     bind      登录被 bind 拦 reason=bound(密码其实对;网态同 out)
     other     日常·线上是别人的学号(提交走阶梯:logging_out 带 online_uid → 真登成功)
     unverified 日常·密码未验证+今早失败(主页两横幅 QA) */
(function(){
'use strict';
const LS_SCENE='gg-mock-scene',LS_CFG='gg-mock-cfg';
const qs=new URLSearchParams(location.search);
const SCENE=qs.get('scene')||(localStorage.getItem(LS_SCENE)||'ok');
if(qs.get('scene'))localStorage.setItem(LS_SCENE,SCENE);

const delay=ms=>new Promise(r=>setTimeout(r,ms));
const OK=d=>({ok:true,data:d});
const ERR=(code,message,reason)=>reason?{ok:false,code,message,reason}:{ok:false,code,message};
const emit=(type,payload)=>{if(typeof window.guiguiEmit==='function')window.guiguiEmit(type,payload)};
const nowTs=()=>{const d=new Date();
  return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0')};

const UID='2025000000001',UID_MASK='2025…7209',OTHER_UID='2025000000002',SERVER='10.1.2.3';

const S={
  configured:false,pwd:null,verified:false,taskOk:true,
  net:{state:'logged_in',ssid:'Campus-WiFi',server:SERVER},
  cfg:JSON.parse(localStorage.getItem(LS_CFG)||'null')||{
    trigger_time:'07:00',boot_login:true,heartbeat_minutes:5,operator:'校园用户',
    wifi_fallback_enabled:false,wifi_fallback_ssid:null,
    patrol_enabled:false,patrol_minutes:30,wake_login:false,
    vacation_silence:true,notifications:true,show_gui:true,master:true,
    login_retries:3,retry_seconds:5},
  last:{when:'今早',time:'07:00',tries:1,outcome:'ok'},   /* tries:0=本来就在线,见 lastText */
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
if(SCENE==='daily'){S.configured=true;S.verified=true}
if(SCENE==='rejected'){S.net.state='not_logged_in'}
if(SCENE==='bind'){S.net.state='not_logged_in'}
if(SCENE==='other'){S.configured=true;S.verified=true}
if(SCENE==='unverified'){S.configured=true;S.verified=false;
  S.last={when:'今早',time:'07:00',tries:3,outcome:'fail'};
  S.logs[0].entries=[{ts:'07:00:01',level:'fail',text:'登录被拒:密码不对,改一下再试'}]}

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
    if(SCENE==='other')return OK({uid:OTHER_UID,source:'chkstatus'});   /* 线上是别人的号 */
    if(S.net.state==='logged_in')return OK({uid:UID,source:'chkstatus'});
    if(S.configured)return OK({uid:UID,source:'config'});
    return OK({uid:null,source:'none'});
  },
  async login(a){
    emit('login:progress',{phase:'probe'});
    if(S.net.state==='unreachable')return ERR('NET_UNREACHABLE',SERVER+' 不可达,先连校园网');
    if(S.net.state==='waiting')return ERR('NET_UNREACHABLE','网络还没就绪,稍等一下再试');
    if(a&&a.operator){S.cfg.operator=a.operator;saveCfg()}   /* 登录即存,getConfig 回填胶囊 */
    if(S.net.state==='logged_in'&&SCENE==='other'&&(a&&a.password)){
      /* 验证阶梯:线上是他人学号 → 注销(如实注明)→ 翻转 → 真登一次 */
      emit('login:progress',{phase:'logging_out',online_uid:'6503…6503'});
      await delay(1400);
      S.net.state='not_logged_in';
      emit('login:progress',{phase:'requesting',attempt:1,attempts:1});
      await delay(900);
      S.pwd=a.password;S.verified=true;S.net.state='logged_in';
      const e={ts:nowTs(),level:'ok',text:'已登录 · '+UID_MASK};
      S.logs[0].entries.push(e);
      emit('log:appended',{day_label:'今天',entry:e});
      netEmit();
      return OK({result:'success',uid:UID_MASK,attempts:1,verified:true});
    }
    if(S.net.state==='logged_in')return OK({result:'already',uid:UID_MASK,attempts:0,verified:S.verified});
    const pwd=(a&&a.password)!=null&&a.password!==''?a.password:S.pwd;
    if(!pwd)return ERR('NOT_CONFIGURED','还没存密码,先填一次');
    emit('login:progress',{phase:'requesting',attempt:1,attempts:S.cfg.login_retries});
    await delay(900);
    if(SCENE==='rejected')return ERR('AUTH_REJECTED','密码不对,改一下再试','wrong_password');
    if(SCENE==='bind')return ERR('AUTH_REJECTED','密码是对的,但这个账号被绑在别处/受限 — 去自助服务平台看看绑定','bound');
    S.pwd=pwd;S.net.state='logged_in';S.verified=true;
    const e={ts:nowTs(),level:'ok',text:'已登录 · '+UID_MASK};
    S.logs[0].entries.push(e);
    emit('log:appended',{day_label:'今天',entry:e});
    netEmit();
    return OK({result:'success',uid:UID_MASK,attempts:1,verified:true});
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
    emit('schedule:changed',{master:S.cfg.master,trigger_time:S.cfg.trigger_time,task_ok:S.taskOk});
    return OK({master:S.cfg.master});
  },
  async logs(a){
    await delay(80);
    const n=Math.min(Math.max((a&&a.days)||14,1),90);
    return OK({days:S.logs.slice(0,n)});
  },
  async recentResult(){await delay(50);return OK({...S.last,verified:S.verified})},
  async taskStatus(){await delay(80);return S.cfg.master?OK({ok:S.taskOk}):OK({ok:true,note:'off'})},
  async rebuildTask(){
    await delay(600);
    S.taskOk=true;   /* QA:重建一次就修好 */
    emit('schedule:changed',{master:S.cfg.master,trigger_time:S.cfg.trigger_time,task_ok:true});
    return OK({ok:true,changed:true});
  },
  async feedback(){
    await delay(400);
    const lines=[
      '桂桂 v2.0.0 诊断信息',
      '时间:2026-08-31 07:00',
      '系统:Windows 11 · WebView2',
      '网络:Campus-WiFi · 已登录 · 2025…0001',
      '配置:07:00 触发 · 巡逻 30 分钟 · 通知开',
      '凭据:已存(密码不出后端)',
      '任务:GuiGui(每日)与 GuiGui-Patrol(巡逻)已注册',
      '—— 最近 3 天 ——',
      '07:00 [OK] 已登录 · 2025…0001'
    ];
    return OK({text:lines.join('\n')});
  },
  async winMinimize(){},
  async winClose(){},
  async openSelfService(){window.open('https://bcs.guat.edu.cn/Cas/Login?appid=71999680','_blank')}
};
})();
