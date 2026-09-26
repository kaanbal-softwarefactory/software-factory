/* ═══════════════════════════════════════════════════════════════
   AcuaBot — reproductor de referencia del Acuaponsito Framework
   (ver docs/acuaponsito/FRAMEWORK.md)

   Standalone y reutilizable: cualquier página que tenga el markup
   del widget + este script puede darle vida al personaje.

   Novedades v2:
   - ROTACIÓN de variantes: si un estado tiene varios clips, alterna
     entre ellos con crossfade ANTES de que se note el loop — el
     corte desaparece y el personaje se siente vivo.
   - Crossfade más fino (450ms, tenue) + precarga del siguiente clip.
   - Contrato LLM {say, state, clip} sin cambios.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  class AcuaBot {
    /**
     * @param {object} o  {v1, v2, svg, bubble, bubbleText, root, api}
     *   api: (path) => url con auth (opcional; default identidad)
     */
    constructor(o) {
      this.v = [o.v1, o.v2];
      this.svg = o.svg;
      this.bubble = o.bubble;
      this.bubbleText = o.bubbleText;
      this.root = o.root;
      this.api = o.api || ((p) => p);
      this.active = 0;
      this.catalog = null;
      this.byId = {};
      this.byState = {};
      this.currentClip = null;
      this.stateName = null;
      this.videosOk = true;
      this.rotate = true;             // alternar variantes de un estado
      this._typeTimer = null;
      this._hideTimer = null;
      this._rotArmed = false;
      this.v.forEach((vid) => {
        vid.addEventListener("error", () => this._fallback(), true);
        // rotación: cerca del final del clip, si hay variantes, crossfade
        vid.addEventListener("timeupdate", () => this._maybeRotate(vid));
      });
    }

    async load(catalogUrl = "/api/catalog") {
      try {
        const r = await fetch(this.api(catalogUrl));
        this.catalog = await r.json();
        this.byId = {}; this.byState = {};
        for (const c of this.catalog.clips || []) {
          this.byId[c.id] = c;
          (this.byState[c.state] = this.byState[c.state] || []).push(c);
        }
      } catch { this._fallback(); }
      return this;
    }

    /* cadena de fallbacks del árbol: nunca pantalla negra */
    resolveState(state, hops = 0) {
      if (hops > 6 || !this.catalog) return null;
      if (this.byState[state]?.length) return state;
      const fb = this.catalog.states?.[state]?.fallback;
      return fb ? this.resolveState(fb, hops + 1) : null;
    }

    _pickFrom(pool) {
      let pick = pool[Math.floor(Math.random() * pool.length)];
      if (pool.length > 1 && this.currentClip && pick.id === this.currentClip.id) {
        pick = pool[(pool.indexOf(pick) + 1) % pool.length];
      }
      return pick;
    }

    setState(state) {
      this.stateName = state;
      const resolved = this.resolveState(state);
      const pool = resolved ? this.byState[resolved] : (this.catalog?.clips || []);
      if (!pool.length) return this._fallback(state);
      this.playClip(this._pickFrom(pool));
    }

    /* contrato LLM: clip válido > state > fallback */
    applyLLM(res) {
      if (res.clip && this.byId[res.clip]) {
        this.stateName = this.byId[res.clip].state;
        this.playClip(this.byId[res.clip]);
      } else if (res.state) this.setState(res.state);
      if (res.say) this.speak(res.say);
    }

    playClip(clip) {
      if (!this.videosOk) return this._fallback(clip.state);
      if (this.currentClip?.id === clip.id && this._rotArmed === false) return;
      this.currentClip = clip;
      this._rotArmed = false;
      const next = this.v[1 - this.active];
      const curr = this.v[this.active];
      next.src = clip.url.startsWith("/") ? clip.url : "/" + clip.url;
      next.loop = false;              // el loop lo maneja la rotación
      const swap = () => {
        next.play().catch(() => {});
        next.classList.add("on");     // crossfade tenue — sin cortes visibles
        curr.classList.remove("on");
        this.active = 1 - this.active;
        setTimeout(() => {
          if (!curr.classList.contains("on")) curr.pause();
          this._rotArmed = true;      // habilitar rotación para ESTE ciclo
        }, 500);
      };
      if (next.readyState >= 3) swap();
      else next.addEventListener("canplay", swap, { once: true });
      this.svg?.classList.add("hidden");
    }

    _maybeRotate(vid) {
      if (!this._rotArmed || vid !== this.v[this.active]) return;
      if (!vid.duration || vid.currentTime < vid.duration - 0.55) return;
      this._rotArmed = false;
      const resolved = this.resolveState(this.stateName);
      const pool = resolved ? this.byState[resolved] : [];
      if (this.rotate && pool.length > 1) {
        this.playClip(this._pickFrom(pool));   // variante distinta, crossfade
      } else {
        vid.currentTime = 0.01;                // loop del mismo clip
        vid.play().catch(() => {});
        this._rotArmed = true;
      }
    }

    speak(text, opts = {}) {
      if (!this.bubble) return;
      clearInterval(this._typeTimer); clearTimeout(this._hideTimer);
      this.bubble.classList.remove("hidden", "done");
      this.bubbleText.textContent = "";
      let i = 0;
      this._typeTimer = setInterval(() => {
        this.bubbleText.textContent = text.slice(0, ++i);
        if (i >= text.length) {
          clearInterval(this._typeTimer);
          this.bubble.classList.add("done");
          this._hideTimer = setTimeout(
            () => this.bubble.classList.add("hidden"), opts.stay || 12000);
        }
      }, 26);
    }

    awake(on = true) { this.root?.classList.toggle("awake", on); }

    _fallback(state) {
      this.videosOk = false;
      this.v.forEach((vid) => { vid.classList.remove("on"); vid.pause(); });
      this.svg?.classList.remove("hidden");
      this.svg?.classList.toggle("bot-success", state === "celebrate");
      this.svg?.classList.toggle("bot-error", state === "error");
    }

    /* hace el widget arrastrable; onTap se dispara si NO hubo arrastre */
    draggable(stageEl, onTap) {
      const el = this.root;
      stageEl.addEventListener("pointerdown", (e) => {
        const sx = e.clientX, sy = e.clientY;
        const r = el.getBoundingClientRect(); const ox = r.left, oy = r.top;
        let moved = false;
        stageEl.setPointerCapture(e.pointerId);
        const mv = (ev) => {
          const dx = ev.clientX - sx, dy = ev.clientY - sy;
          if (Math.abs(dx) + Math.abs(dy) > 6) moved = true;
          if (moved) {
            el.style.left = Math.max(4, Math.min(innerWidth - 180, ox + dx)) + "px";
            el.style.top = Math.max(4, Math.min(innerHeight - 190, oy + dy)) + "px";
            el.style.right = "auto"; el.style.bottom = "auto";
            el.style.alignItems = "flex-start";
          }
        };
        const up = () => {
          stageEl.removeEventListener("pointermove", mv);
          stageEl.removeEventListener("pointerup", up);
          if (!moved && onTap) onTap();
        };
        stageEl.addEventListener("pointermove", mv);
        stageEl.addEventListener("pointerup", up);
      });
      return this;
    }
  }
  window.AcuaBot = AcuaBot;
})();
