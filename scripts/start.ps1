$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show('请先运行 install.cmd 安装 Python 依赖，然后双击 start.cmd。','个人工作台') | Out-Null
    exit 1
}
Start-Process -FilePath $pythonw -ArgumentList @('-m','app.launcher') -WorkingDirectory $root -WindowStyle Hidden
