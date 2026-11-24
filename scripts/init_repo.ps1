# 一键初始化开源仓库（本地 commit + tag，不 push）
#
# 用法（在仓库根目录，任选其一）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\init_repo.ps1
#   pwsh -File scripts/init_repo.ps1
#
# 它会做五件事：
#   1. 检查 git 与 .gitignore 排除项（影像 / 密钥 / 权重 不得入库）
#   2. 初始化仓库并暂存全部文件
#   3. 核对暂存清单：列出体积最大的 10 个文件，任何禁入项命中即中止
#   4. 跑一遍 efo 单元测试
#   5. 提交并打 tag，最后打印 push 命令（推送交给你手动执行）

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Fail($msg) { Write-Host "`n[中止] $msg" -ForegroundColor Red; exit 1 }
function Ok($msg)   { Write-Host "  ok  $msg" -ForegroundColor Green }

# ---------- 1. 环境 ----------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Fail "未找到 git。先安装 Git for Windows：https://git-scm.com/download/win"
}
Ok "git: $(git --version)"

if (-not (Test-Path ".gitignore")) { Fail "缺少 .gitignore" }
$ign = Get-Content ".gitignore" -Raw
foreach ($need in @("data/demo/frames/", "data/seed/", ".env", "deploy/.env.cloud")) {
  if ($ign -notmatch [regex]::Escape($need)) { Fail ".gitignore 缺少排除项：$need" }
}
Ok ".gitignore 已排除影像、仿真数据、本地密钥"

# ---------- 2. init + add ----------
if (-not (Test-Path ".git")) {
  git init -b main | Out-Null
  Ok "已初始化仓库（branch: main）"
} else {
  Ok "仓库已存在，沿用"
}

git add -A
$staged = @(git -c core.quotepath=false diff --cached --name-only)
if ($staged.Count -eq 0) { Fail "没有可提交的文件（或全部被忽略）" }
Write-Host "`n暂存文件数：$($staged.Count)"

# ---------- 3. 禁入项核对 ----------
$bad = $staged | Where-Object {
  $_ -match '^data/demo/frames/' -or
  $_ -match '^data/seed/' -or
  $_ -match '\.env$' -or
  $_ -match 'deploy/\.env\.cloud$' -or
  $_ -match '\.(pt|onnx|engine|pth)$' -or
  $_ -match 'evidence\.json$'
}
if ($bad) {
  Write-Host "`n以下文件不应入库：" -ForegroundColor Yellow
  $bad | ForEach-Object { Write-Host "    $_" }
  Fail "请先把上述文件加入 .gitignore 并 git rm --cached"
}
Ok "无影像 / 无权重 / 无密钥入库"

Write-Host "`n体积最大的 10 个暂存文件："
$sizes = foreach ($p in $staged) {
  $full = Join-Path $root $p
  try {
    if (Test-Path -LiteralPath $full) {
      [pscustomobject]@{ File = $p; KB = [math]::Round((Get-Item -LiteralPath $full).Length / 1KB, 1) }
    }
  } catch { }
}
$sizes | Sort-Object KB -Descending | Select-Object -First 10 | Format-Table -AutoSize | Out-String -Width 110 | Write-Host

$totalMB = (($sizes | Measure-Object KB -Sum).Sum) / 1024
Write-Host ("暂存总体积：{0:N2} MB" -f $totalMB)
if ($totalMB -gt 30) { Write-Host "  注意：超过 30MB，建议检查是否混入数据文件" -ForegroundColor Yellow }

# ---------- 4. 测试 ----------
Write-Host "`n运行 efo 单元测试……"
$py = @("py", "python", "python3") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
if ($py) {
  & $py "packages/efo/tests/run.py"
  if ($LASTEXITCODE -ne 0) { Fail "单元测试未通过，先修再提交" }
  Ok "单元测试通过"
} else {
  Write-Host "  跳过：未找到 python" -ForegroundColor Yellow
}

# ---------- 5. commit + tag ----------
$name = git config user.name
$mail = git config user.email
if (-not $name -or -not $mail) {
  Write-Host "`n[需要你补一步] git 身份未配置：" -ForegroundColor Yellow
  Write-Host '    git config --global user.name  "你的名字"'
  Write-Host '    git config --global user.email "你的邮箱"'
  Write-Host "`n配好后重新运行本脚本即可提交。文件已暂存，不会丢。" -ForegroundColor Cyan
  exit 0
}

$msg = @"
feat: 卒中绿色通道质控台 v1.0

系统：FastAPI + PostgreSQL 16 + Redis 7，17 表 / 14 节点 / 22 指标 / 600 例仿真队列。
EFO：事件级保真三命题（盲区 / 放大 / 偏置）+ 三解法，零依赖开源包。
验证：1527 帧真实标注事件级评估（F1 0.9333）；INT8 权重量化对照；昇腾容量模型。

边界：未对接真实 DSA；队列为仿真数据；验证集仅含「导丝在场」帧。
"@
git commit -m $msg | Out-Null
Ok "已提交：$(git rev-parse --short HEAD)"

if (-not (git tag -l "v1.0.0")) {
  git tag -a v1.0.0 -m "v1.0.0 · 本地原型 + EFO 事件级验证"
  Ok "已打 tag v1.0.0"
}

# ---------- 下一步 ----------
Write-Host @"

========================================================
本地已完成。推送命令（先建空仓库，不要勾 README）：

  git remote add origin https://github.com/<你的用户名>/stroke-qc.git
  git push -u origin main
  git push origin v1.0.0

Gitee 同理：
  git remote add gitee https://gitee.com/<你的用户名>/stroke-qc.git
  git push gitee main --tags

仓库设置建议（About 栏直接抄）：
  描述：卒中绿色通道 · 介入器械识别与流程时效质控台（EFO 事件级保真）
  Topics：stroke, yolo, event-detection, quality-control, fastapi, ascend, efo
========================================================
"@ -ForegroundColor Cyan
