# -*- coding: utf-8 -*-
"""战锤3技能包本机适配重放（配合 sync_wh3_skills.ps1 使用）。

上游 https://github.com/scnjwyc/warhammer3-mod-development-skill 的内容与本机有 4 类固定差异。
sync_wh3_skills.ps1 每次刷新会整体替换技能目录，本脚本在刷新后重放这些差异。
幂等：重复执行无副作用；上游改版导致原文字样找不到时，以退出码 2 报警，不猜测改法。

用法：python -X utf8 tools/apply_wh3_skill_adaptations.py [目标skills目录 ...]
不带参数时刷全部 3 处默认安装位。
"""
import io
import os
import sys

ADAPT_DEV = "warhammer-mod-development"
ADAPT_TR = "warhammer-mod-translation"

SCHEMA_ROW_OLD = "| schema | 本机 RPFM 配置中的 `schema_wh3.ron`，随游戏版本核对 |"
SCHEMA_ROW_NEW = ("| schema | 本机用工程固化版 `E:\\战锤mod\\tools\\rpfm-schema\\schema_wh3.ron`"
                  "（备用 RPFM 缓存 `%APPDATA%\\FrodoWazEre\\rpfm\\config\\schemas\\schema_wh3.ron`，"
                  "均无需联网 update），随游戏版本核对 |")

LOC_TABLE_OLD = "`多语言/localisation__.loc_CN.tsv`"
LOC_TABLE_NEW = "`多语言/localisation__CN.loc.tsv`"

LOC_NAME_OLD = "localisation__.loc_CN.tsv"
LOC_NAME_NEW = "localisation__CN.loc.tsv"

LOCAL_SECTION_HEADING = "## 本机实例（E:\\战锤mod）"
LOCAL_SECTION = """## 本机实例（E:\\战锤mod）

| 项 | 本机路径 |
|---|---|
| 工作区 | `E:\\战锤mod` |
| 游戏源码 | `E:\\战锤mod\\源码`（原版脚本文档在 `源码\\documentation\\script`） |
| MOD 源 | `E:\\战锤mod\\mod` |
| 本地化 | `E:\\战锤mod\\多语言`，中文原版库为 `多语言\\localisation__CN.loc.tsv` |
| 本机工具 | rpfm_cli、打包.ps1、部署脚本、RPFM Server MCP 等一律以 `E:\\战锤mod\\工具清单.md` 为准 |
"""

DEAD_ROW = "| 与龙同行本体更新后的精简补丁 | [精简补丁同步](../warhammer-wwd-lite-patch/SKILL.md) |\n"

# 2026-10-05 本机新增专题：SkillPreset（第三方技能预设 MOD）逆向分析设计文档。
# 母本 = 工程设计文档（唯一编辑入口）；同步刷新整体替换技能目录后，
# 靠下面两步重灌：① 专题文件复制进 references/topics/，② SKILL.md 追加导航行。
TOPIC_SOURCE = r"E:\战锤mod\设计文档\技能预设·SkillPreset·第三方MOD分析设计文档.md"
TOPIC_NAME = "技能预设·SkillPreset·第三方MOD分析设计文档.md"
TOPIC_ANCHOR = "| Lua 监听、初始化、存档、API | [Lua 约定与示例](references/lua_api.md) |"
TOPIC_ROW = ("\n| 技能加点/技能树 MOD 的实现范式（CCO 读树、三段式结算、memread 真值、"
             "存档回调时机、UI 浮层铁律） | [SkillPreset 分析专题](references/topics/"
             + TOPIC_NAME + ") |")

# 2026-10-02 本机实战补充：追加到 warhammer-mod-development/references/pack-workflow.md 末尾。
# 内容与 tools/_skill_practice_section.py 保持一致（该文件仅为文本源，改内容两处同步改）。
PRACTICE_HEADING = "## 表结构升版与第三方包修复（9.0.x 实战补充 · 2026-10-02）"

PRACTICE_SECTION = PRACTICE_HEADING + """

对任意第三方/自有 pack 的 DB 表升版与「启动 DB 崩溃」修复，按以下本机验证过的口径执行：

1. **结构对比**：包内 `db/**` 全量 `extract_packed_files(export_as_tsv=true)`，按表头第 2 行 `#表名;版本;路径` 与当前原版对比。原版参照**不全在 `data\\db.pack`**（部分表在其他原版包）——本地对照不到时不要猜，改用依赖库口径：直接对该表 `update_table`，由 RPFM 依依赖库判定，三态结果：返回 `[旧版,新版,[],[新增列]]` = 升级、`already has the newer definition` = 已最新、`cannot be found in the Game Files` = 纯自定义表（正常，不升）。
2. **升版落地**：「并回原包」`open_packfiles → (import_tsv 载入新内容) → update_table → save_pack_as`，PFH 头保真。新列由 RPFM 按默认值填充：`land_units_to_unit_abilites_junctions` 新增的 `culture` 列填 `*`（与原版惯例一致，**勿留空**）。验收 = 文件清单逐项一致 + 行数零变化 + 回读版本达标。
3. **部署**：先备份原包到 `mod\\_备份原包\\<包名>.pre-<标记>.pack` 并 SHA256 复核，再覆盖目标（`data\\` 或工坊 content 目录），双端核哈希；回滚 = 把备份拷回。写 `D:\\` 需用户针对该次写入明确授权，且游戏必须关闭。
4. **启动 DB 崩溃（"The first invalid database record is ..."）排查**：对话框里的键 = 关键表键值拼接。① 先核对键面：引用键在**当前版本**原版/包内是否存在（原版数据要从当前版本重导，旧快照会误导）；② 最常见根因是**旧版本表结构**（引擎按新布局读旧表）→ 升表结构即愈，不必先怀疑数据行；10-03 用户实测最终证实：把 MOD 拆分后**逐包刷新表结构**即可正常游玩——对话框只点第一个无效记录的包，修复必须覆盖**所有启用包**的落后表；③ 悬空引用审计：对 junction/桥表按「列名→目标表」映射逐格核对，键空间 = 包内各表首列 ∪ 当前原版 ∪ 加载清单内其他包；注意 variantmeshdefinition/material/dds 等是**文件引用不是 DB 键**，勿混入审计。
5. **`unit_attributes_tables` 自定义键**：09-27 曾归因「封闭枚举自定义键必崩」，但 10-03 干净 A/B（仅恢复 `miao_cth_alchemy_artillery` 3 个自定义键）正常过加载——**必崩结论已证伪，勿再预防性清零**；自定义键无引擎行为（仅 bullet_text 等 UI 作用），处理原则：保留键以保住引用链完整性。
6. **从工程树/Lazy 拆分或回填的坑**：工程树 TSV 声明版本可能落后，**列序也可能错**（`character_skill_node_sets_tables` 4 文件曾以旧布局冒充当前版本）——从树 `import_tsv` 前必须核对树文件表头与当前原版列序一致，否则串列损坏数据；loc 在树中存 `.loc.tsv`（`#Loc;1;...`），用 `import_tsv` 回填 `.loc` 路径。
7. **MCP 参数备忘**：`extract_packed_files`/`delete_packed_files` 的路径参数要传 **JSON 字符串**；`add_packed_files` = `source_paths`(磁盘路径数组) + `destination_paths`(ContainerPath 的 JSON 字符串，逐文件对应)；`new_packed_file` 的 `new_file={"DB":[文件名,表名,版本]}` 后再 `import_tsv`+`update_table`；MCP driver 单步 stdout 约 20 KB 截断——大清单核对一律落盘后用脚本读，勿解析 stdout；server 掉线按 `工具清单.md` 重启（非沙箱、隐藏窗口、等 45127 就绪）。
"""

DEFAULT_TARGETS = [
    r"E:\战锤mod\.trae\skills",
    os.path.join(os.environ.get("USERPROFILE", ""), ".zcode", "skills"),
    os.path.join(os.environ.get("USERPROFILE", ""), ".trae-cn", "skills"),
]


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def adapt(target):
    """返回 (改动列表, 缺失原文的警告列表)。"""
    changes, warns = [], []

    p = os.path.join(target, ADAPT_DEV, "references", "project_structure.md")
    s = read(p)
    if LOC_TABLE_OLD in s:
        s = s.replace(LOC_TABLE_OLD, LOC_TABLE_NEW)
        changes.append("project_structure.md: loc 文件名")
    elif LOC_TABLE_NEW not in s:
        warns.append("project_structure.md: loc 表行原样与新样都未命中（上游改版？）")
    if SCHEMA_ROW_OLD in s:
        s = s.replace(SCHEMA_ROW_OLD, SCHEMA_ROW_NEW)
        changes.append("project_structure.md: schema 行")
    elif SCHEMA_ROW_NEW not in s:
        warns.append("project_structure.md: schema 行原样与新样都未命中（上游改版？）")
    if LOCAL_SECTION_HEADING not in s:
        s = s.rstrip("\n") + "\n\n" + LOCAL_SECTION
        changes.append("project_structure.md: 追加本机实例")
    write(p, s)

    p = os.path.join(target, ADAPT_TR, "references", "terminology-cases.md")
    s = read(p)
    n = s.count(LOC_NAME_OLD)
    if n:
        s = s.replace(LOC_NAME_OLD, LOC_NAME_NEW)
        changes.append("terminology-cases.md: loc 文件名 ×%d" % n)
    elif LOC_NAME_NEW not in s:
        warns.append("terminology-cases.md: loc 文件名原样与新样都未命中（上游改版？）")
    write(p, s)

    p = os.path.join(target, ADAPT_DEV, "SKILL.md")
    s = read(p)
    if DEAD_ROW in s:
        s = s.replace(DEAD_ROW, "")
        changes.append("SKILL.md: 删除 wwd-lite 死链行")
    elif "wwd-lite" in s:
        warns.append("SKILL.md: wwd-lite 引用以未知形式出现，需人工检查")
    write(p, s)

    p = os.path.join(target, ADAPT_DEV, "references", "pack-workflow.md")
    s = read(p)
    if PRACTICE_HEADING not in s:
        s = s.rstrip("\n") + "\n\n" + PRACTICE_SECTION
        changes.append("pack-workflow.md: 追加 9.0.x 实战补充")
    write(p, s)

    try:
        src_text = read(TOPIC_SOURCE)
    except (OSError, IOError):
        src_text = None
        warns.append("SkillPreset 母本缺失：%s" % TOPIC_SOURCE)
    if src_text is not None:
        topics_dir = os.path.join(target, ADAPT_DEV, "references", "topics")
        dst = os.path.join(topics_dir, TOPIC_NAME)
        if not os.path.exists(dst) or read(dst) != src_text:
            write(dst, src_text)
            changes.append("topics: 重灌 SkillPreset 分析专题")

        p = os.path.join(target, ADAPT_DEV, "SKILL.md")
        s = read(p)
        if TOPIC_NAME not in s:
            if TOPIC_ANCHOR in s:
                s = s.replace(TOPIC_ANCHOR, TOPIC_ANCHOR + TOPIC_ROW)
                changes.append("SKILL.md: 追加 SkillPreset 分析专题导航行")
            else:
                warns.append("SKILL.md: Lua 行锚点未命中，专题导航行未插入（上游改版？）")
        write(p, s)

    return changes, warns


def main():
    targets = sys.argv[1:] or DEFAULT_TARGETS
    any_warn = False
    for t in targets:
        if not os.path.isdir(t):
            print("[跳过] 目录不存在：%s" % t)
            continue
        try:
            changes, warns = adapt(t)
        except (OSError, IOError) as e:
            print("[失败] %s：%s" % (t, e))
            any_warn = True
            continue
        for c in changes:
            print("[%s] 已适配：%s" % (t, c))
        if not changes:
            print("[%s] 已是适配状态，无改动" % t)
        for w in warns:
            print("[%s] 警告：%s" % (t, w))
            any_warn = True
    if any_warn:
        print("\n存在未命中的适配点：上游可能已改版，请人工核对后更新本脚本。")
        sys.exit(2)
    print("\n全部适配完成。")


if __name__ == "__main__":
    main()
