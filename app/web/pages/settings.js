import {el,button,heading,modal} from '../core/dom.js';
import {moduleLoaders} from '../core/module-loaders.js';

function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

function countBadge(label, value, tone) {
  return el('div', {class: 'flex min-w-[74px] flex-1 flex-col gap-1 rounded-xl border border-[#E7E4D9] bg-[#FBFAF6] px-3 py-2.5'},
    el('span', {class: 'text-[9.5px] tracking-wide text-[#8A938D]'}, label),
    el('b', {class: 'text-[18px] font-semibold leading-none ' + (tone || 'text-[#2A382F]')}, String(value)));
}

async function mountBackupSection(container, context) {
  const section = el('section', {class: 'mt-5 rounded-2xl border border-[#E3E0D5] bg-white p-5 shadow-[0_4px_18px_rgba(36,76,64,0.04)]'});
  let fileInput = null;
  const head = el('div', {class: 'flex flex-wrap items-start justify-between gap-3'},
    el('div', {},
      el('h2', {class: 'text-[15px] font-semibold tracking-[-0.01em] text-[#2A382F]'}, '数据备份与恢复'),
      el('p', {class: 'mt-1 text-[11.5px] leading-5 text-[#7B857F]'},
        '备份任务、长期目标、笔记、偏好、项目与设置。不包含项目代码、运行日志和 AI 密钥。恢复前会自动保存一份当前数据。')),
    el('div', {class: 'flex items-center gap-2'},
      button('导出备份', () => exportBackup(), '', {class: 'wb-primary'}),
      restoreButton()));
  const overview = el('div', {class: 'mt-4'});
  const backups = el('div', {class: 'mt-4'});
  section.append(head, overview, backups);
  container.append(section);

  function restoreButton() {
    fileInput = el('input', {type: 'file', accept: '.json,application/json', class: 'hidden'});
    fileInput.addEventListener('change', () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = '';
      if (file) prepareRestore(file);
    });
    const btn = button('从备份恢复', () => fileInput.click(), '', {class: 'wb-quiet'});
    btn.append(fileInput);
    return btn;
  }

  async function exportBackup() {
    try {
      const response = await context.api.raw('/backup/export');
      if (!response.ok) throw new Error('导出失败：HTTP ' + response.status);
      const disposition = response.headers.get('content-disposition') || '';
      const match = /filename="([^"]+)"/.exec(disposition);
      const filename = match ? match[1] : 'personal-workbench-backup.json';
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = el('a', {href: url, download: filename});
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1500);
      context.notify('备份已导出：' + filename);
    } catch (error) {
      context.notify(error.message || '导出失败', true);
    }
  }

  function describeBundle(bundle) {
    const data = (bundle && bundle.data) || {};
    const tasks = (data.tasksState && data.tasksState.tasks) || {};
    const goals = (data.tasksState && data.tasksState.goals) || {};
    const notes = (data.home && data.home.notes && data.home.notes.items) || [];
    return { tasks: Object.keys(tasks).length, goals: Object.keys(goals).length, notes: notes.length };
  }

  function prepareRestore(file) {
    const reader = new FileReader();
    reader.onload = () => {
      let bundle = null;
      try {
        bundle = JSON.parse(String(reader.result || ''));
      } catch (error) {
        context.notify('备份文件不是合法的 JSON', true);
        return;
      }
      if (!bundle || bundle.format !== 'personal-workbench-backup') {
        context.notify('这不是个人工作台的备份文件', true);
        return;
      }
      const stats = describeBundle(bundle);
      const content = el('div', {class: 'text-[12px] leading-6 text-[#4A5A50]'},
        el('p', {}, '文件：', el('b', {class: 'text-[#2A382F]'}, file.name), '（' + formatSize(file.size) + '）'),
        el('p', {}, '导出时间：', bundle.exportedAt || '未知', ' · 版本：', String(bundle.appVersion || '未知')),
        el('p', {class: 'mt-1'}, '包含：待办 ', el('b', {}, String(stats.tasks)), ' 条 · 长期目标 ', el('b', {}, String(stats.goals)), ' 个 · 笔记 ', el('b', {}, String(stats.notes)), ' 条'),
        el('p', {class: 'mt-2 rounded-lg bg-[#FBEDE9] px-3 py-2 text-[11px] text-[#8F4A36]'},
          '恢复会用备份内容覆盖当前的任务、笔记、偏好与设置。当前数据会先自动备份到数据目录的 backups/ 下。'));
      const actions = [
        button('取消', () => handle.close(), '', {class: 'wb-quiet'}),
        button('确认恢复', () => doRestore(bundle, handle), '', {class: 'wb-primary', id: 'confirmRestoreBtn'}),
      ];
      const handle = modal('从备份恢复', content, actions, context.signal);
    };
    reader.onerror = () => context.notify('读取备份文件失败', true);
    reader.readAsText(file, 'utf-8');
  }

  async function doRestore(bundle, handle) {
    const confirmBtn = handle.dialog.querySelector('#confirmRestoreBtn');
    if (confirmBtn) confirmBtn.disabled = true;
    try {
      const response = await context.api.raw('/backup/restore', {
        method: 'POST',
        body: JSON.stringify(bundle),
        headers: {'Content-Type': 'application/json'},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message = (data && data.error && data.error.message) || ('恢复失败：HTTP ' + response.status);
        throw new Error(message);
      }
      handle.close();
      const summary = (data && data.summary) || {};
      context.notify('恢复完成：待办 ' + (summary.tasks ?? '?') + ' 条 · 目标 ' + (summary.goals ?? '?') + ' 个 · 笔记 ' + (summary.notes ?? '?') + ' 条');
      await refresh();
      setTimeout(() => location.reload(), 900);
    } catch (error) {
      if (confirmBtn) confirmBtn.disabled = false;
      context.notify(error.message || '恢复失败', true);
    }
  }

  async function refresh() {
    try {
      const info = await context.api.request('/backup/info');
      const summary = info.summary || {};
      overview.replaceChildren(
        el('div', {class: 'flex flex-wrap gap-2'},
          countBadge('待办', summary.tasks ?? 0),
          countBadge('长期目标', summary.goals ?? 0),
          countBadge('待办来源', summary.sources ?? 0),
          countBadge('随手记', summary.notes ?? 0),
          countBadge('项目', summary.projects ?? 0)),
        el('p', {class: 'mt-2.5 break-all font-mono text-[9.5px] text-[#9AA19C]'},
          '数据目录：' + (info.dataDir || '未知') + ' · 版本 ' + (info.appVersion || context.version || '未知')));
      const list = (info.backups || []);
      backups.replaceChildren(
        el('p', {class: 'text-[10px] tracking-wide text-[#8A938D]'}, '自动备份（恢复前生成，最多保留 10 份）'),
        list.length
          ? el('div', {class: 'mt-1.5 divide-y divide-[#F0EDE5] rounded-xl border border-[#E7E4D9]'},
            ...list.map(item => el('div', {class: 'flex items-center justify-between gap-3 px-3 py-1.5 text-[10.5px]'},
              el('span', {class: 'truncate font-mono text-[#5C6E64]'}, item.name),
              el('span', {class: 'shrink-0 text-[9.5px] text-[#9AA19C]'}, (item.createdAt || '').replace('T', ' ') + ' · ' + formatSize(item.size)))))
          : el('p', {class: 'mt-1.5 text-[10.5px] text-[#A0A7A1]'}, '还没有自动备份。第一次恢复时会自动生成。'));
    } catch (error) {
      overview.replaceChildren(el('p', {class: 'text-[11px] text-[#B4543B]'}, error.message || '读取备份信息失败'));
    }
  }

  await refresh();
  return () => fileInput?.remove();
}

export async function mount(container, context) {
  const cleanup = [];
  const wrapper = el('div', {class:'settings-page'});
  wrapper.append(heading('设置', '管理数据备份、本机目录和项目默认环境'));
  container.replaceChildren(wrapper);

  const stopBackup = await mountBackupSection(wrapper, context);
  if (stopBackup) cleanup.push(stopBackup);
  if (context.signal.aborted) return () => cleanup.forEach(fn => fn());

  for (const m of context.modules) {
    if (m.status === 'available' && m.settings_route && moduleLoaders[m.id]) {
      const module = await moduleLoaders[m.id]();
      if (context.signal.aborted) return () => cleanup.forEach(fn => fn());
      const section = el('section', {});
      wrapper.append(section);
      const stop = await module.mountSettings?.(section, context);
      if (stop) cleanup.push(stop);
    }
  }
  return () => cleanup.forEach(fn => fn());
}
