/* js/main.js —— 启动入口
 * 模块加载顺序见 index.html 底部 script 标签：
 *   state → tv → whale → chat → widgets → drag → main
 * 各模块通过 RD.Bus / RD.Store 协作，新增功能时照此模式挂接即可。
 */
(function () {
  'use strict';

  // 顶部菜单栏日期（Poolsuite 风格：FRI 16 OCT 2026）
  const DOW = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  function renderMenuDate() {
    const now = new Date();
    const el = document.getElementById('menuDate');
    if (el) {
      el.textContent = DOW[now.getDay()] + ' ' + now.getDate() + ' ' + MON[now.getMonth()] + ' ' + now.getFullYear();
    }
  }
  renderMenuDate();
  setInterval(renderMenuDate, 60 * 1000);   // 跨天自动更新

  // 页面隐藏时各 rAF 循环已通过 document.hidden 自行暂停，无需额外处理。
  console.log('[Retro Desk] ready —— 电视 %s，鲸鱼 %s',
    window.RD.Store.get('tv.power', true) ? '开机' : '关机',
    window.RD.Store.get('whale.paused', false) ? '已暂停' : '活动中');
})();
