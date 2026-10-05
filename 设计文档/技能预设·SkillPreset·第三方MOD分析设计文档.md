# 技能预设（SkillPreset）—— 第三方 MOD 逆向分析设计文档

（分析对象 = `mod\skillpreset.pack`，他人设计的战锤3技能管理 MOD。本文档 = 功能总结 + 架构拆解 + 关键机制 + 可借鉴经验，全部集中在这一份里。分析方式 = RPFM CLI 4.0.4 全量解包 + 逐文件源码审读，未运行游戏。）

---

## 0. 速览

| 项目 | 值 |
|---|---|
| 分析对象 | `E:\战锤mod\mod\skillpreset.pack` |
| **MD5** | **`b58fbc8f068c6d6ab2dbcfa21a74bb2a`** |
| 大小 | 1,028,604 字节（压缩格式 None） |
| Pack 头 | PFH5 · **file_type = 3（Mod 型）** |
| 包内条目 | **15 个资源**（6 Lua + 1 loc + 5 TWUI XML + 1 PNG）+ RPFM 保留元数据（`dependencies_manager_v2.rpfm_reserved` 内容为 `[]`，无声明依赖） |
| **DB 表** | **0 张 —— 纯脚本/界面 MOD，对原版数据零改动** |
| 代码量 | Lua 共 **16,134 行**（约 880 KB），其中 UI 控制器一个文件 10,737 行 |
| 运行时依赖 | **`memreader`**（外部库 MOD，提供 `_G.memreader` 内存读取）；缺失时**优雅降级**，只损失部分精读能力 |
| 借鉴来源 | cpecific skill queue（CSQ）、Custom Lord Creation、MCT —— 只抄已验证写法，不打包依赖 |

**一句话总结**：这是一套「角色技能加点管理器」——把技能配置存成**按角色类型（agent_subtype）归档的本地模板**，支持一键套用、点数不足自动转**实时队列**并随升级自动加点；技术上以「CCO 表达式读树 + **内存读取拿真值** + **规划→盲加→对账三段式结算**」构成闭环，UI 为不碰原版面板的独立浮层。工程化程度极高（需求文档章节号、M0/M1/M2 里程碑、D1~D9 决策编号、🩸教训注释遍布源码），是 Lua MOD 里少见的高完成度作品。

---

## 一、这个 MOD 干什么

围绕战锤3战役的**角色技能树**做增量管理，全部功能只属于玩家操作，不改任何原版数值：

| # | 功能 | 说明 |
|---|---|---|
| 1 | **技能模板** | 把某角色当前的加点方案存为命名模板，**按 agent_subtype 分目录**归档；支持列表 / 读取 / 保存 / 删除 / 重命名 |
| 2 | **套用模板** | 点数够 → 立即一次点完；点数不足 → 剩余项转入该角色的**实时队列**（决策 D1） |
| 3 | **角色实时队列** | 与模板解耦的待加点列表，可置顶 / 移位 / 删除，**随存档持久化**（决策 D9） |
| 4 | **队列自动加点** | 由 `CharacterSkillPointAvailable` 事件驱动（不轮询），升级拿到点数后按队列顺序自动学习 |
| 5 | **一键补全** | 按优先级把当前可学的技能自动排进队列，用光剩余点数 |
| 6 | **读取加点技能** | 把角色**已学**的技能还原成有序列表灌入队列（用于"从现状生成模板"） |
| 7 | **技能节点点击入队** | 在原版技能卡**内部**注入透明点击层，直接点技能树节点入队/出队，并挂「升到 N 级」角标 |
| 8 | **模拟升级**（已隔离停用） | 虚拟等级轴推演，不动角色真实状态；当前版本 `SIM_ENABLED = false` 整块隔离 |
| 9 | **中英双语 UI** | 单 loc 文件带 `_en` 后缀键，Lua 按游戏语言二选一 |

安全边界（源码明示的承诺）：
- **绝不撤销已学技能** —— 换模板时只提示「有 N 个已生效技能不在新模板里」，让玩家自己用原版「重置全部技能点」；
- **绝不虚报** —— 队列项「要么真学到、要么留在队列」由结构保证（见 §3.3）；
- **绝不在玩家可编辑目录执行代码** —— 模板解析不用 `loadstring`（见 §5）。

---

## 二、总体架构

### 2.1 模块划分（全局命名空间 `SkillPreset.*`）

引擎机制：先加载 `script/campaign/mod/` 下全部文件，再**统一调用与文件同名的全局函数**作入口（日志可证：`skillpreset_ui() not found, continuing`）。因此模块注册在文件顶层，入口函数只做初始化，加载顺序互不敏感。

| 文件 | 行数 | 注册 | 职责 |
|---|---:|---|---|
| `skillpreset_memread.lua` | 276 | `SkillPreset.memread` | **内存读取层**：经 `_G.memreader` 读技能节点真实等级 / 前置点数 / 前置关系（REQUIRED·SUBSET）/ 互斥 / 逐级经验曲线 / 等级上限 |
| `skillpreset_core.lua` | 2,661 | `SkillPreset.core` | **M1 加点内核**：技能树解析、前置与互斥校验、队列运算、三段式结算、模拟推演、一键补全、已学顺序还原 |
| `skillpreset_storage.lua` | 582 | `SkillPreset.storage` | **M2 模板存储**：%APPDATA% 文件读写、索引维护、无 `loadstring` 纯字符串解析 |
| `skillpreset_apply.lua` | 1,185 | `SkillPreset.apply` | **M2 应用与实时队列**：套模板 / 换模板 / 队列 CRUD / 事件驱动自动加点 / 存档持久化 / 手点同步 |
| `skillpreset_subtype_kind.lua` | 693 | `SkillPreset.subtype_category` | **自动生成**（`tools/gen_subtype_kind.py`）：subtype → 原版类型名 loc key，命中率 100%，用于模板按「同类合并」展示 |
| `skillpreset_ui.lua` | 10,737 | `SkillPreset.ui` | **UI 控制器**：浮层队列面板、模板弹窗、技能卡点击层、双语、几何跟随、事件接入 |

### 2.2 依赖与参考

| 项 | 性质 | 说明 |
|---|---|---|
| `memreader` | **运行时依赖**（外部库 MOD） | 读引擎进程内存；`api_ready()` 逐步检查，缺 API / 偏移失效一律返回 nil，调用方降级 |
| CSQ（cpecific skill queue） | 只抄写法 | 技能树读取表达式（`SKILL_LIST_EXPR` 出处 CSQ:250）、列表滚动结构、行卡片布局、几何跟随模式 |
| Custom Lord Creation | 只抄写法 | 浮层面板本体与九宫格贴图写法 |
| MCT | 只抄写法 | Resize 需配 `ResizeCurrentStateImage` 的经验；早期倍率方案已弃用，改为 memread 读真实经验表 |

---

## 三、数据链与关键机制

### 3.1 技能树读取 —— CCO 表达式（不是 DB、不是 UI 遍历）

```lua
-- core.lua M.SKILL_LIST_EXPR（出处 cpecific_skill_queue.lua:250，M0 实测可用）
'SkillList.JoinString(ParentSkillsList.JoinString(Key,",")+";"+Key+";"
  +IsBackgroundSkill+";"+Level+";"+TotalLevels+";"+Status+";"
  +ChildSkillsList.JoinString(Key,",")+";"
  +LevelsDetailsList.JoinString(Level+":"+RankRequired,","),"|")'
```

- 经 `cco("CcoCampaignCharacter", cqi):Call(...)` 拿到整棵树的**扁平字符串**，按 `|` 拆行、`;` 拆字段；
- 每行固定 **8 字段**：`[0]父技能列表 [1]key [2]isBg [3]当前等级 [4]等级上限 [5]状态 [6]子技能列表 [7]等级明细`；
- 🩸 **铁律：不可用 `gmatch("[^;]+")` 逐段取** —— 它会跳过空字段导致整体错位（源码头部明示）；
- 剩余点数用同通道 `Call('SkillPointsAvailable')`。

### 3.2 内存读取 —— 为什么引擎表达式不够（memread 模块）

**根因**（实测结论，写死在注释里）：引擎表达式**不返回技能解锁等级** —— 加 `UnlockedAtRank` 属性读不到（= 0）、`LevelsDetailsList` 的 `RankRequired` 恒为 0。而「某等级刚解锁的技能优先」「前置需要 N 点」等判定都离不开真值。

| 读取项 | API | 用途 |
|---|---|---|
| 真实已学等级 | `load_levels` | 对账唯一裁决信源（见 3.3） |
| 前置关系 + 互斥 | `load_prereqs` | REQUIRED / SUBSET（N 选 M）精确判定 |
| 前置投点 | `load_prereq_points` | 「父技能共投 N 点才解锁」 |
| 逐级经验曲线 | `experience_points` | 每级给几点（取代 MCT 倍率/预设） |
| 等级上限 | `rank_cap` | 推演封顶 |

设计约束：
- **读取等级与读取规则分开**（普通对账只读 key/level/节点数，不碰关系，省开销）；
- 内存偏移**随游戏版本漂移**，任何一步失败返回 nil，调用方「暂停该角色结算、保留队列与未确认单据」；
- 读不到逐级曲线时，数值只用于**显示估算**，绝不作为真实加点的预算上限。

### 3.3 🩸🩸 结算三段式（2026-10-03 重构，全 MOD 唯一加点路径）

旧架构「边读边判边加」的病根：`cm:add_skill`（AddPoint）之后**引擎内存异步刷新**，同一结算内刚加的技能 level 恒旧，每轮判定都要靠多层回退手工补账；而用 CCO 的 `Level` 做裁决实测恒 0，判据根本不可靠。

新架构把判定全部挪出异步窗口：

| 段 | 动作 | 要点 |
|---|---|---|
| ① 规划 | 读 1 次引擎树 + 1 次 memread 真值 | 纯内存推演出执行计划（plan） |
| ② 执行 | 照单**盲加** | 不判定、不重读；`pcall` 抛错即停 |
| ③ 对账 | 延迟 memread **差分**（现值 − 执行前快照） | 真学到的出队；被拒的原位保留；计划外增量（玩家手点）同步删队列份 |

- **memread 真值是唯一裁决信源**；引擎只是最终执行者；
- 未确认单据**随存档保留**，读档后先对账、再开放新结算；
- 配套重入守卫：`SETTLE.executing`（连升级 1 秒多轮不互踩）、`rerun_after`（被守卫挂起的回头补跑）、`audit_scheduled`（对账闹钟防抖）。

> 🩸 可借鉴：凡是「写操作后要立刻读结果」的战役 MOD，都该用「快照 → 盲写 → 延迟差分对账」，不要在异步窗口里边写边读。

### 3.4 自动加点事件链（apply 模块）

| 监听 | 角色 | 备注 |
|---|---|---|
| `CharacterSkillPointAvailable` | **主驱动**：有可用点数 → 结算一轮 | 事件过滤 `true`，回调内 pcall |
| `CharacterSkillPointAllocated` | 注册了但**实测不派发** | 注释明示「实际依赖轮询」，不可依赖 |
| `WorldStartRound` | **可靠兜底**：每回合轮询技能点变化 | 不依赖事件名，防漏 |

手动行为同步：玩家在原版界面上手点的技能，经 `sync_manual_spent` / `reconcile_manual` 以 memread 真值判脏，同步出队，避免「队列里还排着玩家已经学了的东西」。

### 3.5 一键补全的优先级语义（core.fill_queue）

- **候选**：已学 ∪ 当前队列 = satisfied 起点；背景技能 / 引擎白送的「半自动技能」（`s.auto_manual`，前 N 级引擎自动送）豁免，不占队列不花点；
- **优先级**：正常技能按「解锁等级刚到 > 层级 > 引擎 active」等分层（pri 1~4）；
- 🩸 **堆叠技能垫底（用户定案）**：登峰造极 / 额外技能点这类「加技能点」的技能（UI 按 effect 识别）**参与一切判定**（候选、等级拦截、断口扫描），只在选点优先级垫底（pri=5）——有正常技能可排就让位，某轮无正常可排（等级空档）才入队填空、**不空跳断口**；
- **多级技能记次数**（`queued_n`）：入队过的多级技能知道自己排了几次，可继续排下一级（否则永远只学 1 级）；
- 「撤销补全」**不做**（§0.8.5 定案），连快照都不生成。

### 3.6 已学顺序还原（core.order_learned，供「读取加点技能」）

把角色 1..R 级之间学过的技能反推出合理顺序：两遍扫描（第 1 遍严格前置 REQUIRED/SUBSET，全挑不出才用引擎 active 兜底）、**进度等级按轮次推进**（不是按已排项数——角色可能「等级高、点数少」，按项数推永远轮不到 need=6 的技能）、5000 轮守卫防死循环、进度等级上限 = 真实等级+1（推不出去的交给末尾兜底）。

---

## 四、UI 设计（5 个 TWUI + 10,737 行控制器）

### 4.1 界面资产

| 文件 | 行数 | 作用 |
|---|---:|---|
| `skillpreset_queue_panel.twui.xml` | 1,094 | **主浮层**：面板本体 + 九宫格（parchment_divider）+ 标题条 + 可滚动列表（`listview > list_clip > list_box + vslider`，原版 parchment_slider_vertical）+ 按钮区（模拟升级 / 一键补全 / 保存 / 读取加点技能） |
| `skillpreset_row.twui.xml` | 563 | 队列行（386×67）：序号 + **复刻 CSQ 的技能卡**（`CSQ_card.twui.xml` 抄来的原版观感）+ 置顶/删除按钮；**纯 ASCII**，显示文字全部由 Lua 用 UTF-8 设置 |
| `skillpreset_skill_overlay.twui.xml` | 129 | **技能卡内透明点击层**：Lua 在每张原版技能卡里 `card:CreateComponent('sp_skill_overlay', …)`，捕获点击入队；状态 available / locked |
| `skillpreset_queue_tooltip.twui.xml` | 380 | 队列行自定义 tooltip（标题 / 描述 / 效果） |
| `skillpreset_template_dialog.twui.xml` | 655 | 模板管理弹窗（滚动列表同主面板结构；含 `magic_flame` 材质装饰） |
| `skillpreset_template_row.twui.xml` | 234 | 模板行（Hover / Selected / SelectedHover 四态） |
| `icon_rank_up.png` | 862 B | 技能卡角标「升到 N 级」小图标 |

### 4.2 交互设计要点

- **独立浮层，不注入原版面板**（需求 2.3）：面板**跟随原版技能树的高度与位置**（CSQ 模式两步：宽度让开树、高度贴树框，2026-10-02 布局 v2 定案「贴右上角、下部贴技能树的框」），既不遮树、也不被非 16:9 分辨率破坏；
- **只在技能页面显示**：双判据（页签点击 + 技能子面板可见性），面板关闭时轮询进入「零查找」模式；
- **点击层挂在卡内**：原版技能卡照常可点，透明层只接管「入队」语义，带 available/locked 两态与角标；
- **模板弹窗**：新增 / 修改 / 删除 / **就地重命名**（行名变输入框、按钮变对勾）/ 删除确认（照抄原版确认弹窗，不自搭 UI）；**滚动锁**（`ComponentMoved` 守卫：弹窗滚动不许穿透影响下面技能页）；
- **性能闸门**：行悬停高亮的 `ComponentMouseOn/Off` 监听在**弹窗没开时直接放行**（大地图上成百上千组件不再进回调）；
- **双语**：mod loc 单文件、键带 `_en` 后缀，Lua 判语言取键（原版 loc 命名空间不区分语言的第三方惯例做法）；
- **三根等级轴，任何交叉以此为准**（2026-09-23 用户定案）：① 角色真实等级；② 队列「模拟起点」（存在队列数据里，`set_rank_ctx`，跟存档走）；③ 虚拟模拟轴（整块隔离，`SIM_ENABLED=false`，恢复=改回 true，代码全保留）。

---

## 五、存储设计（两套持久化，泾渭分明）

### 5.1 模板 → 本地文件（不进存档）

```
%APPDATA%\The Creative Assembly\Warhammer3\scripts\skillpreset\
    <subtype>\tpl_001.lua        -- 模板本体（Lua 表字面量格式）
    <subtype>\_index.lua         -- 索引：显示名 ↔ 文件名 ↔ 修改时间
```

- **按 agent_subtype 分目录**：模板天然跟角色类型走（决策：同类合并展示，粒度对齐 `recruitment_category`，见 §2.1 subtype_kind）；
- 🩸 **文件名一律 ASCII 序号（tpl_001.lua），中文显示名存索引** —— 实测本环境 `io.open` 无法写中文文件名；
- 🩸 **解析全程不用 `loadstring`，纯字符串解析** —— 模板在玩家可自由编辑的目录里，执行其内容始终是风险面；而模板语义只是「一串技能 key」，纯解析既能表达完整语义，又能 **100% 杜绝代码执行**（比「白名单 + loadstring」更稳）；
- 索引损坏可**自恢复**（扫目录重建）。

### 5.2 实时队列 → 存档（`save_named_value` / `load_named_value`）

- 按角色 cqi 索引：`{ [cqi] = { items={...}, source="模板名", mtime=... } }`；
- 用原版标准持久化 API（源码依据 `lib_campaign_manager.lua:1325/1737`，参照 `wh_dlc08_norsca.lua:125-135` 用法）；
- 🩸🩸 **注册时机是生死线**：`cm:add_saving_game_callback / add_loading_game_callback` 必须挂在**文件顶层** —— 引擎入口函数 55 秒才被调用，赶不上 `LoadingGame` 事件 ⇒ **2026-09-29 曾因此丢整个队列**（存档回调注册晚于读档）。

---

## 六、兼容性、风险与评价

| 维度 | 评价 |
|---|---|
| 原版兼容 | **极好**：0 张 DB 表，纯 script/ui/text，不覆盖任何原版资源；卸载即消失，无残留 |
| 跨 MOD | 不注入原版面板、不抢组件（浮层 + 卡内子组件 + 事件过滤），与同类 UI MOD（CSQ 等）共存的写法都对齐了「只读别人、只写自己」原则 |
| 版本风险 | **memread 偏移随游戏版本漂移**是最大软肋 —— 全部失败路径返回 nil，降级后功能受限但不崩；这是「内存读取」路线的固有代价 |
| 数据风险 | 原版更新导致模板里 skill key 失效：套用时有 `validate_queue` / 换模板冲突提示兜底，且**从不撤销已学**，最坏情况是队列项滞留 |
| 安全 | 玩家目录零代码执行（无 loadstring）；引擎调用全程 pcall 化；高频回调有性能闸门 |
| 工程化 | **标杆级**：需求文档章节号（§0.8.6/§4.2.4…）与决策编号（D1/D9）贯穿注释；M0 实测先行（每个关键 API 标注「M0 已验证」）；教训用 🩸 分级标注；自动生成表带「请勿手改」头；日志开关（VERBOSE_UI）分级；局部变量 200 上限都有意识规避（`precheck 警告 199 的教训`） |

**争议点 / 可讨论**：
1. 依赖 `memreader` 读取进程内存——功能上无可替代（引擎不吐真值），但属于脆弱路线，游戏大版本更新后必须跟着修偏移；
2. UI 文件 10,737 行偏巨型（三根等级轴、模板弹窗、几何跟随、双语全在一个文件里），可读性靠注释纪律而非拆分维持；
3. `CharacterSkillPointAllocated` 注册了却不可用（引擎不派发），留了一个「死监听」占位——注释里讲清了原因，算诚实的妥协。

---

## 七、🩸 可借鉴经验汇总（下次做同类 MOD 照抄）

1. **读技能树**：用 CCO 表达式 `SkillList.JoinString(...)` 一次拿整棵树；固定 8 字段、`|`/`;` 分隔；**禁用 `gmatch("[^;]+")`**（跳空字段必错位）。
2. **CA 的 `string.find` 只收 2~3 参**：模式匹配一律 `string.find_lua` 或先判第四参兼容。
3. **写后必异步**：`cm:add_skill` 后引擎内存异步刷新，同结算内读不到新值 ⇒ **三段式**（规划读快照 → 盲加 → 延迟 memread 差分对账），「真值是唯一裁决信源」。
4. **存档回调必须在文件顶层注册**：引擎同名入口函数 55s 才跑，赶不上 LoadingGame——晚注册 = 读档丢数据（09-29 事故）。
5. **`CharacterSkillPointAllocated` 实测不派发**：自动加点要么挂 `CharacterSkillPointAvailable`，要么 `WorldStartRound` 轮询兜底。
6. **玩家可编辑目录禁 `loadstring`**：纯字符串解析 Lua 表字面量即可表达「key 列表」语义。
7. **中文文件名 `io.open` 写不进去**：文件名用 ASCII 序号，显示名进索引。
8. **引擎拿不到解锁等级**（`UnlockedAtRank`=0、`RankRequired` 恒 0）：需要真值只能 memread；读取等级与读取规则分开，失败即 nil 降级。
9. **浮层三原则**：`interactive="false"` 不拦原版鼠标；几何以原版技能树为基准跟随（让开宽度、贴住高度）；高频监听（悬停等）必须加「弹窗开着才生效」的过滤闸门。
10. **`find_uicomponent` 依赖 `arg`，不可塞进 pcall 匿名函数**；裸 `Parent()` 指针不能直接索引。
11. **主 chunk 顶层 local 上限 200**：接近就合并成一张状态表（该 MOD 的 `SETTLE` 就是这么做的）。
12. **关键日志只走控制台 `out()`**：曾试过「关键行落盘」结果两次闪退（"is not a ui component" ×57~60），已回退；要留证据就做**开关式明细**（VERBOSE_UI），默认只出事件级日志。
13. **尺寸/布局参数照抄能跑通的参照 MOD**（CSQ / CLC / MCT），不要自己发明——与外籍军营筛选排（《全种族招募》v33~v40）踩的坑完全同源。
14. **换模板永不撤销已学**：只提示冲突数（`注意：有 %d 个已生效技能不在新模板里…`），把「要不要完全一致」的决定权交还玩家（用原版重置）。

---

## 附录 A · 包内文件清单（15 资源）

| 包内路径 | 大小 | 说明 |
|---|---:|---|
| `script/campaign/mod/skillpreset_core.lua` | 152,581 | 加点内核（树解析/校验/队列/三段式/补全/排序） |
| `script/campaign/mod/skillpreset_ui.lua` | 610,279 | UI 控制器（浮层/模板弹窗/点击层/双语/几何） |
| `script/campaign/mod/skillpreset_apply.lua` | 56,389 | 模板应用 + 实时队列 + 事件 + 存档持久化 |
| `script/campaign/mod/skillpreset_storage.lua` | 24,986 | 模板文件存储（%APPDATA%、索引、安全解析） |
| `script/campaign/mod/skillpreset_subtype_kind.lua` | 34,142 | 自动生成：subtype → 类型名 loc key |
| `script/campaign/mod/skillpreset_memread.lua` | 13,335 | memreader 内存读取（真值层） |
| `text/db/skillpreset_ui.loc` | 2,768(TSV) | 中英双语 UI 文本（22 组键 ×2） |
| `ui/skillpreset/skillpreset_queue_panel.twui.xml` | 43,885 | 主浮层面板 |
| `ui/skillpreset/skillpreset_queue_tooltip.twui.xml` | 27,474 | 队列行 tooltip |
| `ui/skillpreset/skillpreset_row.twui.xml` | 22,327 | 队列行（原版观感技能卡） |
| `ui/skillpreset/skillpreset_template_dialog.twui.xml` | 23,571 | 模板管理弹窗 |
| `ui/skillpreset/skillpreset_template_row.twui.xml` | 8,335 | 模板行 |
| `ui/skillpreset/skillpreset_skill_overlay.twui.xml` | 5,086 | 技能卡透明点击层 |
| `ui/skillpreset/icon_rank_up.png` | 862 | 「升到 N 级」角标 |
| `dependencies_manager_v2.rpfm_reserved` | 2（`[]`） | RPFM 依赖声明：空 |

> 解包产物在 `E:\战锤mod\_analysis_skillpreset\`（loc 已转 TSV，另生成 RPFM 的 notes/settings 两个保留文件，非包内资源）。

## 附录 B · 主要公开接口（供后续参考/复用判断）

```
SkillPreset.core    parse_tree / read_tree_raw / get_points_available
                    check_prerequisites / validate_queue / normalize_queue
                    queue_push / queue_remove_at / queue_move_to / queue_pin_to_earliest
                    read_true_levels / read_character_snapshot
                    plan_strict_head / execute_plan / begin_audit / run_audit(apply侧调度)
                    simulate_queue / fill_queue / order_learned
SkillPreset.apply   apply_template / switch_template / normalize_template_list
                    process_queue / set_queue / clear_queue / get_queue
                    init_events / poll_skill_points / sync_manual_spent / reconcile_manual
                    add_saving_game_callback(顶层) / on_loading_game(顶层)
SkillPreset.storage list_templates / load_template / save_template
                    delete_template / rename_template / read_index / write_index
SkillPreset.memread load_levels / load_prereqs / load_prereq_points
                    load_unlock_ranks / experience_points / rank_cap
SkillPreset.ui      init_ui / refresh / sim_reset / sim_state / sim_levelup(隔离)
                    （确认弹窗照原版做法；模板弹窗含就地重命名与滚动锁）
```

---

*分析：ZCode（RPFM CLI 4.0.4 解包 + 全量源码审读）· 2026-10-05*
