#Requires -Version 5.1
<#
.SYNOPSIS
  同步「战锤3 MOD 开发技能包」到本机 3 处技能目录。

.DESCRIPTION
  上游仓库：https://github.com/scnjwyc/warhammer3-mod-development-skill
  流程：读取远端 main 最新 commit SHA → 与本地 state 比对 → 有更新才下载 zip →
        逐个目标目录「备份旧安装 → 整体替换 → 校验 → 重放本机适配」 → 写 state。

  本机适配由 tools\apply_wh3_skill_adaptations.py 重放（上游与本机的固定差异：固化 schema 路径、
  中文原版库文件名、本机实例段、wwd-lite 死链行、重灌 SkillPreset 分析专题到 topics+SKILL.md 导航），幂等；上游改版导致字样找不到时该脚本退出码 2 报警。

  默认刷 3 处：
    E:\战锤mod\.trae\skills                    （项目级，本会话使用）
    %USERPROFILE%\.zcode\skills                （ZCode 全局）
    %USERPROFILE%\.trae-cn\skills              （Trae 全局）

  定期刷新用法（在工程根目录 E:\战锤mod 执行）：
    powershell -ExecutionPolicy Bypass -File .\tools\sync_wh3_skills.ps1 -Check   # 只查有无更新
    powershell -ExecutionPolicy Bypass -File .\tools\sync_wh3_skills.ps1          # 有更新才安装
    powershell -ExecutionPolicy Bypass -File .\tools\sync_wh3_skills.ps1 -Force   # 强制重装当前远端版本
    powershell -ExecutionPolicy Bypass -File .\tools\sync_wh3_skills.ps1 -Target 'D:\some\skills'   # 只刷指定目录

  只操作各目标目录下的 `warhammer-*` 技能目录，不碰 README 等本机维护文件，不触碰游戏目录。

.NOTES
  本文件须保存为 UTF-8 with BOM（PowerShell 5.1 否则把中文读成乱码）。
#>
[CmdletBinding()]
param(
    [string[]]$Target,
    [string]$BackupRoot,
    [switch]$Check,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Target -or $Target.Count -eq 0) {
    $Target = @(
        (Join-Path $projectRoot '.trae\skills'),
        (Join-Path $env:USERPROFILE '.zcode\skills'),
        (Join-Path $env:USERPROFILE '.trae-cn\skills')
    )
}
if (-not $BackupRoot) { $BackupRoot = Join-Path $PSScriptRoot '_wh3skills_backup' }

$RepoUrl   = 'https://github.com/scnjwyc/warhammer3-mod-development-skill'
$AtomUrl   = "$RepoUrl/commits/main.atom"
$ZipUrl    = 'https://codeload.github.com/scnjwyc/warhammer3-mod-development-skill/zip/refs/heads/main'
$StatePath = Join-Path $PSScriptRoot '_wh3skill_state.json'

function Get-RemoteSha {
    $atom = Invoke-WebRequest -Uri $AtomUrl -UseBasicParsing -TimeoutSec 60
    $m = [regex]::Match([string]$atom.Content, 'Grit::Commit/([0-9a-f]{40})')
    if (-not $m.Success) { throw '无法从上游 atom feed 解析 commit SHA（网络失败或仓库结构变更）' }
    $m.Groups[1].Value
}

function Get-TargetTag([string]$Path) {
    $full = $Path.TrimEnd('\')
    $leaf = Split-Path $full -Leaf
    $parent = Split-Path (Split-Path $full -Parent) -Leaf
    ($parent + '-' + $leaf) -replace '[\\/:*?"<>|]', '_'
}

function Test-SameTree([string]$A, [string]$B) {
    $a = @(Get-ChildItem $A -Recurse -File -ErrorAction SilentlyContinue)
    $b = @(Get-ChildItem $B -Recurse -File -ErrorAction SilentlyContinue)
    if ($a.Count -ne $b.Count) { return $false }
    ($a | Measure-Object Length -Sum).Sum -eq ($b | Measure-Object Length -Sum).Sum
}

$remoteSha = Get-RemoteSha
$localSha = $null
if (Test-Path $StatePath) {
    try { $localSha = (Get-Content $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json).sha } catch { $localSha = $null }
}

Write-Host "上游仓库：$RepoUrl"
Write-Host "远端 SHA：$remoteSha"
Write-Host ("本地 SHA：{0}" -f $(if ($localSha) { $localSha } else { '(未记录)' }))
Write-Host '目标目录：'
foreach ($t in $Target) { Write-Host ("  {0}{1}" -f $t, $(if (Test-Path $t) { '' } else { '   [不存在，将跳过]' })) }

if ($localSha -eq $remoteSha -and -not $Force) {
    Write-Host '已是最新，无需同步。' -ForegroundColor Green
    return
}
if ($Check) {
    Write-Host '检测到新版本，去掉 -Check 即可同步。' -ForegroundColor Yellow
    return
}

$tmp = Join-Path $env:TEMP ('wh3skill_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    $zip = Join-Path $tmp 'bundle.zip'
    Write-Host '下载技能包 …'
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zip -UseBasicParsing -TimeoutSec 600
    Write-Host ('下载完成：{0:N1} MB' -f ((Get-Item $zip).Length / 1MB))
    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    $srcSkills = Join-Path $tmp 'warhammer3-mod-development-skill-main\skills'
    if (-not (Test-Path $srcSkills)) { throw "包结构异常：$srcSkills 不存在" }
    $srcDirs = @(Get-ChildItem $srcSkills -Directory)
    if ($srcDirs.Count -eq 0) { throw '包结构异常：skills/ 下没有技能目录' }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $results = @()

    # 安装后需重放的本机适配（幂等；上游改版导致原文字样找不到时，该脚本以退出码 2 报警）
    $adaptScript = Join-Path $PSScriptRoot 'apply_wh3_skill_adaptations.py'
    $python = $null
    if (Test-Path $adaptScript) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
    if (-not $python) { Write-Warning '未找到 python 或 apply_wh3_skill_adaptations.py，本次跳过本机适配重放' }

    foreach ($t in $Target) {
        if (-not (Test-Path $t)) { Write-Warning "跳过（目录不存在）：$t"; continue }

        $bk = Join-Path $BackupRoot ("${stamp}_" + (Get-TargetTag $t))
        New-Item -ItemType Directory -Path $bk -Force | Out-Null

        $old = @(Get-ChildItem $t -Directory -Filter 'warhammer-*' -ErrorAction SilentlyContinue)
        foreach ($d in $old) { Move-Item -LiteralPath $d.FullName -Destination (Join-Path $bk $d.Name) }

        $installed = @()
        foreach ($d in $srcDirs) {
            Copy-Item -LiteralPath $d.FullName -Destination (Join-Path $t $d.Name) -Recurse -Force
            $installed += $d.Name
        }

        $bad = @()
        foreach ($n in $installed) {
            if (-not (Test-SameTree (Join-Path $srcSkills $n) (Join-Path $t $n))) { $bad += $n }
        }
        if ($bad.Count -gt 0) { throw ("[$t] 复制校验失败：" + ($bad -join ', ')) }

        $adaptOk = $true
        if ($python) {
            & $python -X utf8 $adaptScript $t 2>&1 | ForEach-Object { Write-Host ("    $_") }
            if ($LASTEXITCODE -ne 0) {
                $adaptOk = $false
                Write-Warning "[$t] 本机适配未完全命中（退出码 $LASTEXITCODE），需人工核对"
            }
        }

        Write-Host ("[{0}] 旧安装备份 {1} 个 → {2}；装入 {3} 个；本机适配 {4}" -f $t, $old.Count, $bk, $installed.Count, $(if ($adaptOk) { '已重放' } else { '未完全命中' })) -ForegroundColor Green
        $results += [ordered]@{ target = $t; backup = $bk; replaced = $old.Count; skills = $installed; adapted = $adaptOk }
    }

    if ($results.Count -eq 0) { throw '没有任何目标目录可用，未做任何写入。' }

    $state = [ordered]@{
        repo    = $RepoUrl
        sha     = $remoteSha
        updated = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        targets = $results
    }
    ($state | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $StatePath -Encoding UTF8

    Write-Host ("完成：已刷新 {0} 处，commit {1}" -f $results.Count, $remoteSha) -ForegroundColor Green
    Write-Host '重载技能或开启新会话后生效。' -ForegroundColor Yellow
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
