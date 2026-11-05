/* 顶栏：按角色裁剪菜单 + 当前用户 + 退出。
   只改 <header> 里的 <a>，不动页面其他内容（如术中监控的序列下拉框）。 */
(async function () {
  let me;
  try {
    const r = await fetch('/api/me', { headers: { 'Accept': 'application/json' } });
    if (!r.ok) { location.replace('/login'); return; }
    me = await r.json();
  } catch (e) { return; }

  const ROLE_CN = { doctor: '医生', nurse: '护士', qc: '质控科', guest: '访客' };
  // 与后端 auth.READ_PAGES 保持一致
  const ALLOW = {
    doctor: ['/monitor', '/cases'],
    nurse:  ['/followups', '/cases'],
    qc:     ['/qc', '/cases'],
    guest:  ['/monitor', '/cases', '/followups', '/qc']
  };
  const ok = ALLOW[me.role] || [];
  const header = document.querySelector('header');
  if (!header) return;

  // 1) 隐藏无权访问的链接
  header.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href');
    if (!href || href === '/' || href === '#' || href.startsWith('/about')) return;
    const path = href.split('?')[0];
    if (!ok.some(p => path === p || path.startsWith(p + '/'))) a.remove();
  });

  // 2) 追加当前用户与退出
  let right = header.querySelector('.right');
  if (!right) {
    right = document.createElement('div');
    right.className = 'right';
    header.appendChild(right);
  }
  const who = document.createElement('span');
  who.style.cssText = 'color:#CFE0F5;font-size:12px;margin-left:10px;white-space:nowrap';
  who.textContent = `${me.name} · ${ROLE_CN[me.role] || me.role}`;

  const out = document.createElement('a');
  out.href = '#';
  out.textContent = '退出';
  out.style.cssText = 'color:#fff;text-decoration:none;border:1px solid rgba(255,255,255,.45);'
    + 'padding:2px 8px;border-radius:2px;white-space:nowrap';
  out.onclick = async (e) => {
    e.preventDefault();
    try { await fetch('/api/logout', { method: 'POST' }); } catch (err) {}
    location.replace('/login');
  };

  right.appendChild(who);
  right.appendChild(out);
})();
