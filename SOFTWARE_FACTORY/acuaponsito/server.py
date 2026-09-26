#!/usr/bin/env python3
"""
Acuaponsito Agent Runtime — el motor del agente, separado de toda app
=====================================================================
Un solo archivo, cero dependencias (stdlib). Corre como proceso, servicio
systemd o contenedor. Cualquier app lo embebe con UN script:

    <script src="http://HOST:4600/embed.js" data-token="TOKEN"></script>

El agente vive en SU capa: botón flotante → panel medio → pantalla completa
encima de la UI anfitriona, sin tocar jamás el flujo del usuario.

Poder real, seguro por diseño:
  - El LLM puede PROPONER acciones (bash) → quedan en cola de APROBACIÓN;
    solo un admin las ejecuta (o auto_approve explícito).
  - Login interno privado (vive en tu VPS/PC), roles: admin/member/observer.
  - WebSocket propio (RFC6455, stdlib): presencia, chat en tiempo real entre
    personas y con el agente, estado del bot sincronizado en todos los embeds.
  - Memoria JSONL amigable para IA + chats persistentes.
  - Identidad configurable: nombre, personalidad, modo descanso, idle timer.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import smtplib
import socket
import struct
import subprocess
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA_DIR = os.environ.get("ACUA_DATA_DIR", os.path.expanduser("~/.acuaponsito"))
os.makedirs(DATA_DIR, exist_ok=True)
PORT = int(os.environ.get("ACUA_PORT", "4600"))
TOKEN = os.environ.get("ACUA_TOKEN") or secrets.token_urlsafe(18)

_ANIM_CANDIDATES = [
    os.environ.get("KAANBAL_ANIM_DIR", ""),
    os.path.normpath(os.path.join(HERE, "..", "..", "animacion")),
    "/anim",
]
ANIM_DIR = next((p for p in _ANIM_CANDIDATES if p and os.path.isdir(p)), None)

# ── configuración persistente (identidad del agente) ─────────────────────────
CONFIG_FILE = os.path.join(DATA_DIR, "agent.config.json")
CONFIG_LOCK = threading.Lock()
DEFAULT_CONFIG = {
    "name": "Acuaponsito",
    "personality": "tierno, científico y práctico; guía a makers y científicos a digitalizar e integrar IA en sus sistemas",
    "goal": "guiar al usuario hacia sus objetivos: detectar patrones, proponer automatizaciones y preparar el camino a MLOps",
    "providers": [],           # [{provider, api_key, model}]
    "idle_minutes": 8,
    "rest_mode": False,        # modo descanso: no propone, solo responde
    "auto_approve": False,     # ejecutar acciones sin aprobación (¡solo si confías!)
    "respond_in_team": "mention",  # mention | always
    "schedules": [],           # [{id, name, every_minutes, prompt}]
    "webhooks": [],            # [{id, name, prompt}]
}


def load_config():
    with CONFIG_LOCK:
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = {**DEFAULT_CONFIG, **json.load(f)}
        except FileNotFoundError:
            cfg = dict(DEFAULT_CONFIG)
        return cfg


def save_config(cfg):
    with CONFIG_LOCK:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(CONFIG_FILE, 0o600)  # contiene API keys
        except Exception:
            pass


# ── usuarios y sesiones (login interno privado) ──────────────────────────────
USERS_FILE = os.path.join(DATA_DIR, "users.json")
USERS_LOCK = threading.Lock()
SESSIONS = {}  # session_id -> {user, role, since}
RESETS = {}    # token -> {user, expires}
RESETS_LOCK = threading.Lock()


def _hash_pw(pw, salt):
    return hashlib.sha256((salt + pw).encode()).hexdigest()


def load_users():
    with USERS_LOCK:
        try:
            with open(USERS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}


def save_users(users):
    with USERS_LOCK:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
        try:
            os.chmod(USERS_FILE, 0o600)
        except Exception:
            pass


def find_user_by_identifier(identifier):
    """Login con usuario O correo — busca username exacto, luego email (case-insensitive)."""
    users = load_users()
    if identifier in users:
        return identifier, users[identifier]
    ident_low = (identifier or "").strip().lower()
    for uname, u in users.items():
        if (u.get("email") or "").strip().lower() == ident_low and ident_low:
            return uname, u
    return None, None


def auth_session(handler):
    sid = handler.headers.get("X-Session", "")
    return SESSIONS.get(sid)


def system_status():
    """Estados claros para la UI: sin_admin (nunca se creó el guardián) vs activo
    (ya existe al menos un admin — el arranque real ocurrió)."""
    users = load_users()
    has_admin = any(u.get("role") == "admin" for u in users.values())
    if not users or not has_admin:
        return {"code": "sin_admin", "label": "Aún no inicia — falta crear al guardián"}
    return {"code": "activo", "label": "Sistema iniciado"}


# ── correo: recuperación de contraseña (smtplib stdlib; fallback local honesto) ──
SMTP_HOST = os.environ.get("ACUA_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("ACUA_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ACUA_SMTP_USER", "")
SMTP_PASS = os.environ.get("ACUA_SMTP_PASS", "")
SMTP_FROM = os.environ.get("ACUA_SMTP_FROM", SMTP_USER)
OUTBOX_DIR = os.path.join(DATA_DIR, "outbox")


def send_email(to_addr, subject, body):
    """Envía correo real si hay SMTP configurado (env ACUA_SMTP_*). Si no,
    escribe el mensaje en ~/.acuaponsito/outbox/ y lo deja en la memoria del
    agente — nunca se pierde el enlace de recuperación, solo cambia el canal."""
    if SMTP_HOST and SMTP_USER and SMTP_PASS:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SMTP_FROM
            msg["To"] = to_addr
            msg.set_content(body)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
            return True, "enviado"
        except Exception as e:
            return False, f"fallo SMTP: {e}"
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    fname = os.path.join(OUTBOX_DIR, f"{int(time.time())}-{re.sub(r'[^a-zA-Z0-9@._-]', '_', to_addr)}.txt")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(f"Para: {to_addr}\nAsunto: {subject}\n\n{body}\n")
    return False, f"SMTP no configurado — mensaje guardado en {fname} (configura ACUA_SMTP_HOST/USER/PASS para envío real)"


# ── memoria (JSONL amigable para IA) ─────────────────────────────────────────
MEMORY_FILE = os.path.join(DATA_DIR, "memory.jsonl")
MEMORY_LOCK = threading.Lock()


def remember(source, kind, **detail):
    ev = {"ts": round(time.time(), 2), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
          "source": source, "kind": kind, **detail}
    with MEMORY_LOCK, open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def recall(limit=100):
    try:
        with MEMORY_LOCK, open(MEMORY_FILE, encoding="utf-8") as f:
            return [json.loads(l) for l in f.readlines()[-limit:] if l.strip()]
    except FileNotFoundError:
        return []


# ── chats persistentes por canal ─────────────────────────────────────────────
CHATS_FILE = os.path.join(DATA_DIR, "chats.jsonl")
CHATS_LOCK = threading.Lock()


def chat_append(msg):
    with CHATS_LOCK, open(CHATS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def chat_history(channel, limit=60):
    try:
        with CHATS_LOCK, open(CHATS_FILE, encoding="utf-8") as f:
            msgs = [json.loads(l) for l in f if l.strip()]
        return [m for m in msgs if m["channel"] == channel][-limit:]
    except FileNotFoundError:
        return []


# ── estado global del bot + WebSocket hub ────────────────────────────────────
BOT = {"state": "sleep", "clip": None, "since": time.time()}
LAST_INTERACTION = [time.time()]
WS_CLIENTS = []          # [{sock, lock, user, role}]
WS_LOCK = threading.Lock()
APPROVALS = []           # [{id, cmd, reason, requested_by, channel, status}]
APPROVALS_LOCK = threading.Lock()


def ws_frame(payload: bytes, opcode=0x1) -> bytes:
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


def ws_broadcast(obj, role_min=None):
    data = ws_frame(json.dumps(obj, ensure_ascii=False).encode())
    with WS_LOCK:
        clients = list(WS_CLIENTS)
    for c in clients:
        try:
            with c["lock"]:
                c["sock"].sendall(data)
        except Exception:
            with WS_LOCK:
                if c in WS_CLIENTS:
                    WS_CLIENTS.remove(c)


def set_bot_state(state, clip=None):
    BOT.update({"state": state, "clip": clip, "since": time.time()})
    ws_broadcast({"type": "bot_state", "state": state, "clip": clip})


def presence_broadcast():
    with WS_LOCK:
        users = sorted({c["user"] for c in WS_CLIENTS})
    ws_broadcast({"type": "presence", "users": users})


def touch():
    LAST_INTERACTION[0] = time.time()
    if BOT["state"] in ("rest",):
        set_bot_state("idle")


# ── catálogo del framework de animación ──────────────────────────────────────
def load_catalog():
    if ANIM_DIR:
        try:
            with open(os.path.join(ANIM_DIR, "catalog.json"), encoding="utf-8") as f:
                cat = json.load(f)
            for c in cat.get("clips", []):
                c["url"] = "/anim/" + urllib.parse.quote(c["file"])
            cat["source"] = "animacion"
            return cat
        except Exception:
            pass
    return {"source": "none", "states": {}, "clips": []}


def _catalog_for_llm():
    cat = load_catalog()
    states = ", ".join(cat.get("states", {}).keys()) or "sleep, idle, greet, think, speak"
    lines = [f'- {c["id"]}: {c.get("description", "")[:120]}' for c in cat.get("clips", [])]
    return states, "\n".join(lines) or "- (sin clips aún)"


# ── contexto del host (funciona en cualquier Linux, con o sin k8s) ───────────
def host_context():
    ctx = {"hostname": socket.gethostname().lower()}
    try:
        ctx["load"] = open("/proc/loadavg").read().split()[:3]
        mem = open("/proc/meminfo").read()
        total = int(re.search(r"MemTotal:\s+(\d+)", mem).group(1)) // 1024
        avail = int(re.search(r"MemAvailable:\s+(\d+)", mem).group(1)) // 1024
        ctx["mem_mb"] = {"total": total, "available": avail}
        d = shutil.disk_usage("/")
        ctx["disk_free_gb"] = round(d.free / 1024**3)
        ctx["uptime_h"] = round(float(open("/proc/uptime").read().split()[0]) / 3600, 1)
    except Exception:
        pass
    if shutil.which("k3s") or shutil.which("kubectl"):
        kb = "k3s kubectl" if shutil.which("k3s") else "kubectl"
        try:
            out = subprocess.run(f"{kb} get pods -A --no-headers 2>/dev/null", shell=True,
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            if out:
                lines = out.splitlines()
                ctx["k8s"] = {"pods": len(lines),
                              "running": sum(" Running " in l for l in lines)}
        except Exception:
            pass
    return ctx


# ── proveedor LLM ─────────────────────────────────────────────────────────────
AI_PROVIDERS = {
    "deepseek": {"base": "https://api.deepseek.com", "models_path": "/models",
                 "chat_path": "/chat/completions", "default_model": "deepseek-chat", "style": "openai"},
    "openai": {"base": "https://api.openai.com", "models_path": "/v1/models",
               "chat_path": "/v1/chat/completions", "default_model": "gpt-4o-mini", "style": "openai"},
    "anthropic": {"base": "https://api.anthropic.com", "models_path": "/v1/models",
                  "chat_path": "/v1/messages", "default_model": "claude-haiku-4-5-20251001", "style": "anthropic"},
}


def _headers(provider, key):
    if AI_PROVIDERS[provider]["style"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def http_json(url, headers=None, data=None, timeout=45):
    req = urllib.request.Request(url, headers=headers or {})
    if data is not None:
        req.data = data.encode()
        req.method = "POST"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def validate_provider(provider, key):
    if provider not in AI_PROVIDERS:
        return {"valid": False, "message": "Proveedor desconocido"}
    p = AI_PROVIDERS[provider]
    status, resp = http_json(p["base"] + p["models_path"], _headers(provider, key), timeout=20)
    if status == 200:
        models = [m.get("id", "") for m in resp.get("data", [])][:5]
        return {"valid": True, "message": f"✓ {provider} conectado", "models": models,
                "default_model": p["default_model"]}
    return {"valid": False, "message": f"{provider} HTTP {status}"}


def ai_call(system, messages, max_tokens=800):
    cfg = load_config()
    if not cfg["providers"]:
        return None, "sin-proveedor"
    e = cfg["providers"][0]
    p = AI_PROVIDERS[e["provider"]]
    model = e.get("model") or p["default_model"]
    if p["style"] == "anthropic":
        body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system, "messages": messages})
        status, resp = http_json(p["base"] + p["chat_path"], _headers(e["provider"], e["api_key"]), body)
        if status != 200:
            return None, f"{e['provider']} HTTP {status}"
        return resp.get("content", [{}])[0].get("text", ""), None
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": system}] + messages})
    status, resp = http_json(p["base"] + p["chat_path"], _headers(e["provider"], e["api_key"]), body)
    if status != 200:
        return None, f"{e['provider']} HTTP {status}"
    return resp.get("choices", [{}])[0].get("message", {}).get("content", ""), None


def parse_contract(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            out = json.loads(m.group(0))
            return {"say": out.get("say", text), "state": out.get("state", "speak"),
                    "clip": out.get("clip"), "action": out.get("action")}
        except json.JSONDecodeError:
            pass
    return {"say": (text or "").strip(), "state": "speak", "clip": None, "action": None}


def agent_system_prompt(user, channel):
    cfg = load_config()
    states, clips = _catalog_for_llm()
    ctx = host_context()
    with WS_LOCK:
        online = sorted({c["user"] for c in WS_CLIENTS})
    mem = recall(20)
    mem_lines = "; ".join(f'{e.get("kind")}:{str(e.get("text", e.get("user", "")))[:60]}' for e in mem[-8:])
    return (
        f"Eres {cfg['name']}, agente de plataforma embebido en el sistema del usuario. "
        f"Personalidad: {cfg['personality']}. Meta: {cfg['goal']}.\n"
        f"Hablas con '{user}' en el canal '{channel}'. Usuarios en línea: {', '.join(online) or 'solo tú'}.\n"
        f"HOST: {json.dumps(ctx, ensure_ascii=False)}\n"
        f"MEMORIA RECIENTE: {mem_lines or 'vacía'}\n\n"
        "Respondes SIEMPRE un único JSON válido sin markdown:\n"
        '{"say":"<respuesta en español>","state":"<estado>","clip":"<opcional>",'
        '"action":{"tool":"bash","cmd":"<comando>","reason":"<por qué>"} (SOLO si una acción ayuda)}\n'
        f"Estados: {states}.\nClips:\n{clips}\n"
        "Las acciones NUNCA se ejecutan directo: van a una cola de aprobación humana. "
        "Propón comandos de lectura/diagnóstico primero; sé conservador con escrituras."
    )


def agent_reply(user, channel, text):
    """Pipeline: mensaje → LLM → contrato → broadcast + acción a aprobación."""
    set_bot_state("think")
    history = [{"role": "assistant" if m["from"] == "bot" else "user", "content": m["text"]}
               for m in chat_history(channel, 10)]
    say_error = None
    raw, err = ai_call(agent_system_prompt(user, channel), history + [{"role": "user", "content": text}])
    if err == "sin-proveedor":
        res = {"say": "Aún no tengo un proveedor de IA configurado 💤 — despiértame en Ajustes.",
               "state": "sleep", "clip": None, "action": None}
    elif err:
        res = {"say": f"⚠ Mi proveedor falló: {err}", "state": "warn", "clip": None, "action": None}
    else:
        res = parse_contract(raw)
    msg = {"id": secrets.token_hex(6), "channel": channel, "from": "bot", "user": load_config()["name"],
           "text": res["say"], "ts": time.time()}
    chat_append(msg)
    ws_broadcast({"type": "chat", **msg})
    set_bot_state(res.get("state") or "idle", res.get("clip"))
    if res.get("action") and isinstance(res["action"], dict) and res["action"].get("cmd"):
        add_approval(res["action"], requested_by=load_config()["name"], channel=channel)
    remember("agent", "chat", channel=channel, user=text[:120], agent=str(res["say"])[:120])


# ── acciones con aprobación humana ───────────────────────────────────────────
def add_approval(action, requested_by, channel):
    item = {"id": secrets.token_hex(5), "cmd": action.get("cmd", ""),
            "reason": action.get("reason", ""), "requested_by": requested_by,
            "channel": channel, "status": "pending", "ts": time.time(), "output": None}
    with APPROVALS_LOCK:
        APPROVALS.append(item)
    ws_broadcast({"type": "approval", "item": item})
    cfg = load_config()
    if cfg.get("auto_approve"):
        threading.Thread(target=run_approval, args=(item["id"], "auto"), daemon=True).start()
    return item


def run_approval(aid, approver):
    with APPROVALS_LOCK:
        item = next((a for a in APPROVALS if a["id"] == aid), None)
        if not item or item["status"] != "pending":
            return
        item["status"] = "running"
    ws_broadcast({"type": "approval", "item": item})
    set_bot_state("work")
    try:
        proc = subprocess.run(item["cmd"], shell=True, capture_output=True, text=True,
                              timeout=90, cwd=os.path.expanduser("~"))
        out = (proc.stdout + proc.stderr)[-4000:]
        item["output"] = out or "(sin salida)"
        item["status"] = "done" if proc.returncode == 0 else "failed"
    except Exception as e:
        item["output"] = str(e)
        item["status"] = "failed"
    ws_broadcast({"type": "approval", "item": item})
    msg = {"id": secrets.token_hex(6), "channel": item["channel"], "from": "system",
           "user": "acción", "text": f"$ {item['cmd']}\n{item['output']}", "ts": time.time()}
    chat_append(msg)
    ws_broadcast({"type": "chat", **msg})
    set_bot_state("idle")
    remember("agent", "accion-ejecutada", cmd=item["cmd"][:150], status=item["status"], by=approver)


# ── vida propia: idle, aburrimiento, schedules ───────────────────────────────
TIPS = [
    "¿Sabías que puedo vigilar tu sistema con un schedule? Configúralo en Automatización ⏱️",
    "Llevo rato tranquilo… ¿te propongo ideas para meter IA a tus datos? 🌱",
    "Tip: registra notas clave en mi memoria y las tendré presentes en cada respuesta 📌",
    "Puedo proponer comandos de diagnóstico — tú siempre apruebas antes de que toque algo 🛡️",
]


def life_loop():
    tip_i = 0
    last_tip = 0
    while True:
        time.sleep(30)
        cfg = load_config()
        idle_s = time.time() - LAST_INTERACTION[0]
        if idle_s > cfg["idle_minutes"] * 60 and BOT["state"] not in ("rest", "sleep"):
            set_bot_state("rest")
        if (not cfg["rest_mode"] and idle_s > cfg["idle_minutes"] * 60 * 2
                and time.time() - last_tip > 1800):
            last_tip = time.time()
            msg = {"id": secrets.token_hex(6), "channel": "team", "from": "bot",
                   "user": cfg["name"], "text": TIPS[tip_i % len(TIPS)], "ts": time.time()}
            tip_i += 1
            chat_append(msg)
            ws_broadcast({"type": "chat", **msg})
        # schedules: prompts periódicos → canal equipo
        for sch in cfg.get("schedules", []):
            key = f"_last_{sch['id']}"
            last = getattr(life_loop, key, 0)
            if time.time() - last >= sch.get("every_minutes", 60) * 60:
                setattr(life_loop, key, time.time())
                threading.Thread(target=agent_reply, daemon=True,
                                 args=("schedule", "team", f"[Tarea programada: {sch['name']}] {sch['prompt']}")).start()


# ── HTTP + WS handler ─────────────────────────────────────────────────────────
MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".mp4": "video/mp4", ".svg": "image/svg+xml", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "AcuaponsitoRuntime/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ---------- helpers ----------
    def _token_ok(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        t = q.get("token", [None])[0] or self.headers.get("X-Token")
        return t == TOKEN

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, X-Session")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, X-Session")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _file(self, root, rel):
        rel = urllib.parse.unquote(rel)
        fp = os.path.normpath(os.path.join(root, rel.lstrip("/")))
        if not fp.startswith(os.path.normpath(root)) or not os.path.isfile(fp):
            self.send_error(404)
            return
        size = os.path.getsize(fp)
        ctype = MIME.get(os.path.splitext(fp)[1], "application/octet-stream")
        rng = self.headers.get("Range")
        with open(fp, "rb") as f:
            if rng:
                m = re.match(r"bytes=(\d+)-(\d*)", rng)
                start = int(m.group(1)) if m else 0
                end = int(m.group(2)) if m and m.group(2) else size - 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Content-Type", ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                f.seek(start)
                self.wfile.write(f.read(end - start + 1))
            else:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                shutil.copyfileobj(f, self.wfile)

    # ---------- WebSocket ----------
    def _ws_upgrade(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        sid = q.get("session", [""])[0]
        sess = SESSIONS.get(sid)
        if not self._token_ok() or not sess:
            self.send_error(401)
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        sock = self.connection
        client = {"sock": sock, "lock": threading.Lock(), "user": sess["user"], "role": sess["role"]}
        with WS_LOCK:
            WS_CLIENTS.append(client)
        presence_broadcast()
        with client["lock"]:
            sock.sendall(ws_frame(json.dumps(
                {"type": "bot_state", "state": BOT["state"], "clip": BOT["clip"]}).encode()))
        try:
            while True:
                head = self._recv_exact(sock, 2)
                if not head:
                    break
                opcode = head[0] & 0x0F
                masked = head[1] & 0x80
                length = head[1] & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._recv_exact(sock, 2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._recv_exact(sock, 8))[0]
                if length > 1_000_000:
                    break
                mask = self._recv_exact(sock, 4) if masked else b"\x00" * 4
                payload = bytearray(self._recv_exact(sock, length))
                for i in range(length):
                    payload[i] ^= mask[i % 4]
                if opcode == 0x8:      # close
                    break
                if opcode == 0x9:      # ping → pong
                    with client["lock"]:
                        sock.sendall(ws_frame(bytes(payload), 0xA))
                # texto del cliente (typing etc.) → touch
                if opcode == 0x1:
                    touch()
        except Exception:
            pass
        finally:
            with WS_LOCK:
                if client in WS_CLIENTS:
                    WS_CLIENTS.remove(client)
            presence_broadcast()
        self.close_connection = True

    @staticmethod
    def _recv_exact(sock, n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return buf if buf else b""
            buf += chunk
        return buf

    # ---------- GET ----------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if self.headers.get("Upgrade", "").lower() == "websocket":
            return self._ws_upgrade()
        if path == "/embed.js":
            return self._file(STATIC, "embed.js")
        if path in ("/", "/panel"):
            return self._file(STATIC, "panel.html")
        if path.startswith("/anim/") and ANIM_DIR:
            return self._file(ANIM_DIR, path[6:])
        if not path.startswith("/api/"):
            return self._file(STATIC, path)

        if not self._token_ok():
            return self._json(401, {"error": "token"})

        if path == "/api/boot":
            users = load_users()
            cfg = load_config()
            return self._json(200, {
                "needs_admin": not any(u.get("role") == "admin" for u in users.values()),
                "system_status": system_status(),
                "agent": {"name": cfg["name"], "personality": cfg["personality"],
                          "rest_mode": cfg["rest_mode"], "has_provider": bool(cfg["providers"]),
                          "respond_in_team": cfg["respond_in_team"], "auto_approve": cfg["auto_approve"],
                          "idle_minutes": cfg["idle_minutes"],
                          "providers": [{"provider": p["provider"], "model": p.get("model", "")} for p in cfg["providers"]],
                          "schedules": cfg["schedules"], "webhooks": cfg["webhooks"]},
                "bot": BOT, "host": host_context(),
            })
        if path == "/api/catalog":
            return self._json(200, load_catalog())

        sess = auth_session(self)
        if not sess:
            return self._json(401, {"error": "session"})
        if path == "/api/me":
            return self._json(200, sess)
        if path.startswith("/api/chat/history"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ch = q.get("channel", ["team"])[0]
            if ch.startswith("dm:") and ch != f"dm:{sess['user']}" and sess["role"] != "admin":
                return self._json(403, {"error": "canal privado de otra persona"})
            return self._json(200, {"channel": ch, "messages": chat_history(ch)})
        if path == "/api/approvals":
            with APPROVALS_LOCK:
                return self._json(200, {"items": list(reversed(APPROVALS[-40:]))})
        if path == "/api/users":
            if sess["role"] != "admin":
                return self._json(403, {"error": "solo admin"})
            users = load_users()
            return self._json(200, {"users": [
                {"username": u, "email": v.get("email", ""), "role": v.get("role"),
                 "last_login_ts": v.get("last_login_ts")} for u, v in users.items()]})
        if path == "/api/memory":
            return self._json(200, {"file": MEMORY_FILE, "events": recall(100)})
        self._json(404, {"error": "?"})

    # ---------- POST ----------
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/hook/"):
            return self._hook(path[6:])
        if not self._token_ok():
            return self._json(401, {"error": "token"})
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode() or "{}")

        if path == "/api/setup-admin":
            users = load_users()
            if any(u.get("role") == "admin" for u in users.values()):
                return self._json(409, {"error": "ya hay un guardián"})
            salt = secrets.token_hex(8)
            uname = body["username"]
            users[uname] = {"salt": salt, "hash": _hash_pw(body["password"], salt), "role": "admin",
                            "email": body.get("email", "").strip(), "created_ts": time.time(),
                            "last_login_ts": time.time()}
            save_users(users)
            remember("runtime", "admin-creado", user=uname, email=body.get("email", ""))
            return self._login_ok(uname, "admin")

        if path == "/api/login":
            identifier = body.get("identifier") or body.get("username", "")
            uname, u = find_user_by_identifier(identifier)
            if not u or _hash_pw(body.get("password", ""), u["salt"]) != u["hash"]:
                return self._json(401, {"error": "credenciales"})
            users = load_users()
            users[uname]["last_login_ts"] = time.time()
            save_users(users)
            return self._login_ok(uname, u["role"])

        if path == "/api/forgot-password":
            identifier = body.get("identifier", "").strip()
            uname, u = find_user_by_identifier(identifier)
            if not u or not u.get("email"):
                # no revelamos si el usuario existe; solo si le falta correo (útil en un sistema de 1 persona)
                return self._json(200, {"ok": True, "message":
                    "Si el correo/usuario existe y tiene email registrado, se envió un enlace. "
                    "Si no tienes email en tu cuenta, pide a un admin que use 'Restablecer' en Personas."})
            token = secrets.token_urlsafe(24)
            with RESETS_LOCK:
                RESETS[token] = {"user": uname, "expires": time.time() + 1800}
            reset_url = f"http://localhost:{PORT}/panel?token={TOKEN}&reset={token}"
            sent, detail = send_email(
                u["email"], "Recupera tu acceso a Acuaponsito",
                f"Hola {uname},\n\nUsa este enlace para elegir una nueva contraseña (válido 30 min):\n{reset_url}\n\n"
                f"Si no lo pediste, ignora este mensaje.")
            remember("runtime", "recuperacion-solicitada", user=uname, mail_sent=sent, detail=detail)
            return self._json(200, {"ok": True, "mail_sent": sent,
                "message": "Revisa tu correo." if sent else f"No se pudo enviar el correo ({detail}). "
                                                            "Pide el enlace al administrador desde la bitácora."})

        if path == "/api/reset-password":
            token = body.get("token", "")
            with RESETS_LOCK:
                r = RESETS.get(token)
            if not r or r["expires"] < time.time():
                return self._json(400, {"error": "enlace inválido o vencido"})
            new_pw = body.get("password", "")
            if len(new_pw) < 6:
                return self._json(400, {"error": "la contraseña debe tener al menos 6 caracteres"})
            users = load_users()
            if r["user"] not in users:
                return self._json(404, {"error": "usuario ya no existe"})
            salt = secrets.token_hex(8)
            users[r["user"]]["salt"] = salt
            users[r["user"]]["hash"] = _hash_pw(new_pw, salt)
            save_users(users)
            with RESETS_LOCK:
                RESETS.pop(token, None)
            remember("runtime", "password-restablecido", user=r["user"])
            return self._login_ok(r["user"], users[r["user"]]["role"])

        sess = auth_session(self)
        if not sess:
            return self._json(401, {"error": "session"})
        touch()

        if path == "/api/chat":
            ch = body.get("channel", "team")
            text = body.get("text", "").strip()
            if not text:
                return self._json(400, {"error": "vacío"})
            if ch.startswith("dm:") and ch != f"dm:{sess['user']}":
                return self._json(403, {"error": "canal ajeno"})
            msg = {"id": secrets.token_hex(6), "channel": ch, "from": "user",
                   "user": sess["user"], "text": text, "ts": time.time()}
            chat_append(msg)
            ws_broadcast({"type": "chat", **msg})
            cfg = load_config()
            mention = f"@{cfg['name'].lower()}" in text.lower()
            if ch.startswith("dm:") or cfg["respond_in_team"] == "always" or mention:
                threading.Thread(target=agent_reply, args=(sess["user"], ch, text), daemon=True).start()
            return self._json(202, {"ok": True})

        if path == "/api/provider":
            res = validate_provider(body.get("provider", ""), body.get("api_key", ""))
            if res["valid"]:
                cfg = load_config()
                entry = {"provider": body["provider"], "api_key": body["api_key"],
                         "model": body.get("model") or res["default_model"]}
                cfg["providers"] = [p for p in cfg["providers"] if p["provider"] != body["provider"]]
                cfg["providers"].insert(0, entry)
                save_config(cfg)
                set_bot_state("wake")
                remember("runtime", "proveedor-conectado", provider=body["provider"])
                threading.Thread(target=agent_reply, daemon=True,
                                 args=(sess["user"], f"dm:{sess['user']}",
                                       "Acabas de despertarme por primera vez. Salúdame breve y dime cómo puedes ayudarme aquí.")).start()
            return self._json(200, res)

        if path == "/api/config":
            if sess["role"] != "admin":
                return self._json(403, {"error": "solo admin"})
            cfg = load_config()
            for k in ("name", "personality", "goal", "idle_minutes", "rest_mode",
                      "auto_approve", "respond_in_team", "schedules", "webhooks"):
                if k in body:
                    cfg[k] = body[k]
            save_config(cfg)
            ws_broadcast({"type": "config", "agent": {"name": cfg["name"], "rest_mode": cfg["rest_mode"]}})
            return self._json(200, {"ok": True})

        if path == "/api/users":
            if sess["role"] != "admin":
                return self._json(403, {"error": "solo admin"})
            users = load_users()
            uname = body["username"]
            if body.get("email"):
                _, existing = find_user_by_identifier(body["email"])
                if existing and uname not in users:
                    return self._json(409, {"error": "ese correo ya está en uso por otra cuenta"})
            salt = secrets.token_hex(8)
            users[uname] = {"salt": salt, "hash": _hash_pw(body["password"], salt),
                            "role": body.get("role", "member"), "email": body.get("email", "").strip(),
                            "created_ts": time.time(), "last_login_ts": None}
            save_users(users)
            return self._json(201, {"ok": True, "users": [
                {"username": u, "email": v.get("email", ""), "role": v.get("role")} for u, v in users.items()]})

        if path == "/api/users/reset":
            if sess["role"] != "admin":
                return self._json(403, {"error": "solo admin"})
            users = load_users()
            target = body.get("username", "")
            if target not in users:
                return self._json(404, {"error": "usuario no existe"})
            new_pw = body.get("password", "")
            if len(new_pw) < 6:
                return self._json(400, {"error": "mínimo 6 caracteres"})
            salt = secrets.token_hex(8)
            users[target]["salt"] = salt
            users[target]["hash"] = _hash_pw(new_pw, salt)
            save_users(users)
            remember("runtime", "password-restablecido-por-admin", user=target, by=sess["user"])
            return self._json(200, {"ok": True})

        if path == "/api/approve":
            if sess["role"] != "admin":
                return self._json(403, {"error": "solo admin aprueba"})
            aid = body.get("id")
            if body.get("decision") == "approve":
                threading.Thread(target=run_approval, args=(aid, sess["user"]), daemon=True).start()
            else:
                with APPROVALS_LOCK:
                    for a in APPROVALS:
                        if a["id"] == aid and a["status"] == "pending":
                            a["status"] = "rejected"
                            ws_broadcast({"type": "approval", "item": a})
            return self._json(200, {"ok": True})

        if path == "/api/memory":
            ev = remember(sess["user"], body.get("kind", "nota"), text=body.get("text", ""))
            return self._json(201, ev)

        self._json(404, {"error": "?"})

    def _login_ok(self, user, role):
        sid = secrets.token_urlsafe(20)
        SESSIONS[sid] = {"user": user, "role": role, "since": time.time()}
        remember("runtime", "login", user=user)
        return self._json(200, {"session": sid, "user": user, "role": role})

    def _hook(self, name):
        if not self._token_ok():
            return self._json(401, {"error": "token"})
        cfg = load_config()
        hook = next((h for h in cfg.get("webhooks", []) if h["id"] == name), None)
        if not hook:
            return self._json(404, {"error": "webhook no definido"})
        n = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(n).decode()[:2000]
        threading.Thread(target=agent_reply, daemon=True,
                         args=("webhook", "team", f"[Webhook {hook['name']}] {hook['prompt']}\nPayload: {payload}")).start()
        return self._json(202, {"ok": True})


def main():
    threading.Thread(target=life_loop, daemon=True).start()
    remember("runtime", "arranque", port=PORT)
    server = ThreadingHTTPServer((os.environ.get("ACUA_HOST", "0.0.0.0"), PORT), Handler)
    cfg = load_config()
    print("=" * 64)
    print(f"  🌱 {cfg['name']} Agent Runtime")
    print("=" * 64)
    print(f"  Panel   : http://localhost:{PORT}/panel?token={TOKEN}")
    print(f"  Embed   : <script src=\"http://HOST:{PORT}/embed.js\" data-token=\"{TOKEN}\"></script>")
    print(f"  Datos   : {DATA_DIR}  (config, usuarios, memoria, chats)")
    print("=" * 64, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
