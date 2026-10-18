$ErrorActionPreference = 'Stop'
# 开发版入口：数据根目录跟着项目走（<项目根>\data），与日常稳定版（wb-stable\data）隔离；
# 需要更彻底隔离时可临时设置 WORKBENCH_DATA_DIR 指向其它目录。
& (Join-Path $PSScriptRoot 'start.ps1')
