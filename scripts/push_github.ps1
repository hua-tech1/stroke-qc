# 把本地仓库同步到 GitHub（hua-tech1）
#
# 背景（实测于本机）：
#   - GitHub 用户名是 hua-tech1（带连字符），不是 hua_tech1
#   - 远端 stroke-qc 已存在（83 文件，2026-11-21 的旧快照），本地为全新历史
#     => 两边没有共同祖先，直接 push 到 main 会被拒绝
#   - 本机 git 配了一个已失效的代理 127.0.0.1:7890，导致 git 完全连不上 GitHub
#     （而 PowerShell 直连 API 是通的，说明只是 git 的代理配置问题）
#
# 用法（仓库根目录，任选）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\push_github.ps1
#   powershell ... -File scripts\push_github.ps1 -Branch sync-local   # 默认：推到新分支，不动 main
#   powershell ... -File scripts\push_github.ps1 -Force               # 覆盖远端 main（不可逆）
#
# 默认行为是**非破坏性**的：推到 sync-local 分支，你可以在 GitHub 上对比后再合并。
# 需要账号凭据；脚本会触发系统凭据窗口，不读取也不保存任何 token。

param(
  [string]$Owner = "hua-tech1",
  [string]$Repo  = "stroke-qc",
  [string]$Branch = "sync-local",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Fail($m) { Write-Host "`n[中止] $m" -ForegroundColor Red; exit 1 }

# ---------- 1. 代理体检 ----------
$httpProxy  = git config --get http.proxy
$httpsProxy = git config --get https.proxy
Write-Host "git 代理配置：http='$httpProxy' https='$httpsProxy'"

# ---------- 2. 远端可达性（代理 / 直连 各试一次）----------
$url = "https://github.com/$Owner/$Repo.git"
$env:GIT_TERMINAL_PROMPT = "0"
$ErrorActionPreference = "Continue"

# 候选：先试已配置的代理，再自动探测常见端口，最后试直连
$modes = @()
if ($httpProxy -or $httpsProxy) { $modes += @{ Name = "配置的代理 $httpProxy"; Args = @() } }
foreach ($port in @(7877, 7890, 7891, 7892, 1080, 1081, 10808, 10809, 8888)) {
  if ($httpProxy -and $httpProxy -match ":$port$") { continue }
  $modes += @{ Name = "探测 127.0.0.1:$port"
               Args = @("-c", "http.proxy=http://127.0.0.1:$port",
                        "-c", "https.proxy=http://127.0.0.1:$port") }
}
$modes += @{ Name = "绕过代理直连"; Args = @("-c", "http.proxy=", "-c", "https.proxy=") }

Write-Host "`n探测远端……"
$good = $null
foreach ($m in $modes) {
  $gitArgs = @($m.Args) + @("ls-remote", "--heads", $url)
  $out = & git @gitArgs 2>&1
  if ($LASTEXITCODE -eq 0) {
    Write-Host ("  [ok] {0}" -f $m.Name) -ForegroundColor Green
    $good = $m
    break
  }
  $first = ($out | Where-Object { $_ -match '\S' } | Select-Object -First 1)
  Write-Host ("  [x]  {0}：{1}" -f $m.Name, $first) -ForegroundColor DarkGray
}
$ErrorActionPreference = "Stop"
$env:GIT_TERMINAL_PROMPT = "1"

if (-not $good) {
  Write-Host @"

连不上 github.com，两种模式都失败。按顺序排查：

  1) 你的代理/VPN 没开（最常见）
     - 现在配的是 http://127.0.0.1:7890，但该端口没有服务在监听
     - 启动 Clash / v2ray 等客户端，确认 7890 在监听，再重跑本脚本

  2) 代理端口变了：改成实际端口
       git config --global http.proxy  http://127.0.0.1:<端口>
       git config --global https.proxy http://127.0.0.1:<端口>

  3) 先确认通了再推（该命令应列出远端分支）
       git ls-remote --heads $url

说明：绕过代理时报 "Could not resolve host: github.com"（DNS 不通），
      即这台机器目前只能经代理访问 GitHub，不是仓库或账号的问题。
"@ -ForegroundColor Yellow
  exit 1
}
$proxyArgs = $good.Args
Write-Host ("  采用：{0}" -f $good.Name) -ForegroundColor Green
if ($good.Name -notmatch "^配置的代理" -and $good.Args.Count -gt 0) {
  $used = ($good.Args | Where-Object { $_ -match "^https\.proxy=" }) -replace "^https\.proxy=", ""
  Write-Host "  提示：可把可用代理写入配置，省去每次探测" -ForegroundColor DarkGray
  Write-Host "    git config --global http.proxy $used" -ForegroundColor DarkGray
  Write-Host "    git config --global https.proxy $used" -ForegroundColor DarkGray
}

# ---------- 3. remote ----------
$ErrorActionPreference = "Continue"
$originUrl = git remote get-url origin 2>$null
$hasOrigin = ($LASTEXITCODE -eq 0 -and $originUrl)
$ErrorActionPreference = "Stop"
if ($hasOrigin) {
  git remote set-url origin $url
  Write-Host "  已更新 origin"
} else {
  git remote add origin $url
  Write-Host "  已新增 origin"
}
Write-Host "  origin -> $url"

$status = git status --porcelain
if ($status) { Fail "工作区有未提交改动，先提交：`n$status" }

# ---------- 4. 推 ----------
$target = if ($Force -and $Branch -eq "sync-local") { "main" } else { $Branch }
if ($Force) {
  Write-Host "`n[注意] -Force：将覆盖远端 $target 的历史，不可逆。" -ForegroundColor Red
  $confirm = Read-Host "确认继续？输入 yes"
  if ($confirm -ne "yes") { Fail "已取消" }
  git @proxyArgs push --force -u origin "HEAD:$target"
} else {
  Write-Host "`n推送到分支 $target（非破坏性）……"
  git @proxyArgs push -u origin "HEAD:$target"
}

if ($LASTEXITCODE -ne 0) {
  Fail @"
推送失败。常见原因：
  - 未登录/凭据过期：在 GitHub Desktop 里用 hua-tech1 登录，或
    git config --global credential.helper manager  然后重试
  - 仓库不存在：先在 https://github.com/new 建 $Repo（不要勾 README）
"@
}

$ErrorActionPreference = "Continue"
& git @proxyArgs push origin --tags *> $null
Write-Host "  标签已同步（如无新标签会提示 Everything up-to-date）"
$ErrorActionPreference = "Stop"

Write-Host @"

========================================================
完成。打开对比页：

  https://github.com/$Owner/$Repo/compare/main...$target

确认无误后二选一：
  A) 在网页上 Merge（保留历史）
  B) 本地强制覆盖 main：
       powershell -File scripts\push_github.ps1 -Force
========================================================
"@ -ForegroundColor Cyan
