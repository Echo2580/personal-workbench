/**
 * 开发/构建启动包装。
 *
 * 背景：本机安全软件会拦截位于中文路径下的 esbuild.exe 读取文件
 * （症状：winapi error #5，ACCESS_DENIED，--version 正常但读任何文件都失败；
 * 同一二进制复制到英文路径后恢复正常）。
 * 方案：启动时把 esbuild.exe 复制为英文路径下的改名副本，通过官方环境变量
 * ESBUILD_BINARY_PATH 让 vite/esbuild 全链路改走副本。
 * 副本不存在才复制，npm 重装依赖后也能自愈。
 */
import { spawn } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(root, 'node_modules', '@esbuild', 'win32-x64', 'esbuild.exe')

// 副本必须落在英文路径（安全软件按路径语言拦截，见文件头注释）
const localAppData = process.env.LOCALAPPDATA || join(root, '.local')
const binDir = join(localAppData, 'PersonalWorkbench', 'esbuild')
const dst = join(binDir, 'esbuild-win.exe')

if (!existsSync(dst)) {
  mkdirSync(binDir, { recursive: true })
  copyFileSync(src, dst)
}
process.env.ESBUILD_BINARY_PATH = dst

const [cmd, ...args] = process.argv.slice(2)
const child = spawn(cmd, args, { stdio: 'inherit', cwd: root, shell: process.platform === 'win32' })
child.on('exit', (code) => process.exit(code ?? 1))
