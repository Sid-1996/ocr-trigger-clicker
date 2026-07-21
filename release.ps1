param(
    [Parameter(Mandatory=$true)]
    [string]$Version,
    [string]$Notes = "",
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

# 1. 更新版本號
"__version__ = `"$Version`"" | Set-Content _version.py -Encoding utf8
"__author__ = `"Sid`"" | Add-Content _version.py -Encoding utf8
'__github__ = "https://github.com/Sid-1996/ocr-trigger-clicker"' | Add-Content _version.py -Encoding utf8
$Version | Set-Content latest_version.txt -Encoding utf8

# 2. commit（本地，還不 push）
git add _version.py latest_version.txt
git commit -m "chore: bump to v$Version"

# 3. 打包
Remove-Item -Path dist -Recurse -Force -ErrorAction SilentlyContinue
python build.py
Compress-Archive -Path dist\ocr-trigger-clicker.exe, dist\updater.exe -DestinationPath dist\ocr-trigger-clicker.zip -CompressionLevel Optimal -Force

# 4. 清理既有 tag / release（-Force 模式）
if ($Force) {
    $tagName = "v$Version"
    Write-Output "清理既有 tag 與 release: $tagName"
    git push origin --delete $tagName 2>$null
    gh release delete $tagName --yes 2>$null
}

# 5. push commit + tag
git tag v$Version
git push origin master
git push origin v$Version

# 6. draft release
$title = "v$Version"
$releaseNote = if ($Notes) { $Notes } else { "Release v$Version" }
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
Write-Output "請在 GitHub Releases 頁面手動按「Publish release」公開。"
