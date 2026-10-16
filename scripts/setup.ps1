param([switch]$Development)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw '请安装 Python 3.12 或更高版本（包含 Python Launcher），然后重新运行。' }
    & py -3 -c "import sys; assert sys.version_info >= (3,12), '需要 Python 3.12+'"
    if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.12 或更高版本。' }
    & py -3 -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建工作台专用环境失败。' }
}
& $python -c "import sys; assert sys.version_info >= (3,12), '需要 Python 3.12+'"
if ($LASTEXITCODE -ne 0) { throw '现有 .venv 版本过低，请按 README 重建专用环境。' }
$lock = if ($Development) { 'requirements-dev.lock' } else { 'requirements.lock' }
& $python -m pip install --disable-pip-version-check -r (Join-Path $root $lock)
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请查看上方网络或 pip 错误。' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw '依赖一致性检查失败。' }
& $python -c "import win32job, fastapi, tomlkit; from pathlib import Path; assert Path('app/web/index.html').is_file()"
if ($LASTEXITCODE -ne 0) { throw '工作台资源或 Windows 依赖验证失败。' }
if ($Development) {
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw '测试浏览器安装失败。' }
}
Write-Host '安装完成。双击 start.cmd 打开个人工作台。' -ForegroundColor Green
