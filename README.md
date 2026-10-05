# 战锤3 MOD · 会话产物

本仓库存放战锤3 MOD 工程的部分产物，当前为 2026-10-05「技能预设（SkillPreset）第三方 MOD 逆向分析」一批文件。路径与工程（`E:\战锤mod`，私有备份仓库 `warhammer3-mod-workspace`）保持一致。

## 本批内容（2026-10-05）

| 文件 | 说明 |
|---|---|
| `设计文档/技能预设·SkillPreset·第三方MOD分析设计文档.md` | **母本**：对第三方 MOD `skillpreset.pack`（技能加点管理器，纯 Lua/UI、零 DB 表）的逆向分析——架构、三段式结算、memread 内存读取、存储与 UI 设计、14 条可借鉴铁律 |
| `.trae/skills/warhammer-mod-development/references/topics/技能预设·SkillPreset·第三方MOD分析设计文档.md` | 专题副本：灌入本机技能包 `warhammer-mod-development` 的 topics（3 处安装位内容一致，此处为项目级） |
| `.trae/skills/warhammer-mod-development/SKILL.md` | 技能包入口：Lua 任务行后新增「SkillPreset 分析专题」导航行 |
| `tools/apply_wh3_skill_adaptations.py` | 本机适配重放脚本：新增第 4 类固定差异（母本 → topics 重灌 + SKILL.md 导航行重放），保证技能包同步刷新不丢专题 |
| `tools/sync_wh3_skills.ps1` | 技能包同步器：头注释同步更新适配清单 |
| `工具清单.md` | 本机工具清单：适配说明一行更新 |

## 相关仓库

- 私有工程备份：`z6554535/warhammer3-mod-workspace`（全工程，按 .gitignore 口径）
- 技能包上游：`scnjwyc/warhammer3-mod-development-skill`（本批专题尚未合入上游，暂由 `apply_wh3_skill_adaptations.py` 本机重放兜底）
