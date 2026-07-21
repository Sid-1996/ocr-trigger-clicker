param(
    [Parameter(Mandatory=$true)]
    [string]$Version,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# ---- pre-flight 檢查 ----

$status = git status --porcelain
if ($status) {
    Write-Error "工作目錄有未提交的變更，請先 commit 或 stash："
    $status | ForEach-Object { Write-Output "  $_" }
    exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "找不到 python，請確認在 PATH 中"
    exit 1
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "找不到 gh (GitHub CLI)，請安裝：winget install GitHub.cli"
    exit 1
}

gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "gh 未登入，請先執行 gh auth login"
    exit 1
}

if (-not $Force) {
    $existing = git tag -l "v$Version"
    if ($existing) {
        Write-Error "tag v$Version 已存在。若需重發，請加上 -Force 參數"
        exit 1
    }
}

# ---- 從 CHANGELOG.md 解析 release notes ----

Write-Output "從 CHANGELOG.md 解析 v$Version 發行說明..."

$changelogPath = Join-Path $root "CHANGELOG.md"
$lines = Get-Content -Path $changelogPath -Encoding utf8
$escaped = [regex]::Escape("## [v$Version]")
$versionLine = -1
$nextSectionLine = -1

for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^$escaped") {
        $versionLine = $i
    } elseif ($versionLine -ge 0 -and $lines[$i] -match "^## \[") {
        $nextSectionLine = $i
        break
    }
}

if ($versionLine -eq -1) {
    Write-Error "CHANGELOG.md 中找不到 '## [v$Version]' 區塊。請先在 CHANGELOG.md 新增該版本內容。"
    exit 1
}

# 自動補日期
$headerLine = $lines[$versionLine]
if ($headerLine -notmatch "- \d{4}-\d{2}-\d{2}") {
    $date = Get-Date -Format "yyyy-MM-dd"
    $lines[$versionLine] = "## [v$Version] - $date"
    Write-Output "自動填入日期: $date"
    Set-Content -Path $changelogPath -Value $lines -Encoding utf8
}

# 提取 release notes（不含標題行，去除前後空行）
if ($nextSectionLine -ge 0) {
    $endIndex = $nextSectionLine - 1
    if ($endIndex -ge ($versionLine + 1)) {
        $noteLines = $lines[($versionLine + 1)..$endIndex]
    } else {
        $noteLines = @()
    }
} else {
    $noteLines = $lines[($versionLine + 1)..($lines.Count - 1)]
}

# 去除前後空行
$start = 0
while ($start -lt $noteLines.Count -and [string]::IsNullOrWhiteSpace($noteLines[$start])) {
    $start++
}
$end = $noteLines.Count - 1
while ($end -ge 0 -and [string]::IsNullOrWhiteSpace($noteLines[$end])) {
    $end--
}
if ($start -le $end) {
    $noteLines = $noteLines[$start..$end]
} else {
    $noteLines = @()
}

if ($noteLines.Count -eq 0) {
    Write-Error "CHANGELOG v$Version 區塊內容為空"
    exit 1
}

$releaseNote = $noteLines -join "`n"
Write-Output "成功讀取發行說明 ($($noteLines.Count) 行)"

# ---- 更新版本號 ----

"__version__ = `"$Version`"" | Set-Content _version.py -Encoding utf8
"__author__ = `"Sid`"" | Add-Content _version.py -Encoding utf8
'__github__ = "https://github.com/Sid-1996/ocr-trigger-clicker"' | Add-Content _version.py -Encoding utf8
$Version | Set-Content latest_version.txt -Encoding utf8

# ---- commit（本地，還不 push） ----

git add _version.py latest_version.txt CHANGELOG.md
git commit -m "chore: bump to v$Version"

# ---- 打包 ----

Remove-Item -Path dist -Recurse -Force -ErrorAction SilentlyContinue
python build.py
Compress-Archive -Path dist\ocr-trigger-clicker.exe, dist\updater.exe -DestinationPath dist\ocr-trigger-clicker.zip -CompressionLevel Optimal -Force

# ---- 清理既有 tag / release（-Force 模式） ----

if ($Force) {
    $tagName = "v$Version"
    Write-Output "清理既有 tag 與 release: $tagName"
    git push origin --delete $tagName 2>$null
    gh release delete $tagName --yes 2>$null
}

# ---- push commit + tag ----

git tag v$Version
git push origin master
git push origin v$Version

# ---- draft release ----

$title = "v$Version"
$ghArgs = @(
    "release", "create", "v$Version",
    "dist/ocr-trigger-clicker.zip",
    "--title", $title,
    "--draft", "--prerelease",
    "--notes", $releaseNote
)
gh @ghArgs

Write-Output "Draft release v$Version 建立完成: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v$Version"
Write-Output ""
Write-Output "請先下載 dist/ocr-trigger-clicker.exe 測試，確認無誤後在 GitHub Releases 頁面按「Publish release」公開。"
