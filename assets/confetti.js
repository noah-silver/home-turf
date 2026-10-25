// Tiny confetti burst for celebratory moments (a confirmed watch party, a posted review).
// Fires whenever a new success notice appears. No libraries.
(function () {
  const colors = ["#e8a91b", "#1d8a4a", "#0f2240", "#d7263d", "#ffffff", "#2f6db3"];
  function burst() {
    if (window.__HT_NO_CONFETTI) return;  // screenshots
    let c = document.getElementById("confetti-canvas");
    if (!c) { c = document.createElement("canvas"); c.id = "confetti-canvas"; document.body.appendChild(c); }
    c.width = innerWidth; c.height = innerHeight;
    const ctx = c.getContext("2d");
    const parts = Array.from({ length: 140 }, () => ({
      x: innerWidth / 2 + (Math.random() - 0.5) * 200, y: innerHeight / 3,
      vx: (Math.random() - 0.5) * 14, vy: Math.random() * -12 - 4, r: Math.random() * 6 + 4,
      c: colors[Math.floor(Math.random() * colors.length)], a: Math.random() * Math.PI, va: (Math.random() - 0.5) * 0.3,
    }));
    let frames = 0;
    (function tick() {
      ctx.clearRect(0, 0, c.width, c.height);
      parts.forEach(p => { p.vy += 0.35; p.x += p.vx; p.y += p.vy; p.a += p.va;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2); ctx.restore(); });
      if (++frames < 110) requestAnimationFrame(tick); else ctx.clearRect(0, 0, c.width, c.height);
    })();
  }
  new MutationObserver(muts => {
    for (const m of muts) for (const n of m.addedNodes) {
      if (n.nodeType === 1 && ((n.matches && n.matches(".notice.ok, .celebrate")) || (n.querySelector && n.querySelector(".notice.ok, .celebrate")))) { burst(); return; }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
