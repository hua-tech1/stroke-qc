/* 降级横幅：PG / Redis 不可用时在页面顶部提示，而不是让用户对着一片空白猜。
   只在依赖数据库的页面引入（role / cases / followups / qc）。 */
(async function () {
  try {
    const r = await fetch('/health', { headers: { 'Accept': 'application/json' } });
    const d = await r.json();
    if (d.postgres && d.redis) return;

    const missing = [!d.postgres && 'PostgreSQL', !d.redis && 'Redis'].filter(Boolean).join(' / ');
    const bar = document.createElement('div');
    bar.setAttribute('data-degrade', missing);
    bar.style.cssText = [
      'background:#FFF1C2', 'color:#7A4A0B', 'border-bottom:1px solid #E6C86A',
      'padding:5px 12px', 'font:12px "Microsoft YaHei","PingFang SC",sans-serif',
      'text-align:center', 'line-height:1.5'
    ].join(';');
    bar.innerHTML = `<b>降级运行</b>：${missing} 不可用 —— 依赖数据库的内容将显示错误或空数据；`
      + `影像回放与事件计算不受影响。恢复服务后刷新即可。`;
    document.body.insertBefore(bar, document.body.firstChild);
  } catch (e) { /* 健康检查失败本身不阻塞页面 */ }
})();
