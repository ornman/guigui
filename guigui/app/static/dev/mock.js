/* mock.js — 桥接契约的可执行规范。开发专用:仅当 URL 带 ?dev=1 时由 app.js 动态注入;
   生产 index.html 不引用本文件,打包必须整目录排除 static/dev/。
   方法名、信封、错误码、事件与契约一一对应;后端实现以本文件为行为参照,
   联调时两边对同一场景的返回必须逐字段一致。

   场景:URL ?scene=…(localStorage 记忆,默认 ok)
     ok        首装·已连已登(仪式 → v-form·firstRun 语境)
     out       首装·连上未认证(仪式 → v-form·login 语境)
     down      首装·不可达,当前网是热点「iphone17 pro max」(仪式 → v-guide)
     waiting   日常·网络未就绪(P0-3:前端视同不可达落 v-guide;约 3.2s 后 mock 推 logged_in,排查页自动回日常)
     daily     日常·一切正常(直进 v-main)
     rejected  登录一律被拒 reason=wrong_password(QA 密码错误路径;网态同 out)
     bind      登录被 bind 拦 reason=bound(密码其实对;网态同 out)
     limit     登录被 limit_users 拒 reason=limit_users(已在别处登录,不冤枉密码;网态同 out)
     throttled 登录被节流 reason=throttled(契约 1.4.0;QA P1-6:不是密码错,前端走节流展示+phase='throttled' 推送,实机 waitsec 由服务器给)
     blocked   首装·提交密码成功但定时任务被拦 task_ok=false(契约 1.4.0 P0-1:成功页如实文案+重建入口;rebuildTask 一次即修好)
     fbdg      反馈提交走 SUBMITTED_DEGRADED(D1 成功、issue 延后;用户应无感照常「已收到」)
     other     日常·线上是别人的学号(提交走阶梯:logging_out 带 online_uid → 真登成功)
     unverified 日常·密码未验证+今早失败(主页两横幅 QA)
     ladder_fail  阶梯翻车·首装(2026-09-07 场景 4):线上他人 → 注销 → 真登 wrong_password
                  拒 → 无旧凭据可恢复 → 信封带「;网先断着,输对马上通」;net 翻为
                  not_logged_in,输对再点即走正常成功路(第二幕自然衔接)
     ladder_back  阶梯回滚·日常(2026-09-07 场景 4 变体):configured 且线上他人 → 注销 →
                  真登被拒 → 旧凭据把网接回 → 信封带「;已用旧密码把网接回来了,改对再点一次」
     beforeopen   锚前存入(2026-09-07 场景 7):06:50 前提交 → stored/reason=before_open/
                  verified=false/task_ok=true;主页重登(已存凭据)同样返 stored
     diag_ok     验证器全绿(1.5.0):logged_in + 学号一致 + 任务在岗 + 无崩溃 → exit=ok
     diag_cred   验证器凭据败:not_logged_in + 已存密码 → 真登被拒 wrong_password → exit=login
     diag_task   验证器任务败:logged_in + taskOk=false → 第 4 步 fail「多半被安全软件拦了」→ exit=task_blocked
     diag_app    验证器程序败:logged_in 一切正常但崩溃记录 → 第 5 步 fail → exit=app_fault
     streak     日常·重登连败(2026-09-08 横幅③/验证器链故事):configured+密码存过验证过,
                但密码已被人改 — 已存凭据重登也拒 wrong_password;diagnose 第 3 步
                同样真登被拒 → exit=login(文案与 rejected 场景逐字一致)

   dev 驱动钩子(摆拍/联调):_setNet(state,ssid) 真改网态源;_setRej(reason) 强改
   「已存凭据登录」的拒绝 reason(P1-12 状态页快登五态摆拍;null=关,恢复按场景);
   _setTaskOk(ok) 强改任务在岗位(P1-17 任务①:断网存配置的拦截分流摆拍);
   _runMorningTask('ok'|'fail') 模拟明早任务真跑(P1-17 任务②三结局摆拍) */
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
if(SCENE==='limit'){S.net.state='not_logged_in'}
if(SCENE==='throttled'){S.net.state='not_logged_in'}
if(SCENE==='blocked'){S.net.state='not_logged_in';S.taskOk=false}
if(SCENE==='other'){S.configured=true;S.verified=true}
if(SCENE==='ladder_back'){S.configured=true;S.verified=true}
if(SCENE==='beforeopen'){S.net.state='not_logged_in';S.configured=true;S.verified=false;S.pwd='secret'}
if(SCENE==='diag_ok'){S.configured=true;S.verified=true;S.pwd='secret'}
if(SCENE==='diag_cred'){S.net.state='not_logged_in';S.configured=true;S.verified=false;S.pwd='secret'}
if(SCENE==='diag_task'){S.configured=true;S.verified=true;S.pwd='secret';S.taskOk=false}
if(SCENE==='diag_app'){S.configured=true;S.verified=true;S.pwd='secret'}
if(SCENE==='streak'){S.net.state='not_logged_in';S.configured=true;S.verified=true;S.pwd='secret'}
if(SCENE==='unverified'){S.configured=true;S.verified=false;
  S.last={when:'今早',time:'07:00',tries:3,outcome:'fail'};
  S.logs[0].entries=[{ts:'07:00:01',level:'fail',text:'登录被拒:密码不对,改一下再试'}]}

const saveCfg=()=>localStorage.setItem(LS_CFG,JSON.stringify(S.cfg));
const netEmit=()=>emit('net:state',{state:S.net.state,ssid:S.net.ssid});
let forcedRej=null;   /* _setRej 驱动位:强改已存凭据登录的拒绝 reason(null=关) */

window.GGMock={
  async probe(){
    await delay(650+Math.random()*450);
    if(S.net.state==='waiting')setTimeout(()=>{S.net.state='logged_in';netEmit()},3200);
    return OK({configured:S.configured,net:{...S.net}});
  },
  async identify(){
    await delay(250);
    if(SCENE==='other'||SCENE==='ladder_fail'||SCENE==='ladder_back')
      return OK({uid:OTHER_UID,source:'chkstatus'});   /* 线上是别人的号 */
    if(S.net.state==='logged_in')return OK({uid:UID,source:'chkstatus'});
    if(S.configured)return OK({uid:UID,source:'config'});
    return OK({uid:null,source:'none'});
  },
  async login(a){
    emit('login:progress',{phase:'probe'});
    /* 对齐后端(api.py unreachable/waiting 分支):断网/未就绪时提交的密码没被否认,
       存未验证给明早 — P0-7 验收链(存配置→网恢复→状态页快登)靠这条走通 */
    if(S.net.state==='unreachable'||S.net.state==='waiting'){
      if(a&&a.password){S.pwd=a.password;S.configured=true;S.verified=false}
      return ERR('NET_UNREACHABLE',SERVER+' 不可达,先连校园网');
    }
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
      return OK({result:'success',uid:UID_MASK,attempts:1,verified:true,task_ok:S.taskOk});
    }
    if(S.net.state==='logged_in'&&SCENE==='ladder_fail'&&(a&&a.password)){
      /* 场景 4 首装变体:注销他人会话 → 真登被拒 → 无旧凭据可恢复,网断着;
         第二幕:用户输对密码再点 → 上面 not_logged_in 正常流程,自然衔接 */
      emit('login:progress',{phase:'logging_out',online_uid:'6503…6503'});
      await delay(1400);
      S.net.state='not_logged_in';netEmit();
      emit('login:progress',{phase:'requesting',attempt:1,attempts:1});
      await delay(900);
      return ERR('AUTH_REJECTED','密码不对,改一下再试;网先断着,输对马上通','wrong_password');
    }
    if(S.net.state==='logged_in'&&SCENE==='ladder_back'&&(a&&a.password)){
      /* 场景 4 日常变体:注销 → 真登被拒 → 旧凭据把网接回来了(信封如实说明) */
      emit('login:progress',{phase:'logging_out',online_uid:'6503…6503'});
      await delay(1400);
      S.net.state='not_logged_in';netEmit();
      emit('login:progress',{phase:'requesting',attempt:1,attempts:1});
      await delay(900);
      S.net.state='logged_in';netEmit();
      return ERR('AUTH_REJECTED','密码不对,改一下再试;已用旧密码把网接回来了,改对再点一次','wrong_password');
    }
    if(S.net.state==='logged_in')return OK({result:'already',uid:UID_MASK,attempts:0,verified:S.verified});
    /* dev 驱动(_setRej):已存凭据登录(login 无 password)强改拒绝 reason —
       P1-12 状态页快登五态摆拍;文案与后端 rejection_text 逐字一致 */
    if(forcedRej&&!(a&&a.password)){
      if(forcedRej==='throttled'){
        emit('login:progress',{phase:'throttled',waitsec:10,attempt:1,attempts:1});
        return ERR('AUTH_REJECTED','登录太频繁,请等 10 秒再试','throttled');
      }
      const m={wrong_password:'密码不对,改一下再试',
        wrong_account:'学号或运营商选错了,核对一下再试',
        bound:'密码是对的,但这个账号被绑在别处/受限 — 去自助服务平台看看绑定',
        limit_users:'这个学号已在别的设备上登录(比如在别处登过没下线),那边下线后桂桂会自动登好'}[forcedRej];
      return ERR('AUTH_REJECTED',m,forcedRej);
    }
    const pwd=(a&&a.password)!=null&&a.password!==''?a.password:S.pwd;
    if(!pwd)return ERR('NOT_CONFIGURED','还没存密码,先填一次');
    emit('login:progress',{phase:'requesting',attempt:1,attempts:S.cfg.login_retries});
    await delay(900);
    if(SCENE==='beforeopen'){
      /* 场景 7:06:50 前提交 → 不判密码错,存未验证,明早首试真验证(契约 stored) */
      S.pwd=pwd;
      return OK({result:'stored',uid:UID_MASK,attempts:1,verified:false,reason:'before_open',task_ok:S.taskOk});
    }
    if(SCENE==='rejected'||SCENE==='streak')return ERR('AUTH_REJECTED','密码不对,改一下再试','wrong_password');
    if(SCENE==='bind')return ERR('AUTH_REJECTED','密码是对的,但这个账号被绑在别处/受限 — 去自助服务平台看看绑定','bound');
    if(SCENE==='limit')return ERR('AUTH_REJECTED','这个学号已在别的设备上登录(比如在别处登过没下线),那边下线后桂桂会自动登好','limit_users');
    if(SCENE==='throttled'){
      /* QA P1-6:节流≠密码错;推 phase='throttled' 给前端,然后返回 throttled 信封 */
      emit('login:progress',{phase:'throttled',waitsec:10,attempts:1});
      return ERR('AUTH_REJECTED','登录太频繁,请等 10 秒再试','throttled');
    }
    S.pwd=pwd;S.net.state='logged_in';S.verified=true;
    const e={ts:nowTs(),level:'ok',text:'已登录 · '+UID_MASK};
    S.logs[0].entries.push(e);
    emit('log:appended',{day_label:'今天',entry:e});
    netEmit();
    /* 契约 1.4.0:提交密码路径的成功信封携带 task_ok;已存凭据路径不带 */
    const env={result:'success',uid:UID_MASK,attempts:1,verified:true};
    if(a&&a.password)env.task_ok=S.taskOk;
    return OK(env);
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
  /* ── 2.18 diagnose(1.5.0 验证器):五步与后端逐字一致(diag_* 四场景);
     与 _setNet 联动:当前网态真改第 1-3 步走向 ── */
  async diagnose(){
    const steps=[];let exit='ok',verdict='一切正常,网是通的';
    const conclude=(c,t)=>{if(exit==='ok'){exit=c;verdict=t}};
    const step=async(i,key,label,state,detail,reason)=>{
      emit('diag:progress',{step:i,key,state:'running',detail:'正在查…'});
      await delay(280+Math.random()*180);
      const item={key,label,state,detail};
      if(reason)item.reason=reason;
      steps.push(item);
      emit('diag:progress',{step:i,key,state,detail});
    };
    const net=S.net;
    /* ① 网络连通(链路层) */
    if(net.state==='waiting')await step(1,'network','网络连通','fail','网络还没就绪,像刚开机');
    else if(net.ssid)await step(1,'network','网络连通','ok','已连上 '+net.ssid);
    else await step(1,'network','网络连通','ok','已联网(非 WiFi)');
    /* ② 认证服务器 */
    const up=net.state==='logged_in'||net.state==='not_logged_in';
    const server=net.server||'10.1.2.3';
    if(up)await step(2,'server','认证服务器','ok',server+' 可达');
    else{await step(2,'server','认证服务器','fail',server+' 连不上');conclude('net_down','连不上校园网,先看看网络')}
    /* ③ 凭据验证(副作用仅此步:真登一次看得见) */
    if(!up)await step(3,'credential','凭据验证','skip','服务器够不着,密码没能验证');
    else if(!S.configured||!S.pwd){
      await step(3,'credential','凭据验证','fail','还没存密码,先去填一次');
      conclude('login','密码还没存,先去填一次')}
    else if(net.state==='logged_in'){
      const online=(SCENE==='other'||SCENE==='ladder_fail'||SCENE==='ladder_back')?OTHER_UID:UID;
      if(online===UID)await step(3,'credential','凭据验证','ok','在线,学号一致 ✓');
      else{
        await step(3,'credential','凭据验证','fail','线上是别人的学号(2025…6503),登录一次换回自己');
        conclude('login','线上是别人的号,登录一次换回自己')}
    }else{
      /* not_logged_in:用已存凭据真登一次 */
      emit('login:progress',{phase:'requesting',attempt:1,attempts:1});
      await delay(900);
      if(SCENE==='diag_cred'||SCENE==='rejected'||SCENE==='streak'){
        await step(3,'credential','凭据验证','fail','密码不对,改一下再试','wrong_password');
        conclude('login','凭据有问题,去登录页改一下')
      }else{
        S.net.state='logged_in';S.verified=true;
        const e={ts:nowTs(),level:'ok',text:'已登录 · '+UID_MASK};
        S.logs[0].entries.push(e);
        emit('log:appended',{day_label:'今天',entry:e});
        netEmit();
        await step(3,'credential','凭据验证','ok','密码对,顺手把网登上了 ✓')
      }
    }
    /* ④ 定时任务(按配置只数该在岗的;从缺失反推被拦,如实「多半」) */
    const beats=[
      ['GuiGui',S.cfg.master],
      ['GuiGui-Boot',S.cfg.master&&S.cfg.boot_login!==false],
      ['GuiGui-Wake',S.cfg.master&&S.cfg.wake_login],
      ['GuiGui-Patrol',S.cfg.master&&S.cfg.patrol_enabled]];
    const expected=beats.filter(b=>b[1]);
    if(!expected.length)await step(4,'task','定时任务','skip','总开关关着,自动化本来就没开');
    else if(!S.taskOk){
      await step(4,'task','定时任务','fail','任务不在岗,多半被安全软件拦了');
      conclude('task_blocked','自动登录还没生效,定时任务被拦了')}
    else await step(4,'task','定时任务','ok',expected.length+' 项任务都在岗');
    /* ⑤ 程序自身 */
    if(SCENE==='diag_app'){
      await step(5,'app','程序自身','fail','最近有 1 次崩溃记录');
      conclude('app_fault','桂桂自己出了点问题,带着结论反馈给开发者')}
    else await step(5,'app','程序自身','ok','无崩溃记录');
    return OK({steps,verdict,exit});
  },
  async rebuildTask(){
    await delay(600);
    S.taskOk=true;   /* QA:重建一次就修好 */
    emit('schedule:changed',{master:S.cfg.master,trigger_time:S.cfg.trigger_time,task_ok:true});
    return OK({ok:true,changed:true});
  },
  async feedback(){
    /* 1.3.0 废弃路径(保留一个版本周期):复制文本的旧入口 */
    await delay(400);
    return OK({text:[
      '桂桂 v2.1.0 诊断信息(预览)',
      '系统:Windows 11 26200 x64 · Python 3.12.8',
      '网络:WiFi Campus-WiFi · HTTP 200 · 340ms',
      '—— 最近 7 天 ——','09-01 ✓ · 09-02 ✓ · 09-03 ✗'
    ].join('\n')});
  },
  /* ── 1.3.0 真通道:提交三态 / 诊断预览 / 队列状态 ── */
  async feedbackSend(a){
    await delay(700);
    const kind=(a&&Array.isArray(a.kind)&&a.kind.length)?a.kind:['problem'];
    if(!a||!String(a.what||'').trim())return ERR('FB_VALIDATION','说说具体情况(必填)');
    if(SCENE==='fbdg')return OK({result:'submitted_degraded',id:'GG-37'});
    if(SCENE==='down'){                          /* 断网 → 入队(QA:AC-F3) */
      const q=JSON.parse(localStorage.getItem('gg-mock-fbq')||'[]');
      q.push({kind,what:a.what,contact:a.contact||''});
      localStorage.setItem('gg-mock-fbq',JSON.stringify(q));
      return OK({result:'queued',next_attempt_at:'07:32'});
    }
    return OK({result:'submitted',id:'GG-'+(33+Math.floor(Math.random()*6))});
  },
  async feedbackDiag(a){
    await delay(350);
    const thin=a&&Array.isArray(a.kind)&&a.kind.length===1&&a.kind[0]==='suggestion';
    return OK({text:thin?
      '桂桂 v2.1.0 诊断信息(建议瘦身包)\n系统:Windows 11 26200 x64\n(听建议不需要网络现场)':
      '桂桂 v2.1.0 诊断信息\n系统:Windows 11 26200 x64 · Python 3.12.8 · WebView2 120.0.2210.61\n网卡 WLAN(wifi)· Campus-WiFi · 10.20.30.40\n── 网络(实时)── HTTP 200 · 340ms · 出口网卡:以太网\n── 最近七天 ──\n09-01 ✓ · 09-02 ✓ · 09-03 ✗ · 09-04 ✗\n[09-04]\n  06:52:11 FAIL 登录被拒:这个学号已在别的设备上登录…',
      uid_masked:'2025…0001'});
  },
  async feedbackPendingStatus(){
    await delay(80);
    let q=JSON.parse(localStorage.getItem('gg-mock-fbq')||'[]');
    if(q.length&&SCENE!=='down'){                /* 联网即自动补发 */
      q=[];localStorage.setItem('gg-mock-fbq','[]');
    }
    return OK({pending:q.length,oldest_age_s:q.length?1800:null});
  },
  async winMinimize(){},
  async winClose(){},
  async _setNet(state,ssid){
    /* dev 驱动钩子(state-gallery/联调用):真改 mock 数据源并推 net:state —
       与 guiguiEmit 手推不同,后续 login()/probe() 的网态判定随动,全链真跑 */
    S.net.state=state;
    if(ssid!=null)S.net.ssid=ssid;
    netEmit();
    return OK({...S.net});
  },
  async _setRej(reason){
    /* dev 驱动钩子(P1-12):强改已存凭据登录的拒绝 reason(五态摆拍);null/空=关 */
    forcedRej=reason||null;
    return OK({forced:forcedRej});
  },
  async _setTaskOk(ok){
    /* dev 驱动钩子(P1-17 任务①):强改任务在岗位 — 断网存配置后 submitLadder
       补询 taskStatus 的分流摆拍(false=杀软拦了建成失败 → 拦截页;不还原,
       需要复位就传 true 或重载场景) */
    S.taskOk=!!ok;
    return OK({taskOk:S.taskOk});
  },
  async _runMorningTask(outcome){
    /* dev 驱动钩子(P1-17 任务②):模拟明早 07:00 定时任务真跑一次(GUI 在场视角),
       按 FileWatcher 翻译口径推事件(log:appended 先到、net:state 后到)—
       'ok'=登上(verified 翻真;GUI 不弹彩带,只日志+主页状态,彩带规则见 P1-16)/
       'fail'=重试穷尽没登上(任务仍在岗不进拦截页;网态翻 not_logged_in 走
       ROUTE 调起状态页·蓝变红递快登,横幅①按 verified 自洽;通知由后端发) */
    const t='07:00:'+String(11+Math.floor(Math.random()*78)).padStart(2,'0');
    if(outcome==='ok'){
      S.verified=true;S.net.state='logged_in';
      S.last={when:'今早',time:'07:00',tries:1,outcome:'ok'};
      const e={ts:t,level:'ok',text:'已登录 · '+UID_MASK};
      S.logs[0].entries.push(e);emit('log:appended',{day_label:'今天',entry:e});
      netEmit();
      return OK({ran:'ok'});
    }
    S.net.state='not_logged_in';
    S.last={when:'今早',time:'07:00',tries:3,outcome:'fail'};
    const e={ts:t,level:'fail',text:'登录被拒:密码不对,改一下再试'};
    S.logs[0].entries.push(e);emit('log:appended',{day_label:'今天',entry:e});
    netEmit();
    return OK({ran:'fail'});
  },
  async openSelfService(){window.open('https://bcs.guat.edu.cn/Cas/Login?appid=71999680','_blank')}
};
})();
