/* js/tv.js —— 复古电视
 * 功能：电源开关（亮起/熄灭）、三个 Canvas 动态频道、换台雪花、
 *       暂停/继续、本地视频播放（ObjectURL，仅浏览器本地）、音量/静音。
 * 联动：todo:completed → 屏幕短暂提示（不打断视频）。
 */
(function () {
  'use strict';
  const RD = window.RD;

  const canvas = document.getElementById('tvCanvas');
  const ctx = canvas.getContext('2d');
  const W = canvas.width;   // 192
  const H = canvas.height;  // 120
  const video = document.getElementById('tvVideo');
  const offMask = document.getElementById('tvOffMask');
  const flash = document.getElementById('tvFlash');
  const toastEl = document.getElementById('tvToast');
  const bigPlay = document.getElementById('tvBigPlay');
  const chDisplay = document.getElementById('chDisplay');
  const btnPower = document.getElementById('tvPower');
  const btnPrev = document.getElementById('chPrev');
  const btnNext = document.getElementById('chNext');
  const btnPause = document.getElementById('tvPause');
  const btnMute = document.getElementById('tvMute');
  const btnBack = document.getElementById('tvBack');
  const fileInput = document.getElementById('tvFile');
  const volSlider = document.getElementById('tvVolume');
  const chKnob = document.getElementById('chKnob');
  const volKnob = document.getElementById('volKnob');

  let powerOn = false;
  let channel = RD.Store.get('tv.channel', 0);
  let paused = false;
  let videoMode = false;
  let muted = RD.Store.get('tv.muted', true);   // 视频默认静音
  let volume = RD.Store.get('tv.volume', 60);
  let noiseUntil = 0;
  let tick = 0;
  let toastTimer = null;

  /* ---------------- 频道素材状态 ---------------- */
  const stars = [];
  for (let i = 0; i < 70; i++) {
    stars.push({ x: Math.random() * W, y: Math.random() * H * 0.72, s: Math.random() * 6.28, r: Math.random() < 0.15 ? 2 : 1 });
  }
  let shooting = null;

  const drops = [];
  for (let i = 0; i < 90; i++) {
    drops.push({ x: Math.random() * W, y: Math.random() * H, v: 2 + Math.random() * 2 });
  }
  let lightning = 0;

  /* ---------------- 频道绘制 ---------------- */
  function drawNoise() {
    const img = ctx.createImageData(W, H);
    const d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      const v = (Math.random() * 255) | 0;
      d[i] = d[i + 1] = d[i + 2] = v;
      d[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }

  // CH1 像素日落海面
  function drawSunset() {
    const bands = ['#2b2a55', '#4b3a6e', '#7d4a72', '#b5566a', '#e07157', '#f59a4e'];
    bands.forEach((c, i) => { ctx.fillStyle = c; ctx.fillRect(0, i * 8, W, 8); });
    // 太阳（方块拼成的圆）
    const sy = 34 + Math.sin(tick / 90) * 2;
    ctx.fillStyle = '#ffd27a';
    for (let y = -8; y <= 8; y += 2) {
      const w = Math.sqrt(Math.max(0, 64 - y * y));
      ctx.fillRect(W / 2 - w, sy + y, w * 2, 2);
    }
    // 海面
    ctx.fillStyle = '#27364f';
    ctx.fillRect(0, 52, W, H - 52);
    for (let y = 54; y < H; y += 4) {
      const off = Math.sin(tick / 14 + y * 0.32) * (2 + (y - 52) / 10);
      const grad = (y - 52) / (H - 52);
      ctx.fillStyle = grad < 0.4 ? '#f0a35e' : (grad < 0.7 ? '#5d7290' : '#3b4f6b');
      const segW = 8 + grad * 22;
      for (let x = -segW; x < W; x += segW * 2) ctx.fillRect(x + off * 3, y, segW, 2);
    }
    // 太阳光路
    ctx.fillStyle = 'rgba(255,210,122,0.55)';
    for (let y = 56; y < H; y += 6) {
      const w = 6 + (y - 56) * 0.45;
      ctx.fillRect(W / 2 - w / 2 + Math.sin(tick / 10 + y) * 3, y, w, 2);
    }
  }

  // CH2 雨夜
  function drawRain() {
    ctx.fillStyle = '#101820';
    ctx.fillRect(0, 0, W, H);
    // 城市剪影
    ctx.fillStyle = '#1b2634';
    for (let i = 0; i < 10; i++) {
      const bw = 14 + (i * 37) % 12;
      const bh = 22 + (i * 53) % 26;
      ctx.fillRect(i * 20, H - 26 - bh, bw, bh);
    }
    // 窗灯（少量闪烁）
    ctx.fillStyle = '#c9a54a';
    for (let i = 0; i < 16; i++) {
      const wx = (i * 47) % W;
      const wy = H - 24 - ((i * 31) % 40);
      if ((i + (tick >> 6)) % 5 !== 0) ctx.fillRect(wx, wy, 2, 3);
    }
    // 地面与反光
    ctx.fillStyle = '#1e2c3d';
    ctx.fillRect(0, H - 24, W, 24);
    ctx.fillStyle = 'rgba(201,165,74,0.25)';
    for (let i = 0; i < 8; i++) ctx.fillRect((i * 61) % W, H - 20 + (i % 3) * 5, 6, 2);
    // 偶发闪电
    if (lightning > 0) {
      lightning--;
      ctx.fillStyle = 'rgba(210,225,255,' + (lightning / 12) + ')';
      ctx.fillRect(0, 0, W, H);
    } else if (Math.random() < 0.006) {
      lightning = 12;
    }
    // 雨丝
    ctx.strokeStyle = 'rgba(150,180,220,0.7)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    drops.forEach(d => {
      ctx.moveTo(d.x, d.y);
      ctx.lineTo(d.x - 1, d.y + 6);
      d.y += d.v;
      d.x -= 0.2;
      if (d.y > H) { d.y = -6; d.x = Math.random() * (W + 10); }
    });
    ctx.stroke();
  }

  // CH3 星空
  function drawStars() {
    ctx.fillStyle = '#070b1a';
    ctx.fillRect(0, 0, W, H);
    // 山影
    ctx.fillStyle = '#0d1426';
    ctx.beginPath();
    ctx.moveTo(0, H);
    for (let x = 0; x <= W; x += 16) ctx.lineTo(x, H - 20 - Math.abs(Math.sin(x * 0.7)) * 18);
    ctx.lineTo(W, H);
    ctx.closePath();
    ctx.fill();
    // 星星眨眼
    stars.forEach(s => {
      const a = 0.35 + 0.65 * Math.abs(Math.sin(tick / 30 + s.s));
      ctx.fillStyle = 'rgba(230,238,255,' + a + ')';
      ctx.fillRect(s.x, s.y, s.r, s.r);
    });
    // 偶发流星
    if (!shooting && Math.random() < 0.008) {
      shooting = { x: Math.random() * W * 0.6 + W * 0.2, y: 8 + Math.random() * 20, life: 22 };
    }
    if (shooting) {
      shooting.x += 4;
      shooting.y += 1.6;
      shooting.life--;
      ctx.strokeStyle = 'rgba(255,255,255,0.9)';
      ctx.beginPath();
      ctx.moveTo(shooting.x, shooting.y);
      ctx.lineTo(shooting.x - 10, shooting.y - 4);
      ctx.stroke();
      if (shooting.life <= 0 || shooting.x > W) shooting = null;
    }
  }

  const drawers = [drawSunset, drawRain, drawStars];

  function loop() {
    requestAnimationFrame(loop);
    if (!powerOn || paused || videoMode || document.hidden) return;
    tick++;
    if (performance.now() < noiseUntil) drawNoise();
    else drawers[channel]();
  }

  /* ---------------- 控制逻辑 ---------------- */
  function updateChDisplay() {
    chDisplay.textContent = !powerOn ? '--' : (videoMode ? 'AV' : 'CH ' + (channel + 1));
  }

  function setChannel(i, withNoise) {
    channel = ((i % 3) + 3) % 3;
    RD.Store.set('tv.channel', channel);
    if (withNoise !== false && powerOn && !RD.reduceMotion) {
      noiseUntil = performance.now() + 480;   // 换台雪花
    }
    updateChDisplay();
  }

  function spinKnob(k) {
    const cur = (parseInt(k.dataset.rot || '0', 10) + 45) % 360;
    k.dataset.rot = cur;
    k.style.transform = 'rotate(' + cur + 'deg)';
  }

  function power(on) {
    if (on === powerOn) return;
    powerOn = on;
    RD.Store.set('tv.power', on);
    if (on) {
      offMask.classList.add('hidden');
      flash.classList.remove('tv-flash');
      void flash.offsetWidth;                 // 重新触发亮起动画
      flash.classList.add('tv-flash');
      noiseUntil = performance.now() + (RD.reduceMotion ? 0 : 420);
      if (videoMode && video.src) {
        video.play().catch(() => bigPlay.classList.remove('hidden'));
      }
    } else {
      offMask.classList.remove('hidden');
      if (videoMode) video.pause();
      bigPlay.classList.add('hidden');
    }
    btnPower.classList.toggle('on', on);
    updateChDisplay();
    RD.Bus.emit('tv:power', on);
  }

  function setAudioControls() {
    // 无音频来源（频道模式）时明确禁用音量与静音
    volSlider.disabled = !videoMode;
    btnMute.disabled = !videoMode;
    volKnob.classList.toggle('disabled', !videoMode);
    btnMute.textContent = muted ? '🔇' : '🔊';
  }

  function enterVideo(url) {
    videoMode = true;
    paused = false;
    btnPause.textContent = '⏸';
    btnPause.classList.remove('active');
    video.src = url;
    video.loop = true;
    video.muted = muted;                      // 默认静音
    video.volume = volume / 100;
    video.classList.remove('hidden');
    canvas.classList.add('hidden');
    btnBack.classList.remove('hidden');
    if (!powerOn) power(true);
    updateChDisplay();
    setAudioControls();
    video.play().catch(() => {
      // 浏览器拦截自动播放时给出显式播放按钮
      bigPlay.classList.remove('hidden');
    });
  }

  function exitVideo() {
    if (!videoMode) return;
    videoMode = false;
    video.pause();
    video.removeAttribute('src');             // 临时地址不持久化
    video.load();
    video.classList.add('hidden');
    canvas.classList.remove('hidden');
    btnBack.classList.add('hidden');
    bigPlay.classList.add('hidden');
    if (powerOn && !RD.reduceMotion) noiseUntil = performance.now() + 400;
    updateChDisplay();
    setAudioControls();
  }

  function toast(text, ms) {
    if (toastTimer) clearTimeout(toastTimer);
    toastEl.textContent = text;
    toastEl.classList.add('show');
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms || 1600);
  }

  /* ---------------- 事件绑定 ---------------- */
  btnPower.addEventListener('click', () => power(!powerOn));

  btnPrev.addEventListener('click', () => {
    if (videoMode) { exitVideo(); return; }
    setChannel(channel - 1);
    spinKnob(chKnob);
  });
  btnNext.addEventListener('click', () => {
    if (videoMode) { exitVideo(); return; }
    setChannel(channel + 1);
    spinKnob(chKnob);
  });
  chKnob.addEventListener('click', () => {
    if (powerOn && !videoMode) { setChannel(channel + 1); spinKnob(chKnob); }
  });

  btnPause.addEventListener('click', () => {
    if (!powerOn) return;
    paused = !paused;
    if (videoMode) {
      if (paused) video.pause();
      else video.play().catch(() => {});
    }
    btnPause.textContent = paused ? '▶' : '⏸';
    btnPause.classList.toggle('active', paused);
  });

  btnMute.addEventListener('click', () => {
    if (!videoMode) return;
    muted = !muted;
    video.muted = muted;
    RD.Store.set('tv.muted', muted);
    setAudioControls();
  });

  volSlider.addEventListener('input', () => {
    volume = +volSlider.value;
    video.volume = volume / 100;
    if (volume > 0 && muted) {               // 用户主动调音量视为取消静音
      muted = false;
      video.muted = false;
      RD.Store.set('tv.muted', false);
    }
    RD.Store.set('tv.volume', volume);
    volKnob.style.transform = 'rotate(' + (-60 + volume * 1.2) + 'deg)';
    setAudioControls();
  });

  fileInput.addEventListener('change', () => {
    const f = fileInput.files && fileInput.files[0];
    if (f) enterVideo(URL.createObjectURL(f));
    fileInput.value = '';
  });

  bigPlay.addEventListener('click', () => {
    video.play().then(() => bigPlay.classList.add('hidden')).catch(() => {});
  });
  btnBack.addEventListener('click', exitVideo);
  video.addEventListener('playing', () => bigPlay.classList.add('hidden'));

  /* ---------------- 联动：完成待办 → 屏幕提示 ---------------- */
  RD.Bus.on('todo:completed', d => {
    if (!powerOn) return;
    // 只叠加提示条，不打断正在播放的视频 / 频道
    toast('✓ 已完成：' + (d && d.text ? d.text : ''));
  });

  /* ---------------- 初始化 ---------------- */
  volSlider.value = volume;
  volKnob.style.transform = 'rotate(' + (-60 + volume * 1.2) + 'deg)';
  setAudioControls();
  if (RD.Store.get('tv.power', true)) power(true);
  else updateChDisplay();
  setChannel(channel, false);
  loop();
})();
