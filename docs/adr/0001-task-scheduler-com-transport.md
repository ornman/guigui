# ADR-0001:任务调度传输层改为 COM 主通道 + schtasks 兜底

- **状态**:已批准·待实施(2026-09-11 用户指令「必须更改或者加冗余」)
- **日期**:2026-09-11
- **关联**:审计 R1(docs/tech/guigui-backend-audit-2026-09-11.md §4);部分吸收 R3(diagnostics 的 powershell 点)
- **边界**:只换传输层。任务机制、4 任务结构、触发器语义、rev 对齐、降级链(drop_logon_trigger)全部不动——2026-09-07「计划任务不动」拍板不受影响。

## 背景

现状每次任务对齐都起 `schtasks.exe` 子进程(scheduler.py:255/275/292),GUI 启动、每次保存设置、开关切换、用户点击重建都会触发全量 reconcile。未签名 PyInstaller exe + 子进程 LOLBin(`schtasks /create /f /xml <temp>`)是杀软行为引擎的 T1053.005 模板特征;2026-08-31 火绒严格模式已实测拦截过登录触发任务(scheduler.py:317-321 注释在案),当时靠「删 LogonTrigger 降级」消化,传输层未动。

## 决策

任务计划的 CRUD 传输改为双通道,**COM 为主、schtasks.exe 为兜底**:

1. **COM 主通道**:pythonnet 迟绑定调用 Task Scheduler 服务(`Schedule.Service` ProgID → `Connect` → `GetFolder("\\")`),注册走 `ITaskFolder.RegisterTask(name, xml, TASK_CREATE_OR_UPDATE=6, null, null, TASK_LOGON_INTERACTIVE_TOKEN=3, null)`——**直接吃现有 XML 字符串**,四个 `build_*_task_xml` 生成层零改动。查询/验证走 `GetTask`(读回 XML 与 `State`),删除走 `RegisteredTask.Delete`/`folder.DeleteTask`。
2. **schtasks 兜底通道**:COM 任何环节异常(import 失败/激活失败/HRESULT 错误)自动降级现有 `_run([...])` 路径,行为等价现状,`create_task/remove_task/query_xml` 对外签名不变(调用方零改动)。
3. **注册后验证**:COM 通道注册成功后 `GetTask` 读回确认存在,失败也走兜底重试(防「返回成功但任务未落」的边缘)。
4. **顺手消灭第二处 powershell**:diagnostics.py:319-339 的 `Get-ScheduledTaskInfo` 改走 COM(`RegisteredTask.LastRunTime / LastTaskResult / State`),schtasks /query 保留为兜底。

### 可行性(已实测,2026-09-11,本机 .venv-guigui)

- 依赖零新增:pythonnet 3.1.0 随 pywebview 已在运行时内(requirements.txt 无需改,spec 无需改)。
- 探针验证通过:`clr` + `Type.GetTypeFromProgID("Schedule.Service")` + `Activator.CreateInstance` + `InvokeMember("Connect"/"GetFolder"/"GetTask")` 全通,读到在岗真实 GuiGui 任务(State=3 就绪)。`Connect(None×4)` 的可空 VARIANT 封送无问题。

## 替代方案(为何不选)

- **新增 comtypes / pywin32**:能做,但新增运行时依赖 + PyInstaller 钩子/体积,而 pythonnet 迟绑定已被探针证明可用——零依赖方案优先。
- **只加重试不换通道**:进程树特征(未签名 exe → schtasks.exe)原样保留,治标。
- **安装期建任务**:仍由未签名 exe 执行,拦截特征不变;归 ADR-0005 一并权衡,不解决传输层。

## 后果

- **正向**:最大单一误报源消失(同机 RPC 到任务计划服务,不再 spawn LOLBin);注册路径不再需要 UTF-16 临时 XML 文件;诊断包少一处 powershell。
- **负向**:代码多一层通道封装;COM HRESULT 错误面新增(需映射到现有 bool/None 语义);迟绑定 `InvokeMember` 反射开销可忽略(每拍 ≤ 8 次调用)。
- **残余风险**:若杀软按服务 RPC 层拦(而非进程树),COM 也会被拦 → 兜底链保证功能不丢;最终杠杆仍是签名(ADR-0005)。

## 实施清单(零上下文可执行)

1. `guigui/core/scheduler.py`:新增 COM 通道模块级函数(`_com_folder()`/`_com_register`/`_com_query`/`_com_delete`),`create_task/remove_task/query_xml` 内部先 COM 后 schtasks;`RegisterTask` 的 7 参中 4 个可空位若 `None` 封送报 TypeMismatch,改传 `System.Type.Missing` 或空串(探针已验 Connect 可 None,此项实施时首验)。
2. `guigui/core/diagnostics.py:319-339`:`_self_tasks` 去 powershell,改 COM 读 LastRunTime/LastTaskResult;异常时回退现有 schtasks /query 语义(registered 判定不受损,last_run 允许缺失)。
3. 测试:279 测全绿为基准(现有 mock `_run` 的用例必须不破);新增 COM 层单测(注入假 folder/task 对象)+ 通道降级单测(COM 抛异常 → schtasks 被调用)。
4. 真机验证:dev 模式跑一轮 reconcile(本机在岗任务 rev 匹配应零改动);手动 `tasks_rev+1` 触发重建,任务计划程序面板人工确认;再跑 `python -m pytest guigui/tests -q`(仓库根)。
5. 契约:无变更(信封不动)。

## 验证基准

pytest 须从仓库根跑;venv 用 `.venv-guigui`;实施后 `dev/f-final` 动态验收跑一遍防回归。
