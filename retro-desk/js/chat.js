/* js/chat.js —— 复古聊天窗口
 * 本轮为本地演示回复，不需要任何 API 密钥。
 * ★ 接入位置：把 RD.chatAdapter 替换为「调用你的后端 → 后端转发 DeepSeek」
 *   的 fetch 即可，密钥只放在后端，绝不写进前端。
 */
(function () {
  'use strict';
  const RD = window.RD;

  const win = document.getElementById('chatWin');
  const log = document.getElementById('chatLog');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');

  /* —— 聊天适配函数（演示实现）——
   * 正式版示例：
   *   RD.chatAdapter = async text =>
   *     (await fetch('/api/chat', { method:'POST', body: JSON.stringify({text}) }))
   *       .then(r => r.json()).then(d => d.reply);
   */
  RD.chatAdapter = async function (userText) {
    await new Promise(r => setTimeout(r, 600 + Math.random() * 700));
    const t = (userText || '').trim().toLowerCase();
    const rules = [
      { k: ['你好', 'hi', 'hello', '在吗', '在不在'], r: '你好呀，我是小鲸🐳（本地演示版）。等我接上 DeepSeek，就能认真聊天了。' },
      { k: ['待办', '任务', 'todo'], r: '右上角是今日待办，输入框里加任务，勾掉一条我会替你庆祝一下。' },
      { k: ['电视', '频道', '视频'], r: '中间那台电视有三个频道：像素日落、雨夜、星空。旋钮和 ◀ ▶ 都能换台，还能放本地视频。' },
      { k: ['天气'], r: '日历上的天气是标注过的演示数据，之后可以接真实天气接口。' },
      { k: ['项目', '文件夹'], r: '右下角的项目文件夹双击就能打开，入口在 js/widgets.js 的 PROJECTS 里统一配置。' },
      { k: ['你是谁', '名字'], r: '我是小鲸，这台桌面的常驻宠物，未来 DeepSeek 助手的形象担当（演示版）。' }
    ];
    for (const rule of rules) {
      if (rule.k.some(k => t.indexOf(k) !== -1)) return '[演示] ' + rule.r;
    }
    const pool = [
      '嗯嗯，我在听（演示回复）。',
      '这个想法不错，要不要先记到左上角便笺里？',
      '我现在只会说演示台词，接入 DeepSeek 之后就聪明了。',
      '咕嘟咕嘟……这是鲸鱼式的思考。'
    ];
    return '[演示] ' + pool[(Math.random() * pool.length) | 0];
  };

  function addMsg(text, who) {
    const div = document.createElement('div');
    div.className = 'msg ' + who;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  // 点击鲸鱼 → 打开聊天窗口并置顶
  RD.Bus.on('whale:click', () => {
    win.classList.remove('hidden');
    win.classList.remove('collapsed');
    RD.Bus.emit('win:focus', win);
    if (!log.children.length) addMsg('嗨，我是小鲸。有什么想聊的？', 'bot');
    input.focus();
  });

  document.getElementById('chatClose').addEventListener('click', () => {
    win.classList.add('hidden');
  });

  let busy = false;   // 防止连续发送导致思考状态排队
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true;
    addMsg(text, 'me');
    input.value = '';
    RD.Bus.emit('chat:sent');
    try {
      const reply = await RD.chatAdapter(text);
      addMsg(reply, 'bot');
    } catch (err) {
      addMsg('（演示）好像呛水了，待会儿再试试。', 'bot');
    } finally {
      busy = false;
      RD.Bus.emit('chat:replied');
    }
  });
})();
