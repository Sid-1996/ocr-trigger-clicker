param(
    [Parameter(Mandatory=$true)]
    [string]$Version,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$root = "C:\Code play first\ocr-trigger-clicker"
Set-Location $root

# 1. 更新版本號
"__version__ = `"$Version`"" | Set-Content _version.py
"__author__ = `"Sid`"" | Add-Content _version.py
'__github__ = "https://github.com/Sid-1996/ocr-trigger-clicker"' | Add-Content _version.py
$Version | Set-Content latest_version.txt

# 2. commit 版本異動
git add _version.py latest_version.txt
git commit -m "chore: bump to v$Version"
git push origin master

# 3. 打包
python build.py
Compress-Archive -Path dist\ocr-trigger-clicker.exe -DestinationPath dist\ocr-trigger-clicker.zip -CompressionLevel Optimal -Force

# 4. tag + release
git tag v$Version
git push origin v$Version

$title = "v$Version"
if ($Version -match '^\d+\.\d+\.\d+[a-z]') { $title += " Beta" }
$args = @("release", "create", "v$Version", "dist/ocr-trigger-clicker.zip", "--title", $title, "--prerelease")
if ($Notes) { $args += "--notes"; $args += $Notes }
gh @args

Write-Output "Release v$Version 完成: https://github.com/Sid-1996/ocr-trigger-clicker/releases/tag/v$Version"
