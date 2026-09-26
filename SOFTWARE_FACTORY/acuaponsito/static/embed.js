/* ═══════════════════════════════════════════════════════════════
   Acuaponsito Embed — UN script y el agente vive en tu app
   ================================================================
   <script src="http://HOST:4600/embed.js" data-token="TOKEN"></script>

   - Shadow DOM + position:fixed + z-index máximo: capa propia,
     JAMÁS interfiere con el DOM, CSS o flujo de la app anfitriona.
   - Botón flotante CHICO y arrastrable con el video del personaje.
   - Hover → crece al doble. Clic → panel medio y el botón se OCULTA
     (nunca dos Acuaponsitos a la vez). Expandir → pantalla completa.
   - Cerrar → vuelve el botón chico, justo donde lo dejaste.
   ═══════════════════════════════════════════════════════════════ */
(() => {
  const sc = document.currentScript;
  const BASE = (sc.dataset.agent || new URL(sc.src).origin).replace(/\/$/, "");
  const TOKEN = sc.dataset.token || new URLSearchParams(location.search).get("token") || "";
  const api = (p) => `${BASE}${p}${p.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}`;

  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;z-index:2147483000;";
  document.documentElement.appendChild(host);
  const root = host.attachShadow({ mode: "closed" });

  root.innerHTML = `
  <style>
    :host { all: initial; }
    /* botón chico y arrastrable */
    .btn {
      position: fixed; right: 22px; bottom: 22px; width: 66px; height: 66px;
      border-radius: 20px; overflow: hidden; cursor: grab; border: 1.5px solid rgba(103,232,249,.35);
      background: #08131f; box-shadow: 0 12px 34px rgba(2,12,26,.55), 0 0 22px rgba(34,211,238,.18);
      transition: width .2s ease, height .2s ease, box-shadow .2s ease, border-radius .2s ease;
      z-index: 2; touch-action: none;
    }
    .btn:hover {   /* hover → crece al doble */
      width: 132px; height: 132px; border-radius: 30px;
      box-shadow: 0 20px 56px rgba(2,12,26,.7), 0 0 46px rgba(45,212,191,.32);
    }
    .btn:active { cursor: grabbing; }
    .btn.dragging { transition: none; }
    .btn.gone { opacity: 0; transform: scale(.6); pointer-events: none; }
    .btn video { width: 100%; height: 100%; object-fit: cover; display: block; pointer-events: none; }
    .badge {
      position: absolute; top: -5px; right: -5px; min-width: 20px; height: 20px;
      border-radius: 99px; background: #fb7185; color: #fff; font: 700 11px system-ui;
      display: none; align-items: center; justify-content: center; padding: 0 5px;
      border: 2px solid #08131f;
    }
    .sheet {
      position: fixed; right: 18px; bottom: 18px; width: min(440px, calc(100vw - 36px));
      height: min(680px, calc(100vh - 40px)); border-radius: 20px; overflow: hidden;
      border: 1px solid rgba(103,232,249,.25); background: #061120;
      box-shadow: 0 30px 90px rgba(2,10,22,.75), 0 0 40px rgba(34,211,238,.1);
      opacity: 0; transform: translateY(14px) scale(.98); pointer-events: none;
      transition: all .28s cubic-bezier(.2,.8,.25,1);
    }
    .sheet.open { opacity: 1; transform: none; pointer-events: auto; }
    .sheet.full { right: 14px; bottom: 14px; left: 14px; top: 14px; width: auto; height: auto; }
    .sheet iframe { width: 100%; height: 100%; border: 0; }
  </style>
  <div class="sheet" id="sheet"><iframe id="frame" allow="autoplay" title="Acuaponsito"></iframe></div>
  <div class="btn" id="btn" title="Tu agente 🌱 (arrástrame o tócame)"><video id="bv" muted loop playsinline></video><span class="badge" id="badge"></span></div>`;

  const $ = (id) => root.getElementById(id);
  const sheet = $("sheet"), frame = $("frame"), btn = $("btn"), badge = $("badge"), bv = $("bv");
  let open = false, unread = 0, catalog = null, frameLoaded = false;

  /* ── video del botón según estado real ── */
  async function loadCatalog() {
    try { catalog = await (await fetch(api("/api/catalog"))).json(); } catch { catalog = { clips: [], states: {} }; }
  }
  function clipFor(state, hops = 0) {
    if (!catalog || hops > 6) return null;
    const pool = catalog.clips.filter((c) => c.state === state);
    if (pool.length) return pool[Math.floor(Math.random() * pool.length)];
    const fb = catalog.states?.[state]?.fallback;
    return fb ? clipFor(fb, hops + 1) : catalog.clips[0] || null;
  }
  function setBtnState(state) {
    const clip = clipFor(state);
    if (clip && !bv.src.endsWith(clip.url)) { bv.src = BASE + clip.url; bv.play().catch(() => {}); }
    else if (clip) bv.play().catch(() => {});
  }
  async function pollState() {
    if (open) return;
    try { const b = await (await fetch(api("/api/boot"))).json(); setBtnState(b.bot.state); } catch {}
  }

  /* ── abrir / cerrar / expandir (nunca dos bots) ── */
  function openPanel() {
    if (!frameLoaded) { frame.src = api("/panel"); frameLoaded = true; }
    sheet.classList.add("open");
    btn.classList.add("gone");        // ← el botón desaparece: solo el panel
    open = true; unread = 0; badge.style.display = "none";
  }
  function closePanel() {
    sheet.classList.remove("open", "full");
    btn.classList.remove("gone");     // ← vuelve el botón chico
    open = false;
  }

  /* ── arrastrar el botón (distingue tap de drag) ── */
  let drag = null;
  btn.addEventListener("pointerdown", (e) => {
    const r = btn.getBoundingClientRect();
    drag = { sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top, moved: false };
    btn.setPointerCapture(e.pointerId);
    btn.classList.add("dragging");
  });
  btn.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (Math.abs(dx) + Math.abs(dy) > 6) drag.moved = true;
    if (drag.moved) {
      const w = btn.offsetWidth, h = btn.offsetHeight;
      const nx = Math.max(6, Math.min(innerWidth - w - 6, drag.ox + dx));
      const ny = Math.max(6, Math.min(innerHeight - h - 6, drag.oy + dy));
      btn.style.left = nx + "px"; btn.style.top = ny + "px";
      btn.style.right = "auto"; btn.style.bottom = "auto";
    }
  });
  btn.addEventListener("pointerup", () => {
    btn.classList.remove("dragging");
    if (drag && !drag.moved) openPanel();   // fue un toque → abrir
    drag = null;
  });

  addEventListener("message", (e) => {
    const d = e.data;
    if (!d || !d.acua) return;
    if (e.source === window && d.kind === "open") return openPanel();  // API de la app host
    if (d.kind === "close") closePanel();
    if (d.kind === "size") sheet.classList.toggle("full", d.mode === "full");
    if (d.kind === "state") setBtnState(d.state);
    if (d.kind === "unread" && !open) { unread++; badge.textContent = unread; badge.style.display = "flex"; }
    if (d.kind === "approvals" && d.pending > 0 && !open) { badge.textContent = d.pending; badge.style.display = "flex"; }
  });

  loadCatalog().then(pollState);
  setInterval(pollState, 40000);
})();
