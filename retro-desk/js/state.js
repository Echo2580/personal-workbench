/* js/state.js —— 共享事件总线 + localStorage 持久化
 * 所有组件联动都走 RD.Bus，所有持久化都走 RD.Store。
 * 新增联动时：发布方 Bus.emit('事件名', 数据)，订阅方 Bus.on('事件名', fn)。
 */
window.RD = window.RD || {};
(function () {
  'use strict';

  const Bus = {
    map: {},
    on(ev, fn) { (this.map[ev] = this.map[ev] || []).push(fn); },
    emit(ev, data) {
      (this.map[ev] || []).slice().forEach(fn => {
        try { fn(data); } catch (e) { console.error('[Bus]', ev, e); }
      });
    }
  };

  const LS_KEY = 'retroDesk.v1';
  let cache = null;

  function loadAll() {
    if (cache) return cache;
    try { cache = JSON.parse(localStorage.getItem(LS_KEY)) || {}; }
    catch (e) { cache = {}; }
    return cache;
  }
  function saveAll() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(cache)); } catch (e) { /* 隐私模式等场景下静默失败 */ }
  }

  const Store = {
    get(key, dft) {
      const o = loadAll();
      return Object.prototype.hasOwnProperty.call(o, key) ? o[key] : dft;
    },
    set(key, val) { loadAll()[key] = val; saveAll(); },
    remove(key) { const o = loadAll(); delete o[key]; saveAll(); },
    removePrefix(prefix) {
      const o = loadAll();
      Object.keys(o).forEach(k => { if (k.indexOf(prefix) === 0) delete o[k]; });
      saveAll();
    }
  };

  RD.Bus = Bus;
  RD.Store = Store;

  // 皮肤升级迁移：v2（Poolsuite 风格）默认布局与 v1 不同，作废旧布局坐标，
  // 待办 / 便笺 / 频道等数据保留。
  if (Store.get('skinVer', 0) < 2) {
    Store.removePrefix('pos.');
    Store.set('skinVer', 2);
  }
  RD.reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
})();
