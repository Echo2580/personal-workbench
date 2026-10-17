$ErrorActionPreference = 'Stop'
# 开发版入口：强制使用独立数据目录，与日常使用版完全隔离
$env:WORKBENCH_DATA_DIR = Join-Path $env:LOCALAPPDATA 'PersonalWorkbench-dev'
& (Join-Path $PSScriptRoot 'start.ps1')
