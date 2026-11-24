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
$noProxyArgs = @()
if ($httpProxy -or $httpsProxy) {
  Write-Host "  检测到代理，本次推送将绕过它（-c http.proxy= -c https.proxy=）" -ForegroundColor Yellow
  $noProxyArgs = @("-c", "http.proxy=", "-c", "https.proxy=")
}

# ---------- 2. 远端可达性 ----------
$env:GIT_TERMINAL_PROMPT = "0"
Write-Host "`n探测远端……"
git @noProxyArgs ls-remote --heads "https://github.com/$Owner/$Repo.git" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  $env:GIT_TERMINAL_PROMPT = "1"
  Write-Host @"

连不上 github.com。按顺序排查：
  1) 代理已失效：git config --global --unset http.proxy ; git config --global --unset https.proxy
  2) 需要代理才能上 GitHub：把代理改成一个**正在运行**的端口，例如
       git config --global http.proxy http://127.0.0.1:<你的端口>
  3) 本机 PowerShell 能直连 api.github.com（已验证），所以 1) 通常就能解决
"@ -ForegroundColor Yellow
  exit 1
}
$env:GIT_TERMINAL_PROMPT = "1"
Write-Host "  远端可达" -ForegroundColor Green

# ---------- 3. remote ----------
$url = "https://github.com/$Owner/$Repo.git"
git remote get-url origin 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
  git remote set-url origin $url
} else {
  git remote add origin $url
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
  git @noProxyArgs push --force -u origin "HEAD:$target"
} else {
  Write-Host "`n推送到分支 $target（非破坏性）……"
  git @noProxyArgs push -u origin "HEAD:$target"
}

if ($LASTEXITCODE -ne 0) {
  Fail @"
推送失败。常见原因：
  - 未登录/凭据过期：在 GitHub Desktop 里用 hua-tech1 登录，或
    git config --global credential.helper manager  然后重试
  - 仓库不存在：先在 https://github.com/new 建 $Repo（不要勾 README）
"@
}

git @noProxyArgs push origin --tags 2>$null | Out-Null

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
