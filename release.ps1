param(
    [Parameter(Mandatory=$true)]
    [string]$Version,
    [switch]$Force,
    # 發布到測試庫（ocr-trigger-clicker-release-test）：直接公開，供 E2E 驗證
    [switch]$FeedTest
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($FeedTest) {
    $repoUrl = "https://github.com/Sid-1996/ocr-trigger-clicker-release-test"
} else {
    $repoUrl = "https://github.com/Sid-1996/ocr-trigger-clicker"
}
$ghRepo = $repoUrl -replace "^https://github\.com/", ""
$tagName = "v$Version"

# ---- pre-flight 檢查 ----

$status = git status --porcelain
if ($status) {
    Write-Error "工作目錄有未提交的變更，請先 commit 或 stash："
    $status | ForEach-Object { Write-Output "  $_" }
    exit 1
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "找不到 uv，請先安裝全域 uv 並確認在 PATH 中"
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

if (-not (Get-Command vpk -ErrorAction SilentlyContinue)) {
    Write-Error "找不到 vpk，請先安裝：dotnet tool install --global vpk"
    exit 1
}

if (-not $Force) {
    $existing = git tag -l $tagName
    if ($existing) {
        Write-Error "tag $tagName 已存在。若需重發，請加上 -Force 參數"
        exit 1
    }
}

# ---- 從 docs/dev/CHANGELOG.md 解析 release notes ----

Write-Output "從 docs/dev/CHANGELOG.md 解析 v$Version 發行說明..."

$changelogPath = Join-Path $root "docs/dev/CHANGELOG.md"
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
    Write-Error "docs/dev/CHANGELOG.md 中找不到 '## [v$Version]' 區塊。請先在 docs/dev/CHANGELOG.md 新增該版本內容。"
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
# 注意：latest_version.txt 凍結於 0.3.0、刻意不再更新——
# 讓仍使用自製更新器的舊客戶端永遠顯示「暫無更新」（斷糧，避免觸碰已拆除的更新路徑）
# -FeedTest 模式：版本檔僅暫改不提交，流程結束自動還原（不污染正式庫歷史）

if ($FeedTest) {
    $savedVersionPy = Get-Content _version.py -Raw -Encoding utf8
    $savedPyproject = Get-Content pyproject.toml -Raw -Encoding utf8
}

"__version__ = `"$Version`"" | Set-Content _version.py -Encoding utf8
"__author__ = `"Sid`"" | Add-Content _version.py -Encoding utf8
'__github__ = "https://github.com/Sid-1996/ocr-trigger-clicker"' | Add-Content _version.py -Encoding utf8

$pyprojectPath = Join-Path $root "pyproject.toml"
$pyprojectText = Get-Content -Path $pyprojectPath -Raw -Encoding utf8
# 注意：不用 `$` 端點——工作區是 CRLF，.NET 正則 `(?m)$` 對不上 `\r` 前的位置會靜默失敗
$pyprojectText = [regex]::Replace($pyprojectText, '(?m)^version = "[^"]*"', "version = `"$Version`"")
Set-Content -Path $pyprojectPath -Value $pyprojectText -Encoding utf8
# 防呆：確認版本真的寫進去了，否則硬失敗（避免再次靜默跳過）
if ((Get-Content -Path $pyprojectPath -Raw -Encoding utf8) -notmatch ('version = "' + [regex]::Escape($Version) + '"')) {
    throw "pyproject.toml 版本同步失敗：找不到 version = `"$Version`""
}

# ---- 取回前版資產（供 Velopack 計算 delta；首次發布無前版時允許失敗） ----

Remove-Item -Path Releases -Recurse -Force -ErrorAction SilentlyContinue
vpk download github --repoUrl $repoUrl
if ($LASTEXITCODE -ne 0) {
    Write-Warning "無法取得前版資產（首次發布屬正常），本版將只有完整包、無 delta"
}

# ---- 打包（PyInstaller + vpk pack） ----

Remove-Item -Path dist -Recurse -Force -ErrorAction SilentlyContinue
if ($FeedTest) {
    uv run python build.py --feed test
} else {
    uv run python build.py
}
if ($LASTEXITCODE -ne 0) { throw "build.py 失敗" }

# ---- commit 版號與 CHANGELOG（本地，還不 push；測試模式跳過） ----

if (-not $FeedTest) {
    git add _version.py pyproject.toml docs/dev/CHANGELOG.md
    git commit -m "chore: bump to v$Version"
}

# ---- 清理既有 tag / release（-Force 模式，僅正式庫） ----

if ($Force -and -not $FeedTest) {
    Write-Output "清理既有 tag 與 release: $tagName"
    git push origin --delete $tagName 2>$null
    gh release delete $tagName -R $ghRepo --yes 2>$null
}

# ---- push commit + tag（測試模式跳過） ----

if (-not $FeedTest) {
    git tag $tagName
    git push origin master
    if ($LASTEXITCODE -ne 0) { git tag -d $tagName; throw "Failed to push master" }
    git push origin $tagName
    if ($LASTEXITCODE -ne 0) { git tag -d $tagName; throw "Failed to push tag" }
}

# ---- 上傳 Velopack 資產到 GitHub Releases ----

$token = (gh auth token).Trim()
$uploadArgs = @(
    "upload", "github",
    "--repoUrl", $repoUrl,
    "--token", $token,
    "--tag", $tagName,
    "--releaseName", $tagName
)
if ($FeedTest) {
    # 測試庫直接公開——沙箱裡沒有使用者，E2E 才測得到真實下載路徑；
    # --merge 允許同版號反覆覆蓋上傳（沙箱迭代用）
    $uploadArgs += "--publish", "--merge"
} else {
    # 正式庫維持 draft：人工冒煙測試後再到 GitHub 頁面 Publish
}
& vpk @uploadArgs
if ($LASTEXITCODE -ne 0) { throw "vpk upload github 失敗" }

# ---- 補發行說明（vpk 不寫 body；draft 狀態也可編輯） ----

$notesFile = Join-Path $env:TEMP "ocr_release_notes_$Version.md"
$releaseNote | Set-Content -Path $notesFile -Encoding utf8
gh release edit $tagName -R $ghRepo --title $tagName --notes-file $notesFile
if ($LASTEXITCODE -ne 0) { throw "gh release edit 失敗" }
Remove-Item $notesFile -ErrorAction SilentlyContinue

# ---- 測試模式收尾：還原版本檔，保持工作樹乾淨 ----

if ($FeedTest) {
    Set-Content _version.py -Value $savedVersionPy -Encoding utf8 -NoNewline
    Set-Content pyproject.toml -Value $savedPyproject -Encoding utf8 -NoNewline
    git checkout -- pyproject.toml 2>$null
}

if ($FeedTest) {
    Write-Output ""
    Write-Output "✅ 測試庫已公開發布 $tagName"
    Write-Output "   https://github.com/$ghRepo/releases/tag/$tagName"
    Write-Output "   可用 feed=test 的安裝包執行 E2E 更新驗證。"
} else {
    Write-Output ""
    Write-Output "Draft release $tagName 建立完成（含 Setup.exe／nupkg／releases.win.json）:"
    Write-Output "   https://github.com/$ghRepo/releases/tag/$tagName"
    Write-Output ""
    Write-Output "請下載 Releases\$tagName 目錄下的 Setup.exe 安裝冒煙測試，"
    Write-Output "確認無誤後在 GitHub Releases 頁面按「Publish release」公開。"
}
