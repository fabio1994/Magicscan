import csv, getpass, hashlib, hmac, io, json, os, re, secrets, sqlite3, sys, threading, time, datetime as dt, pathlib
import collections, html, traceback, urllib.parse, unicodedata
import cv2, numpy as np
from flask import Flask, Response, g, jsonify, redirect, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import magicscan as ps

AUTH = pathlib.Path("magicdata/auth.json")      # vecchio login a utente singolo: viene migrato nell'amministratore
DB = "magicdata/collezione.db"
DDL_UTENTI = (
    "create table if not exists utenti(id integer primary key autoincrement, nome text unique collate nocase,"
    " hash text, admin integer default 0, creato text)",
    "create table if not exists inviti(codice text primary key, creato text, scade text, usato_da integer, nota text)",
)
NOME_OK = re.compile(r"[A-Za-z0-9._-]{3,30}")
if __name__ == "__main__" and "--setpw" in sys.argv:      # python app.py --setpw  (crea o cambia l'AMMINISTRATORE)
    u = input("Nome utente amministratore (3-30 caratteri: lettere, numeri . _ -): ").strip()
    p1 = getpass.getpass("Password (almeno 8 caratteri): ")
    if not NOME_OK.fullmatch(u) or len(p1) < 8 or p1 != getpass.getpass("Ripeti la password: "):
        sys.exit("Dati non validi o password diverse: non e' cambiato nulla.")
    pathlib.Path("magicdata").mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    for ddl in DDL_UTENTI:
        c.execute(ddl)
    adm = c.execute("select id from utenti where admin=1 order by id limit 1").fetchone()
    altro = c.execute("select id from utenti where nome=?", (u,)).fetchone()
    if altro and (not adm or altro[0] != adm[0]):
        sys.exit("Esiste gia' un altro utente con questo nome: non e' cambiato nulla.")
    h = generate_password_hash(p1)
    if adm:
        c.execute("update utenti set nome=?, hash=? where id=?", (u, h, adm[0]))
    else:
        c.execute("insert into utenti(nome,hash,admin,creato) values(?,?,1,?)", (u, h, time.strftime("%Y-%m-%d")))
    c.commit()
    sys.exit("Password salvata. Il login e' attivo: l'amministratore e' " + u + ".")

CTKEYF = pathlib.Path("magicdata/cardtrader.key")
CTMAPF = pathlib.Path("magicdata/cardtrader_blueprints.json")
if __name__ == "__main__" and "--set-cardtrader-key" in sys.argv:
    k = getpass.getpass("Token API CardTrader (non viene mostrato): ").strip()
    if len(k) < 10:
        sys.exit("Token non valido: non e' cambiato nulla.")
    CTKEYF.parent.mkdir(parents=True, exist_ok=True)
    CTKEYF.write_text(k)
    sys.exit("Token CardTrader salvato.")

app = Flask(__name__, static_folder="static")

# ---------- LOGIN ----------
def _key():
    f = pathlib.Path("magicdata/secret.key")
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


app.secret_key = _key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
app.permanent_session_lifetime = dt.timedelta(days=30)
FAIL = {}
LIBERE = {"/login", "/logout", "/registrati", "/static/icon-180.png", "/static/icon-512.png", "/static/icon.svg"}
LOGIN = '<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n<meta name="theme-color" content="#000"><title>Magicscan - Accesso</title><link rel="apple-touch-icon" href="/static/icon-180.png">\n<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;color:#f8f0d5;font:16px Georgia,"Times New Roman",serif;background:radial-gradient(circle at 12% 8%,rgba(123,199,155,.3),transparent 28%),radial-gradient(circle at 88% 90%,rgba(215,173,76,.22),transparent 30%),linear-gradient(145deg,#0b211b,#071712 62%,#123b2d);position:relative;overflow:hidden}body:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.4;background-image:radial-gradient(rgba(236,205,116,.8) 0 1px,transparent 1.8px);background-size:170px 190px}form{position:relative;z-index:1;width:100%;max-width:390px;padding:32px 22px;border-radius:28px;background:linear-gradient(145deg,rgba(30,73,56,.94),rgba(8,29,22,.94));border:1px solid rgba(215,173,76,.42);box-shadow:0 20px 55px rgba(0,0,0,.4),inset 0 1px rgba(255,244,194,.1);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);text-align:center}img{width:88px;height:88px;border-radius:24px;margin-bottom:12px;box-shadow:0 8px 22px rgba(0,0,0,.28)}h1{margin:0 0 18px;color:#f8f0d5;font-size:32px;letter-spacing:.02em;text-shadow:0 2px 14px rgba(0,0,0,.3)}input{width:100%;margin-bottom:12px;background:rgba(5,25,20,.62);border:1px solid rgba(215,173,76,.3);color:#f8f0d5;border-radius:14px;padding:14px;font-size:16px;outline:0}input::placeholder{color:#b9b99f}input:focus{border-color:#d7ad4c;box-shadow:0 0 0 3px rgba(215,173,76,.18)}button{width:100%;border:0;border-radius:14px;padding:14px;font:600 16px Georgia,"Times New Roman",serif;background:linear-gradient(135deg,#e1bd63,#b8892e);color:#17231c;cursor:pointer;box-shadow:0 8px 18px rgba(0,0,0,.24)}.e{color:#f0a596;min-height:22px;margin-bottom:8px;font-size:14px}a{color:#e5bf69}a:hover{color:#f8f0d5}</style></head><body>\n<form method="post"><img src="/static/icon-512.png" alt="Magicscan"><h1>Magicscan</h1><div class="e" role="alert">@@ERR@@</div>\n<input name="u" placeholder="Nome utente" autocomplete="username" autocapitalize="none" autocorrect="off" required>\n<input name="p" type="password" placeholder="Password" autocomplete="current-password" required><button>Accedi</button><p style="margin:16px 0 0;font-size:14px"><a href="/registrati">Ho un codice invito: crea un account</a></p></form></body></html>'


def _hh(h):
    return hashlib.sha256(h.encode()).hexdigest()[:16]


def _ip():
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()


def _bloccato(ip):
    ora = time.time()
    for k in list(FAIL):
        FAIL[k] = [t for t in FAIL[k] if ora - t < 600]
        if not FAIL[k]:
            del FAIL[k]
    return len(FAIL.get(ip, [])) >= 5 or sum(len(v) for v in FAIL.values()) >= 30


def uid():
    """Id dell'utente che sta facendo la richiesta (ogni utente vede solo la propria collezione)."""
    return g.u["id"]


def utente_sessione():
    """Dati dell'utente collegato, o None se non ha fatto l'accesso. Senza utenti registrati l'app e' aperta (utente 1)."""
    if not q("select 1 from utenti limit 1"):
        return {"id": 1, "nome": "", "admin": 1, "hash": ""}
    i = session.get("uid")
    if i:
        r = q("select * from utenti where id=?", (i,))
        if r and session.get("h") == _hh(r[0]["hash"]):
            return r[0]
    return None


# La tab "Vendi" (pubblicazione su CardTrader) e' pronta ma spenta. Per riaccenderla: MAGIC_VENDI=1 in docker-compose.yml.
VENDI_ON = os.environ.get("MAGIC_VENDI", "").strip().lower() in ("1", "true", "si", "yes")


@app.before_request
def vendi_spenta():
    if not VENDI_ON and request.path.startswith("/api/vendi"):
        return jsonify(errore="La funzione Vendi non e' attiva"), 404


@app.before_request
def protezione():
    if request.path in LIBERE:
        return None
    g.u = utente_sessione()
    if g.u:
        return None
    if request.path.startswith(("/api/", "/img/")):
        return jsonify(errore="non autorizzato"), 401
    return redirect("/login")


def pagina(corpo, err=""):
    """Pagina di accesso/registrazione: stessa grafica del login."""
    testa = LOGIN.split('<form method="post">')[0]
    r = Response(testa + '<form method="post"><img src="/static/icon-512.png" alt="Magicscan"><h1>Magicscan</h1><div class="e" role="alert">'
                 + html.escape(err) + "</div>" + corpo + "</form></body></html>", mimetype="text/html")
    r.headers["Cache-Control"] = "no-store"
    return r


@app.route("/login", methods=["GET", "POST"])
def login():
    if not q("select 1 from utenti limit 1"):
        return redirect("/")
    err = ""
    if request.method == "POST":
        ip = _ip()
        if _bloccato(ip):
            err = "Troppi tentativi. Riprova tra 10 minuti."
        else:
            r = q("select * from utenti where nome=?", (request.form.get("u", "").strip(),))
            ok = check_password_hash(r[0]["hash"] if r else generate_password_hash("x"), request.form.get("p", ""))
            if r and ok:
                FAIL.pop(ip, None)
                session.clear()
                session.permanent = True
                session["uid"], session["h"] = r[0]["id"], _hh(r[0]["hash"])
                return redirect("/")
            FAIL.setdefault(ip, []).append(time.time())
            time.sleep(1)
            err = "Nome utente o password errati."
    return Response(LOGIN.replace("@@ERR@@", html.escape(err)), mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.route("/registrati", methods=["GET", "POST"])
def registrati():
    if not q("select 1 from utenti limit 1"):
        return redirect("/")
    err = ""
    f = request.form
    if request.method == "POST":
        ip = _ip()
        nome, p1, cod = f.get("u", "").strip(), f.get("p", ""), re.sub(r"\s", "", f.get("c", "")).upper()
        if _bloccato(ip):
            err = "Troppi tentativi. Riprova tra 10 minuti."
        elif not NOME_OK.fullmatch(nome):
            err = "Nome utente: da 3 a 30 caratteri (lettere, numeri, punto, trattino)."
        elif len(p1) < 8 or p1 != f.get("p2", ""):
            err = "La password deve avere almeno 8 caratteri e coincidere nei due campi."
        else:
            c = db()
            try:
                oggi = time.strftime("%Y-%m-%d")
                if c.execute("update inviti set usato_da=0 where codice=? and usato_da is null and scade>=?", (cod, oggi)).rowcount != 1:
                    c.rollback()
                    FAIL.setdefault(ip, []).append(time.time())
                    time.sleep(1)
                    err = "Codice invito non valido o scaduto."
                else:
                    try:
                        nid = c.execute("insert into utenti(nome,hash,admin,creato) values(?,?,0,?)",
                                        (nome, generate_password_hash(p1), oggi)).lastrowid
                    except sqlite3.IntegrityError:
                        c.rollback()
                        err = "Nome utente gia' in uso: scegline un altro."
                    else:
                        c.execute("update inviti set usato_da=? where codice=?", (nid, cod))
                        c.commit()
                        session.clear()
                        session.permanent = True
                        session["uid"], session["h"] = nid, _hh(c.execute("select hash from utenti where id=?", (nid,)).fetchone()[0])
                        return redirect("/")
            finally:
                c.close()
    corpo = ('<input name="u" placeholder="Scegli un nome utente" autocomplete="username" autocapitalize="none" autocorrect="off" required value="'
             + html.escape(f.get("u", "")) + '">'
             '<input name="p" type="password" placeholder="Password (almeno 8 caratteri)" autocomplete="new-password" required>'
             '<input name="p2" type="password" placeholder="Ripeti la password" autocomplete="new-password" required>'
             '<input name="c" placeholder="Codice invito" autocapitalize="characters" autocorrect="off" required value="'
             + html.escape(f.get("c", "")) + '"><button>Crea account</button>'
             '<p style="margin:14px 0 0;font-size:14px"><a href="/login">Ho gia\' un account</a></p>')
    return pagina(corpo, err)


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


def _solo_admin():
    return bool(g.u and g.u["admin"] and g.u["nome"])


ADMIN_CSS = ("body{margin:0;padding:20px;font:15px Georgia,'Times New Roman',serif;color:#f8f0d5;"
             "background:linear-gradient(145deg,#0b211b,#071712 62%,#123b2d);min-height:100vh}main{max-width:760px;margin:auto}"
             "h1{font-size:28px}h2{margin-top:28px;font-size:18px;color:#e5bf69}"
             "table{width:100%;border-collapse:collapse;background:rgba(34,67,53,.72);border:1px solid rgba(218,181,91,.28);border-radius:12px}"
             "td,th{padding:9px 10px;border-bottom:1px solid rgba(218,181,91,.18);text-align:left}"
             "code{white-space:nowrap;font-size:16px;letter-spacing:1px;background:rgba(215,173,76,.18);padding:2px 6px;border-radius:6px}"
             "button{border:0;border-radius:10px;padding:9px 14px;font-weight:700;background:linear-gradient(135deg,#e1bd63,#b8892e);color:#17231c;cursor:pointer}"
             "button.r{background:#a8564b;color:#fff}a{color:#e5bf69}.m{color:#b9b99f;font-size:13px}")


@app.get("/admin")
def admin():
    if not _solo_admin():
        return redirect("/")
    oggi = time.strftime("%Y-%m-%d")
    ut = q("select u.id, u.nome, u.admin, u.creato, (select coalesce(sum(coalesce(qta,1)),0) from carte c where c.utente=u.id) n from utenti u order by u.id")
    inv = q("select * from inviti order by creato desc, codice limit 60")
    nomi = {u["id"]: u["nome"] for u in ut}
    righe_u = "".join(
        f"<tr><td>{html.escape(u['nome'])}{' (admin)' if u['admin'] else ''}</td><td>{u['creato'] or ''}</td><td>{u['n']} carte</td><td>"
        + ("" if u["admin"] else f'<form method="post" action="/admin/utente/{u["id"]}/elimina" onsubmit="return confirm(\'Eliminare {html.escape(u["nome"])} e tutta la sua collezione?\')">'
           '<button class="r">Elimina</button></form>') + "</td></tr>" for u in ut)
    righe_i = ""
    for i in inv:
        if i["usato_da"] is None:
            st = "scaduto" if i["scade"] < oggi else "da usare"
            az = f'<form method="post" action="/admin/invito/{i["codice"]}/revoca"><button class="r">Revoca</button></form>'
        else:
            st, az = "usato da " + html.escape(nomi.get(i["usato_da"], "utente eliminato")), ""
        righe_i += f"<tr><td><code>{i['codice']}</code></td><td>{i['scade']}</td><td>{st}</td><td>{az}</td></tr>"
    pg = (f'<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>Magicscan - Utenti</title><style>{ADMIN_CSS}</style></head><body><main><p><a href="/">&larr; Torna all\'app</a></p>'
          '<h1>Utenti e inviti</h1><h2>Nuovo codice invito</h2><form method="post" action="/admin/invito"><button>Genera codice (valido 7 giorni, un solo uso)</button></form>'
          '<p class="m">Passa il codice alla persona: va inserito in <b>/registrati</b> insieme al nome utente e alla password che sceglie.</p>'
          f'<h2>Codici</h2><table>{righe_i or "<tr><td>Nessun codice</td></tr>"}</table>'
          f'<h2>Utenti</h2><table>{righe_u}</table></main></body></html>')
    return Response(pg, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.post("/admin/invito")
def admin_invito():
    if not _solo_admin():
        return redirect("/")
    cod = secrets.token_hex(5).upper()
    cod = cod[:5] + "-" + cod[5:]
    scade = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    q("insert into inviti(codice,creato,scade,usato_da,nota) values(?,?,?,null,'')", (cod, time.strftime("%Y-%m-%d"), scade), True)
    return redirect("/admin")


@app.post("/admin/invito/<cod>/revoca")
def admin_revoca(cod):
    if _solo_admin():
        q("delete from inviti where codice=? and usato_da is null", (cod,), True)
    return redirect("/admin")


@app.post("/admin/utente/<int:i>/elimina")
def admin_elimina(i):
    if _solo_admin() and i != g.u["id"] and q("select 1 from utenti where id=? and admin=0", (i,)):
        q("delete from carte where utente=?", (i,), True)
        q("delete from utenti where id=?", (i,), True)
    return redirect("/admin")


M = ps.Matcher()
lock = threading.Lock()
MARK = pathlib.Path("magicdata/ultimo_agg.txt")
LANGS = {"en": "Inglese", "it": "Italiano", "fr": "Francese", "de": "Tedesco", "es": "Spagnolo", "pt": "Portoghese",
         "ja": "Giapponese", "ko": "Coreano", "ru": "Russo", "zhs": "Cinese (semp.)", "zht": "Cinese (trad.)",
         "la": "Latino", "grc": "Greco antico", "he": "Ebraico", "ar": "Arabo", "sa": "Sanscrito", "ph": "Phyrexiano"}


def sid(cid):
    return cid.rsplit("-", 1)[0]


# ---------- CARDTRADER ----------
CT_BASE = "https://api.cardtrader.com/api/v2"
CT_GAME_ID = 1          # Magic: the Gathering su CardTrader
CTINFOF = pathlib.Path("magicdata/cardtrader_blueprint_info.json")    # proprieta' dei blueprint collegati
CTEXPF = pathlib.Path("magicdata/cardtrader_expansions.json")         # facoltativo: {"codice_set_scryfall": id_espansione_cardtrader}
CT_RETRY_SECS = 600     # una carta non trovata viene ricercata al massimo ogni 10 minuti (o subito col pulsante)
CT_CACHE_SECS = 3600
CT_LOG = collections.deque(maxlen=60)
# Condizioni di CardTrader per Magic: Mint, Near Mint, Slightly Played, Moderately Played, Played, Heavily Played, Poor.
# Per ogni condizione dell'app si prova il primo nome ammesso dal blueprint.
CT_COND_NOMI = {"NM": ["Near Mint"], "LP": ["Slightly Played"], "MP": ["Moderately Played"],
                "HP": ["Heavily Played", "Played"], "DMG": ["Poor", "Damaged"]}
CT_COND = {k: v[0] for k, v in CT_COND_NOMI.items()}
CT_COND_ALIAS = {"Near Mint": "NM", "Lightly Played": "LP", "Slightly Played": "LP", "Moderately Played": "MP",
                 "Heavily Played": "HP", "Played": "HP", "Damaged": "DMG", "Poor": "DMG"}
# Lingue: codici dell'app (Scryfall) -> codici CardTrader
CT_LANG = {"ja": "jp", "ko": "kr", "zhs": "zh-CN", "zht": "zh-TW"}

CT_MAP_LOCK = threading.Lock()
CT_RESOLVE_LOCK = threading.Lock()
CT_HTTP_LOCK = threading.Lock()
CT_MKT_LOCK = threading.Lock()
CT_HTTP_LAST = [0.0]
CT_MKT_LAST = [0.0]
CT_STATE = {"running": False, "tot": 0, "fatte": 0, "ok": 0, "mancanti": 0, "ambigui": 0, "errori": 0,
            "errore": "", "fatale": False}
CT_UNRESOLVED = {}      # card_id -> {ts, stato, motivo, candidati}
CT_EXPANSION_CACHE = None
CT_BLUEPRINT_CACHE = {}
CT_PRICE_CACHE = {}     # (blueprint, lingua, condizione) -> (ts, dict)
CT_PRICE_STATE = {"running": False, "tot": 0, "fatte": 0}
CT_PRICE_LOCK = threading.Lock()


def ctl(msg):
    CT_LOG.append(time.strftime("%H:%M:%S ") + str(msg))
    log("CardTrader: " + str(msg))


class CTError(RuntimeError):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def cardtrader_key():
    try:
        return CTKEYF.read_text().strip() or os.environ.get("CARDTRADER_API_TOKEN") or None
    except OSError:
        return os.environ.get("CARDTRADER_API_TOKEN") or None


def _ct_read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _ct_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def cardtrader_map():
    out = {}
    for k, v in _ct_read(CTMAPF).items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def ensure_cardtrader_map():
    if not CTMAPF.exists():
        _ct_write(CTMAPF, {})


def cardtrader_info():
    d = _ct_read(CTINFOF)
    return {"blueprints": d.get("blueprints") or {}, "metodo": d.get("metodo") or {}}


def ct_save_mapping(card_id, blueprint_id, props=None, metodo="auto", overwrite=False):
    with CT_MAP_LOCK:
        mapping = cardtrader_map()
        if card_id in mapping and not overwrite:
            return
        mapping[card_id] = int(blueprint_id)
        _ct_write(CTMAPF, mapping)
        info = cardtrader_info()
        if props is not None:
            info["blueprints"][str(int(blueprint_id))] = {"props": props}
        info["metodo"][card_id] = metodo
        _ct_write(CTINFOF, info)
    CT_UNRESOLVED.pop(card_id, None)


# ---- chiamate HTTP: rispettano i limiti di CardTrader e riportano l'errore vero ----
def ct_request(method, path, params=None, body=None, market=False):
    token = cardtrader_key()
    if not token:
        raise CTError("Token CardTrader non configurato")
    r = None
    for tentativo in range(3):
        lock, last, gap = (CT_MKT_LOCK, CT_MKT_LAST, 1.1) if market else (CT_HTTP_LOCK, CT_HTTP_LAST, 0.1)
        with lock:                       # marketplace: 1 chiamata al secondo; resto: ben sotto 200 ogni 10 s
            time.sleep(max(0, gap - (time.time() - last[0])))
            try:
                r = ps.requests.request(method, CT_BASE + path, params=params, json=body, timeout=90,
                                        headers={"Authorization": "Bearer " + token})
            except Exception as e:
                raise CTError(f"rete: {e.__class__.__name__}") from e
            finally:
                last[0] = time.time()
        if r.status_code == 429 and tentativo < 2:
            time.sleep(3 * (tentativo + 1))
            continue
        break
    if r.status_code == 401:
        raise CTError("Token CardTrader non valido o scaduto (401)", 401)
    if not r.ok:
        dettaglio = ""
        try:
            j = r.json()
            dettaglio = (j.get("extra") or {}).get("message") or j.get("error") or json.dumps(j.get("errors") or j)[:200]
        except Exception:
            dettaglio = r.text[:200]
        raise CTError(f"CardTrader {r.status_code}: {dettaglio}", r.status_code)
    try:
        return r.json()
    except ValueError:
        raise CTError("CardTrader ha risposto con dati non validi", r.status_code)


def cardtrader_get(path, params=None, market=False):
    return ct_request("GET", path, params=params, market=market)


def cardtrader_post(path, payload):
    return ct_request("POST", path, body=payload)


def _ct_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("blueprints", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [v for v in data.values() if isinstance(v, dict)]
    return []


# ---- normalizzazione ----
def _ct_norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9/|]+", " ", text).strip()


def _ct_texts(value):
    if isinstance(value, str):
        return {_ct_norm(value)}
    if isinstance(value, dict):
        out = set()
        for child in value.values():
            out.update(_ct_texts(child))
        return out
    return set()


def _ct_set_code(value):
    return re.sub(r"[^a-z0-9]", "", _ct_norm(value)).lstrip("0")


def _ct_num(value, lasco=False):
    """'004' -> '4'; '4/102' -> '4'; con lasco anche 'BS 4' -> '4'."""
    text = _ct_norm(value).split("/", 1)[0].strip()
    if lasco:
        text = re.sub(r"^[a-z]+\s*(?=\d)", "", text)
    return text.replace(" ", "").lstrip("0") or "0"


def _ct_values(value, keys):
    if isinstance(value, dict):
        out = []
        for key, child in value.items():
            if key in keys or isinstance(child, (dict, list)):
                out.extend(_ct_values(child, keys))
        return out
    if isinstance(value, list):
        out = []
        for child in value:
            out.extend(_ct_values(child, keys))
        return out
    return [value] if value is not None else []


CT_NUM_KEYS = {"number", "local_id", "collector_number", "card_number", "localId"}


def _ct_bp_numbers(blueprint):
    values = _ct_values(blueprint.get("fixed_properties"), CT_NUM_KEYS) + _ct_values(
        {k: v for k, v in blueprint.items() if k != "editable_properties"}, CT_NUM_KEYS)
    values += re.findall(r"(?:^|\|)\s*(\d+)\s*/\s*\d+", str(blueprint.get("version") or ""))
    return values


def _ct_bp_names(blueprint):
    names = set()
    for key in ("name", "title", "name_en", "name_it"):
        names.update(_ct_texts(blueprint.get(key)))
    names.discard("")
    return names


def _ct_props(blueprint):
    out = {}
    for p in blueprint.get("editable_properties") or []:
        if isinstance(p, dict) and p.get("name"):
            out[p["name"]] = p.get("possible_values")
    return out


def _ct_cand(blueprint, expansion):
    nums = [str(v) for v in _ct_values(blueprint.get("fixed_properties"), CT_NUM_KEYS)]
    return {"id": int(blueprint.get("id") or blueprint.get("blueprint_id")), "nome": blueprint.get("name"),
            "version": blueprint.get("version"), "numero": nums[0] if nums else "",
            "espansione": expansion.get("name"), "props": _ct_props(blueprint)}


# ---- indice dei metadati Scryfall (una volta sola, non a ogni carta) ----
CT_META = {"n": -1, "nomi": {}, "set": {}}


def _ct_meta():
    metas = getattr(M, "meta", [])
    if CT_META["n"] != len(metas):
        nomi, sets = collections.defaultdict(set), collections.defaultdict(set)
        for meta in metas:
            cid = meta.get("id", "")
            if meta.get("lang") in ("en", "it"):
                nomi[cid].update(_ct_texts(meta.get("name")))
            sets[cid.rsplit("-", 1)[0]].update(_ct_texts(meta.get("set")))
        CT_META.update(n=len(metas), nomi=nomi, set=sets)
    return CT_META


def _ct_expansions():
    global CT_EXPANSION_CACHE
    if CT_EXPANSION_CACHE is None or time.time() - CT_EXPANSION_CACHE[0] > CT_CACHE_SECS:
        items = [x for x in _ct_items(cardtrader_get("/expansions")) if x.get("game_id") == CT_GAME_ID]
        CT_EXPANSION_CACHE = (time.time(), items)
        ctl(f"espansioni Magic scaricate: {len(items)}")
    return CT_EXPANSION_CACHE[1]


def _ct_blueprints(expansion_id):
    hit = CT_BLUEPRINT_CACHE.get(expansion_id)
    if not hit or time.time() - hit[0] > CT_CACHE_SECS:
        items = _ct_items(cardtrader_get("/blueprints/export", {"expansion_id": expansion_id}))
        CT_BLUEPRINT_CACHE[expansion_id] = hit = (time.time(), items)
        ctl(f"blueprint scaricati per espansione {expansion_id}: {len(items)}")
    return hit[1]


def _ct_expansion_lang_ok(expansion, lang):
    return True      # su CardTrader le espansioni di Magic non sono divise per lingua (la lingua e' una proprieta')


def _ct_contains(a, b):
    """Una stringa contiene l'altra come parole intere ('151' in 'scarlet violet 151', ma 'ex' non in 'next')."""
    return bool(a and b and (f" {a} " in f" {b} " or f" {b} " in f" {a} "))


def _ct_expansion_score(expansion, names, set_code):
    values = set()
    for key in ("name", "title", "name_en", "code", "slug"):
        values.update(_ct_texts(expansion.get(key)))
    score = 0
    if set_code and _ct_set_code(set_code) in {_ct_set_code(v) for v in values}:
        score += 100
    for value in values:
        if any(value == name for name in names):
            score += 80
        elif any(_ct_contains(name, value) for name in names):
            score += 20
    return score


def _ct_overrides():
    """Aggiustamenti manuali: file magicdata/cardtrader_expansions.json, es. {"me05.5": 4679}."""
    out = {}
    for k, v in _ct_read(CTEXPF).items():
        out[str(k)] = {int(x) for x in (v if isinstance(v, list) else [v]) if str(x).isdigit()}
    return out


def _sf_en(card_id):
    """Id Scryfall della stampa inglese: i blueprint CardTrader di Magic portano lo scryfall_id."""
    m = _meta_idx().get((card_id, "en"))
    if m and m.get("sf"):
        return m["sf"]
    d = sf_stampa(card_id)
    return d.get("id") if d else None


def _ct_find(card_id, name, set_name, number, lang):
    """-> (stato, dettaglio). stato: ok | ambiguo | mancante. Solleva CTError se CardTrader non risponde.
    Ordine di fiducia: scryfall_id (certo) -> nome + numero -> solo nome (se unico nell'espansione)."""
    set_id = sid(card_id)
    names = ({_ct_norm(name)} | _ct_meta()["nomi"].get(card_id, set())) - {""}
    set_names = (_ct_meta()["set"].get(set_id, set()) | {_ct_norm(set_name)}) - {""}
    expansions = _ct_expansions()
    forzate = _ct_overrides().get(set_id)
    if forzate:
        cands = [x for x in expansions if x.get("id") in forzate]
    else:
        cands = [x for x in expansions if _ct_norm(x.get("code")) == _ct_norm(set_id)]      # il codice Scryfall coincide con quello CardTrader
        if not cands:
            scored = sorted(((_ct_expansion_score(x, set_names, set_id), x) for x in expansions), key=lambda t: -t[0])
            cands = [x for s_, x in scored if s_ > 0][:3]
    if not cands:
        return "mancante", {"motivo": f"nessuna espansione CardTrader per il set '{set_name}' ({set_id})", "candidati": []}
    sf = None
    visti, per_nome = [], []
    for exp in cands:
        if exp.get("id") is None:
            continue
        visti.append(f"{exp.get('name')} [{exp.get('id')}]")
        blueprints = _ct_blueprints(exp["id"])
        if sf is None:
            sf = _sf_en(card_id) or ""
        if sf:
            hit = [b for b in blueprints if str(b.get("scryfall_id") or "") == sf]
            if len(hit) == 1:
                return "ok", {"id": int(hit[0].get("id") or hit[0].get("blueprint_id")), "metodo": "scryfall", "props": _ct_props(hit[0])}
        stessa = [b for b in blueprints if names & _ct_bp_names(b) and (b.get("id") or b.get("blueprint_id")) is not None]
        if not stessa:
            continue
        per_nome = per_nome or [(b, exp) for b in stessa]
        num = _ct_num(number)
        livelli = (
            ("numero", [b for b in stessa if any(_ct_num(v) == num for v in _ct_bp_numbers(b))]),
            ("numero", [b for b in stessa if any(_ct_num(v, True) == _ct_num(number, True) for v in _ct_bp_numbers(b))]),
            ("nome", stessa),
        )
        for metodo, trovati in livelli:
            ids = {int(b.get("id") or b.get("blueprint_id")) for b in trovati}
            if len(ids) == 1:
                return "ok", {"id": ids.pop(), "metodo": metodo, "props": _ct_props(trovati[0])}
            if len(ids) > 1:
                return "ambiguo", {"motivo": f"{len(ids)} blueprint possibili in '{exp.get('name')}'",
                                   "candidati": [_ct_cand(b, exp) for b in trovati[:8]]}
    motivo = f"controllate {', '.join(visti)}: " + ("nessun blueprint con questo nome" if not per_nome else
                                                       "il nome c'e' ma il numero non corrisponde")
    return "mancante", {"motivo": motivo, "candidati": [_ct_cand(b, e) for b, e in per_nome[:8]]}


def cardtrader_resolve(card_id, name, set_name, number, lang, force=False):
    """Trova e salva il blueprint CardTrader. Ritorna lo stato: ok | ambiguo | mancante | errore | senza_token."""
    if not cardtrader_key():
        return "senza_token"
    if card_id in cardtrader_map():
        return "ok"
    prev = CT_UNRESOLVED.get(card_id)
    if prev and not force and time.time() - prev["ts"] < CT_RETRY_SECS:
        return prev["stato"]
    try:
        stato, det = _ct_find(card_id, name, set_name, number, lang)
    except CTError as e:
        CT_UNRESOLVED[card_id] = {"ts": time.time(), "stato": "errore", "motivo": str(e), "candidati": []}
        CT_STATE["errore"] = str(e)
        if e.status in (401, None):             # token sbagliato o rete assente: inutile continuare
            CT_STATE["fatale"] = True
        ctl(f"errore ricerca blueprint {card_id}: {e}")
        return "errore"
    except Exception:
        CT_UNRESOLVED[card_id] = {"ts": time.time(), "stato": "errore", "motivo": "errore interno", "candidati": []}
        ctl("ERRORE interno ricerca blueprint " + traceback.format_exc()[-400:])
        return "errore"
    if stato == "ok":
        ct_save_mapping(card_id, det["id"], det["props"], det["metodo"])
        if det["metodo"] == "nome":
            ctl(f"{card_id} ({name}) collegata a {det['id']} solo per nome: controlla")
    else:
        CT_UNRESOLVED[card_id] = {"ts": time.time(), "stato": stato, "motivo": det["motivo"], "candidati": det["candidati"],
                                  "nome": name, "set": set_name, "numero": number}
        ctl(f"{stato} {card_id} ({name}, {set_name}, n. {number}): {det['motivo']}")
    return stato


def ct_resolve_start(force=False):
    """Avvia in background il download dei blueprint e il collegamento delle carte. False se e' gia' in corso."""
    with CT_RESOLVE_LOCK:
        if CT_STATE["running"]:
            return False
        CT_STATE.update(running=True, tot=0, fatte=0, ok=0, mancanti=0, ambigui=0, errori=0, errore="", fatale=False)
    threading.Thread(target=_ct_resolve_run, args=(force,), daemon=True).start()
    return True


def _ct_resolve_run(force):
    global CT_EXPANSION_CACHE
    try:
        if force:
            CT_EXPANSION_CACHE = None
            CT_BLUEPRINT_CACHE.clear()
            try:
                _ct_expansions()                # verifica subito token e rete, anche se tutte le carte sono gia' collegate
            except CTError as e:
                CT_STATE.update(errore=str(e), fatale=True)
                ctl(f"errore scaricando le espansioni: {e}")
                return
        ensure_cardtrader_map()
        righe = [r for r in q("select card_id, nome, set_nome, numero, lang, sum(coalesce(qta,1)) n from carte "
                              "group by card_id, lang order by n desc, nome") if r["card_id"]]
        CT_STATE["tot"] = len(righe)
        for r in righe:
            stato = cardtrader_resolve(r["card_id"], r["nome"], r["set_nome"], r["numero"], r["lang"], force)
            CT_STATE["fatte"] += 1
            k = {"ok": "ok", "mancante": "mancanti", "ambiguo": "ambigui", "errore": "errori"}.get(stato)
            if k:
                CT_STATE[k] += 1
            if CT_STATE["fatale"]:
                break
    except Exception:
        CT_STATE["errore"] = "errore interno"
        ctl("ERRORE ricerca blueprint " + traceback.format_exc()[-500:])
    finally:
        with CT_RESOLVE_LOCK:
            CT_STATE["running"] = False


# ---- prezzo consigliato ----
def ct_lang(lang):
    lang = (lang or "en").lower()
    return CT_LANG.get(lang, lang)


def _ct_price_fetch(blueprint_id, lang, cond, fin):
    """Offerta piu' bassa con stessa lingua, condizione e foil. Se non c'e', ripiega e lo dichiara."""
    def offerte(params):
        data = cardtrader_get("/marketplace/products", params, market=True)
        prodotti = data.get(str(blueprint_id), []) if isinstance(data, dict) else (data or [])
        out = []
        for p in prodotti:
            pr = p.get("price") or {}
            if p.get("on_vacation") or p.get("graded") or pr.get("cents") is None:
                continue
            out.append((pr["cents"] / 100, pr.get("currency") or "EUR", (p.get("properties_hash") or {}).get("condition")))
        return out

    nomi = set(CT_COND_NOMI.get(cond, [cond]))
    foil = "false" if (fin or "S") == "S" else "true"
    base = "stessa lingua, condizione e finitura"
    lista = offerte({"blueprint_id": blueprint_id, "language": ct_lang(lang), "foil": foil})
    if not lista:
        lista, base = offerte({"blueprint_id": blueprint_id, "foil": foil}), "qualsiasi lingua"
    esatte = [o for o in lista if o[2] in nomi]
    if esatte:
        scelte = esatte
    else:
        scelte, base = lista, base.replace("stessa lingua, condizione e finitura", "stessa lingua e finitura") + ", qualsiasi condizione"
    if not scelte:
        return {"prezzo": None, "motivo": "nessuna offerta su CardTrader"}
    valuta = collections.Counter(o[1] for o in scelte).most_common(1)[0][0]
    prezzi = [o[0] for o in scelte if o[1] == valuta]
    return {"prezzo": min(prezzi), "valuta": valuta, "offerte": len(prezzi), "base": base}


def ct_price_get(blueprint_id, lang, cond, fin="S"):
    """Dalla cache (10 minuti); gli errori restano in cache solo 1 minuto."""
    hit = CT_PRICE_CACHE.get((int(blueprint_id), ct_lang(lang), cond, fin or "S"))
    if hit and time.time() - hit[0] < (60 if hit[1].get("errore") else 600):
        return hit[1]
    return None


def ct_price_work(chiavi):
    try:
        for key in chiavi:
            if ct_price_get(*key) is None:
                try:
                    val = _ct_price_fetch(*key)
                except CTError as e:
                    val = {"prezzo": None, "errore": str(e)}
                    ctl(f"prezzo {key[0]}: {e}")
                CT_PRICE_CACHE[(key[0], ct_lang(key[1]), key[2], key[3] or "S")] = (time.time(), val)
            CT_PRICE_STATE["fatte"] += 1
    finally:
        with CT_PRICE_LOCK:
            CT_PRICE_STATE["running"] = False


def ct_price_start(chiavi):
    chiavi = list(dict.fromkeys(chiavi))
    with CT_PRICE_LOCK:
        if not chiavi or CT_PRICE_STATE["running"]:
            return
        CT_PRICE_STATE.update(running=True, tot=len(chiavi), fatte=0)
    threading.Thread(target=ct_price_work, args=(chiavi,), daemon=True).start()


# ---- pubblicazione ----
def ct_properties(blueprint_id, lang, cond, fin):
    """Proprieta' da inviare a CardTrader (condizione, lingua e foil stanno in 'properties', non al primo livello)."""
    props = (cardtrader_info()["blueprints"].get(str(blueprint_id)) or {}).get("props")
    ammessi = (props or {}).get("condition")
    nomi = CT_COND_NOMI[cond]
    scelto = next((n for n in nomi if not ammessi or n in ammessi), None)
    if not scelto:
        raise CTError(f"Condizione '{nomi[0]}' non ammessa per questo blueprint (ammesse: {', '.join(ammessi)})")
    out = {"condition": scelto}
    lang_ct = ct_lang(lang)
    lang_name = next((n for n in (props or {}) if n.endswith("_language")), "mtg_language")
    ammesse = (props or {}).get(lang_name)
    if ammesse and lang_ct not in ammesse:
        raise CTError(f"Lingua '{lang_ct}' non disponibile per questo blueprint (disponibili: {', '.join(ammesse)})")
    out[lang_name] = lang_ct
    foil = next((n for n in (props or {}) if n.endswith("_foil")), None)
    etched = next((n for n in (props or {}) if "etched" in n.lower()), None)
    if fin == "R":
        if not etched:
            raise CTError("CardTrader non distingue le foil 'etched' per questo blueprint: pubblicala a mano dal sito.")
        out[etched] = True
    elif fin == "H":
        if foil or props is None:
            out[foil or "mtg_foil"] = True      # senza proprieta' note si tenta con il nome standard (strict: se e' sbagliato, CardTrader rifiuta)
    elif foil:
        out[foil] = False
    return out


def ct_already_listed(blueprint_id, props):
    """Copie gia' in vendita sul tuo account con le stesse proprieta' (evita di sommare ai tuoi annunci)."""
    prodotti = cardtrader_get("/products/export", {"blueprint_id": blueprint_id})
    totale = 0
    for p in prodotti if isinstance(prodotti, list) else []:
        ph = p.get("properties_hash") or {}
        if all(ph.get(k) == v for k, v in props.items() if k in ph):
            totale += int(p.get("bundled_quantity") or p.get("quantity") or 0)
    return totale


SETS = {}


def costruisci_sets():
    global SETS
    d = {}
    for m in M.meta:
        s = d.setdefault(sid(m["id"]), {"id": sid(m["id"]), "names": {}, "langs": set()})
        s["langs"].add(m["lang"])
        s["names"][m["lang"]] = m["set"]
        s.setdefault("n", {})
        s["n"][m["lang"]] = s["n"].get(m["lang"], 0) + 1
    SETS = d


costruisci_sets()


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=WAL")      # niente fsync a ogni scrittura: sul disco del NAS fa una grossa differenza
    c.execute("pragma synchronous=NORMAL")
    c.execute("create table if not exists carte(id integer primary key autoincrement, ts text, card_id text,"
              " nome text, set_nome text, numero text, lang text, valore real, valuta text, stato text)")
    cols = {r[1] for r in c.execute("pragma table_info(carte)")}
    for col, t in (("rarita", "text"), ("utente", "integer default 1"), ("qta", "integer default 1"), ("condiz", "text default 'NM'"), ("fin", "text default ''")):
        if col not in cols:
            try:
                c.execute(f"alter table carte add column {col} {t}")
            except sqlite3.OperationalError:      # un altro thread l'ha appena aggiunta (primo avvio con database nuovo)
                pass
    for ddl in DDL_UTENTI:
        c.execute(ddl)
    c.execute("create index if not exists carte_utente on carte(utente, card_id)")
    c.execute("create table if not exists prezzi(card_id text, giorno text, valore real, valuta text,"
              " primary key(card_id, giorno))")
    c.execute("create table if not exists jlink(card_id text primary key, jid text, ts text)")
    c.execute("create table if not exists jprezzi(card_id text, cond text, giorno text, valore real, primary key(card_id, cond, giorno))")
    c.execute("create table if not exists jp2(card_id text, fin text, cond text, giorno text, valore real, primary key(card_id, fin, cond, giorno))")
    c.execute("create table if not exists jfin(card_id text, fin text, primary key(card_id, fin))")
    c.execute("create table if not exists setinfo(sid text, lang text, nome text, logo text, totale integer, primary key(sid, lang))")
    c.execute("create table if not exists correzioni(id integer primary key autoincrement, ts text, proposta text, scelta text,"
              " lang text, esatta integer, pos integer, stato text, punti integer)")
    return c


def migra_utenti():
    """Se c'era il vecchio login a utente singolo (auth.json) diventa l'amministratore: le carte esistenti sono le sue (utente 1)."""
    if q("select 1 from utenti limit 1") or not AUTH.exists():
        return
    try:
        a = json.loads(AUTH.read_text())
        q("insert into utenti(id,nome,hash,admin,creato) values(1,?,?,1,?)", (a["user"], a["hash"], time.strftime("%Y-%m-%d")), True)
        AUTH.rename(AUTH.with_name("auth.json.migrato"))
    except Exception as e:
        print("migrazione login:", e, flush=True)


def q(sql, a=(), w=False):
    c = db()
    try:
        cur = c.execute(sql, a)
        if w:
            c.commit()
            return cur.lastrowid
        return [dict(x) for x in cur.fetchall()]
    finally:
        c.close()


def q_molti(sql, rows):
    """Molte righe in una sola transazione (prima: una scrittura e un commit per riga)."""
    if not rows:
        return
    c = db()
    try:
        c.executemany(sql, rows)
        c.commit()
    finally:
        c.close()


migra_utenti()


def log(msg):
    s = time.strftime("%H:%M:%S ") + str(msg)
    JTLOG.append(s)
    print("magicscan:", s, flush=True)


JTLOG = collections.deque(maxlen=80)
FIN = ("S", "H", "R")      # Non-foil, Foil, Etched
FIN_PREZ = {"S": "", "H": "_foil", "R": "_etched"}      # suffisso dei prezzi Scryfall: usd, usd_foil, usd_etched
SF_LOCK = threading.Lock()
SF_T = [0.0]


def sf_get(path, params=None, body=None):
    """Chiamata a Scryfall (max ~8 al secondo, intestazioni obbligatorie). None se non esiste o in caso di errore."""
    r = None
    for tentativo in range(2):
        with SF_LOCK:
            time.sleep(max(0, 0.125 - (time.time() - SF_T[0])))
            try:
                r = ps.requests.request("POST" if body is not None else "GET", ps.BASE + path, params=params, json=body,
                                        headers=ps.HEADERS, timeout=30)
            except Exception as e:
                log(f"Scryfall: errore di rete ({e.__class__.__name__})")
                return None
            finally:
                SF_T[0] = time.time()
        if r.status_code == 429 and tentativo == 0:
            time.sleep(5)
            continue
        break
    if r.status_code == 404:
        return None
    if not r.ok:
        log(f"Scryfall {r.status_code} su {path}: {r.text[:150]}")
        return None
    return r.json()


META_IDX = {"n": -1, "d": {}}


def _meta_idx():
    if META_IDX["n"] != len(M.meta):
        META_IDX.update(n=len(M.meta), d={(m["id"], m["lang"]): m for m in M.meta})
    return META_IDX["d"]


def numero_di(cid, lang="en"):
    idx = _meta_idx()
    m = idx.get((cid, lang)) or idx.get((cid, "en")) or next((x for x in M.meta if x["id"] == cid), None)
    if m:
        return m["number"]
    r = q("select numero from carte where card_id=? limit 1", (cid,))
    return r[0]["numero"] if r else None


def sf_stampa(cid, lang="en"):
    """Scheda Scryfall INGLESE della stampa (prezzi e rarita' si leggono da li')."""
    num = numero_di(cid, lang)
    if num is None:
        return None
    d = sf_get(f"/cards/{urllib.parse.quote(sid(cid), safe='')}/{urllib.parse.quote(str(num), safe='')}/en")
    if d is None:      # carta stampata solo in un'altra lingua: la scheda si prende dal suo id Scryfall
        m = next((x for x in M.meta if x["id"] == cid and x.get("sf")), None)
        d = sf_get(f"/cards/{m['sf']}") if m else None
    return d


def prezzo_di(p):
    """(valore, valuta) dai prezzi Scryfall: Cardmarket (euro) se c'e', altrimenti TCGplayer (dollari)."""
    for base, valuta in (("eur", "EUR"), ("usd", "USD")):
        for suf in ("", "_foil", "_etched"):
            if (p or {}).get(base + suf):
                return float(p[base + suf]), valuta
    return None, ""


def dettagli(cid, lang="en"):
    d = sf_stampa(cid, lang) or {}
    p = d.get("prices") or {}
    val, valuta = prezzo_di(p)
    return {"rarita": (d.get("rarity") or "").capitalize() or "N/D", "valore": val, "valuta": valuta,
            "cm": {"trend": float(p["eur"])} if p.get("eur") else {}, "prezzi": p}


def punto(cid, val, valuta, cm=None):
    if val is not None:
        q("insert or replace into prezzi values(?,?,?,?)", (cid, dt.date.today().isoformat(), val, valuta), True)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def combos_di(cid):
    return [(r["c"], r["f"]) for r in q("select distinct coalesce(condiz,'NM') c, coalesce(fin,'') f from carte where card_id=?", (cid,))]


def sf_salva(cid, prezzi):
    """Salva il prezzo di oggi (USD) per ogni condizione e finitura possedute. Scryfall ha un solo prezzo per finitura (Near Mint):
    lo stesso valore vale per tutte le condizioni. Restituisce quanti prezzi ha salvato."""
    oggi, righe = dt.date.today().isoformat(), []
    for cd, fin in combos_di(cid):
        v = (prezzi or {}).get("usd" + FIN_PREZ.get(fin or "S", ""))
        if v:
            righe.append((cid, fin, cd, oggi, float(v)))
    q_molti("insert or replace into jp2 values(?,?,?,?,?)", righe)
    return len(righe)


def prezzi_carta(cid, lang):
    try:
        d = sf_stampa(cid, lang)
        if not d:
            log(f"{cid}: Scryfall non ha la carta")
            return
        log(f"{cid}: salvati {sf_salva(cid, d.get('prices'))} prezzi")
    except Exception:
        log("ERRORE " + traceback.format_exc()[-400:])


def aggiorna():
    """Aggiornamento giornaliero: carte raggruppate a 75 per richiesta (/cards/collection di Scryfall)."""
    righe = q("select card_id, min(lang) lang from carte group by card_id")
    for i in range(0, len(righe), 75):
        grp = [(r, {"set": sid(r["card_id"]), "collector_number": str(numero_di(r["card_id"], r["lang"]))}) for r in righe[i:i + 75]]
        d = sf_get("/cards/collection", body={"identifiers": [g[1] for g in grp]})
        if not d:
            continue
        by = {(c.get("set"), str(c.get("collector_number"))): c for c in d.get("data", [])}
        for r, ident in grp:
            c = by.get((ident["set"], ident["collector_number"]))
            if not c:
                log(f"{r['card_id']}: assente nella risposta di Scryfall")
                continue
            val, valuta = prezzo_di(c.get("prices"))
            rar = (c.get("rarity") or "").capitalize() or "N/D"
            if val is not None:
                punto(r["card_id"], val, valuta)
            q("update carte set valore=coalesce(?,valore), valuta=case when ? is null then valuta else ? end, rarita=? where card_id=?",
              (val, val, valuta, rar, r["card_id"]), True)
            sf_salva(r["card_id"], c.get("prices"))
    MARK.write_text(dt.date.today().isoformat())


BK = pathlib.Path("magicdata/backup")


def backup(force=False):
    """Copia coerente del database in magicdata/backup (una al giorno, ultime 14)."""
    BK.mkdir(parents=True, exist_ok=True)
    f = BK / f"collezione-{dt.date.today().isoformat()}.db"
    if f.exists():
        if not force:
            return
        f.unlink()
    s, d = sqlite3.connect(DB), sqlite3.connect(f)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    for old in sorted(BK.glob("collezione-*.db"))[:-14]:
        old.unlink()


def _bk():
    try:
        backup()
    except Exception as e:
        print("backup:", e)


def ciclo():
    while True:
        try:
            _bk()
            sets_mancanti()
            oggi = dt.date.today().isoformat()
            vecchio = not MARK.exists() or MARK.read_text().strip() != oggi
            manca_rar = q("select 1 from carte where rarita is null limit 1")
            if (vecchio and q("select 1 from carte limit 1")) or manca_rar:
                aggiorna()
        except Exception as e:
            print("aggiornamento prezzi:", e)
        time.sleep(3600)


threading.Thread(target=ciclo, daemon=True).start()


MARK_IDX = pathlib.Path("magicdata/ultimo_indice.txt")
INFO = {"nuove": 0, "in_corso": False}


def aggiorna_carte():
    if INFO["in_corso"]:
        return
    INFO["in_corso"] = True
    try:
        tot = 0
        for lang in sorted({m["lang"] for m in M.meta}):
            try:
                tot += ps.aggiorna_indice(M, lang, lock)
            except Exception as e:
                print("aggiornamento carte", lang, e)
        if tot:
            with lock:
                M.carica()
            costruisci_sets()
        try:
            aggiorna_noimg()
        except Exception as e:
            print("carte senza immagine:", e)
        INFO["nuove"] = tot
        MARK_IDX.write_text(dt.date.today().isoformat())
    finally:
        INFO["in_corso"] = False


def ciclo_carte():
    while True:
        try:
            if not MARK_IDX.exists():
                MARK_IDX.write_text(dt.date.today().isoformat())    # indice appena creato: prima verifica tra 7 giorni
            elif (dt.date.today() - dt.date.fromisoformat(MARK_IDX.read_text().strip())).days >= 7:
                aggiorna_carte()
        except Exception as e:
            print("ciclo carte:", e)
        time.sleep(6 * 3600)


threading.Thread(target=ciclo_carte, daemon=True).start()


@app.post("/api/aggiorna-carte")
def aggiorna_carte_ora():
    threading.Thread(target=aggiorna_carte, daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/stato")
def stato_info():
    rd = lambda f: f.read_text().strip() if f.exists() else ""
    bk = sorted(BK.glob("collezione-*.db"))
    c = q("select count(*) n, coalesce(sum(esatta),0) e from correzioni")[0]
    return jsonify(carte=rd(MARK_IDX), prezzi=rd(MARK), nuove=INFO["nuove"], in_corso=INFO["in_corso"], totale=len(M.meta),
                   backup=bk[-1].stem[-10:] if bk else "", ric_tot=c["n"], ric_ok=c["e"], versione="magic-1", vendi=VENDI_ON, utente=g.u["nome"], admin=_solo_admin())


SETIMG = pathlib.Path("magicdata/setimg")
SET_TENT = {}
SET_LOCK = threading.Lock()
SETERR = collections.deque(maxlen=20)


def _set_file(s, lang):
    return SETIMG / (re.sub(r"[^A-Za-z0-9._+-]", "_", str(s)) + ".svg")      # il simbolo del set e' lo stesso in ogni lingua


def meta_set(s, lang):
    """Nome, numero di carte e simbolo del set da Scryfall. Il simbolo (SVG) viene scaricato in locale."""
    try:
        r = q("select totale, logo from setinfo where sid=? and lang=?", (s, lang))
        f = _set_file(s, lang)
        if r and r[0]["totale"] is not None and (f.exists() or r[0]["logo"] == "-2"):
            return
        if time.time() - SET_TENT.get((s, lang), 0) < 120:      # non insiste piu' di una volta ogni 2 minuti
            return
        SET_TENT[(s, lang)] = time.time()
        d = sf_get("/sets/" + urllib.parse.quote(s, safe=""))
        if not d:
            SETERR.append(f"{lang}/{s}: Scryfall non ha risposto")
            return
        url = (r[0]["logo"] if r else "") or "locale"
        if not f.exists():
            url = ""
            if d.get("icon_svg_uri"):
                x = ps.requests.get(d["icon_svg_uri"], headers=ps.HEADERS, timeout=30)
                if x.ok and len(x.content) > 100:
                    SETIMG.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(x.content)
                    url = d["icon_svg_uri"]
        q("insert or replace into setinfo values(?,?,?,?,?)", (s, lang, d.get("name"), url or "-2", d.get("card_count")), True)
    except Exception as e:
        SETERR.append(f"{lang}/{s}: {e.__class__.__name__}: {e}")
        print("meta_set", s, lang, e)


def sets_mancanti():
    """Riprova le informazioni dei set in collezione che mancano (totale o immagine)."""
    for r in q("select distinct card_id, lang from carte"):
        meta_set(sid(r["card_id"]), r["lang"])


@app.get("/setimg/<lang>/<s>")
def setimg(lang, s):
    f = _set_file(s, lang)
    if not f.exists():
        return Response(status=404)
    return send_file(f.resolve(), max_age=86400)


@app.get("/api/set")
def set_list():
    g = {}
    for r in q("select card_id, lang, set_nome, qta, numero from carte where utente=?", (uid(),)):
        k = (sid(r["card_id"]), r["lang"])
        e = g.setdefault(k, {"nome": r["set_nome"], "ids": set(), "copie": 0, "prima": None})
        e["ids"].add(r["card_id"])
        e["copie"] += r["qta"] or 1
        chiave = (len(str(r["numero"] or "")), str(r["numero"] or ""))
        if e["prima"] is None or chiave < e["prima"][0]:
            e["prima"] = (chiave, r["card_id"])
    info = {(x["sid"], x["lang"]): x for x in q("select * from setinfo")}
    conta = collections.Counter((sid(m["id"]), m["lang"]) for m in M.meta)
    conta.update((sid(m["id"]), m["lang"]) for m in getattr(M, "noimg", []))
    out = []
    for k, e in g.items():
        i = info.get(k, {})
        tot, approx = i.get("totale"), False
        if tot is None and conta.get(k):          # totale ufficiale non ancora scaricato: si usa l'elenco carte del NAS
            tot, approx = conta[k], True
        out.append({"sid": k[0], "lang": k[1], "nome": i.get("nome") or e["nome"], "possedute": len(e["ids"]), "totale": tot,
                    "approx": approx, "copie": e["copie"],
                    "logo": f"/setimg/{k[1]}/{k[0]}" if _set_file(k[0], k[1]).exists() else "",
                    "img": f"/img/{k[1]}/{e['prima'][1]}" if e["prima"] else ""})      # senza logo: una carta posseduta del set
    manca = [k for k in g if info.get(k, {}).get("totale") is None or (not _set_file(*k).exists() and info.get(k, {}).get("logo") != "-2")]
    if manca and SET_LOCK.acquire(blocking=False):
        def lavora():
            try:
                for k in manca:
                    meta_set(*k)
            finally:
                SET_LOCK.release()
        threading.Thread(target=lavora, daemon=True).start()
    return jsonify(sorted(out, key=lambda x: (x["nome"] or "").lower()))


@app.get("/api/mancanti")
def mancanti_list():
    """Restituisce le carte mancanti dei soli set gia' presenti in collezione."""
    possedute = collections.defaultdict(set)
    for r in q("select card_id, lang from carte where utente=?", (uid(),)):
        possedute[(sid(r["card_id"]), r["lang"])].add(r["card_id"])

    info = {(x["sid"], x["lang"]): x for x in q("select * from setinfo")}
    catalogo = collections.defaultdict(dict)
    for m in list(M.meta) + list(getattr(M, "noimg", [])):
        k = (sid(m["id"]), m["lang"])
        if k in possedute:
            catalogo[k].setdefault(m["id"], m)

    out = []
    for k, owned in possedute.items():
        cards = [m for cid, m in catalogo[k].items() if cid not in owned]
        if not cards:
            continue
        i = info.get(k, {})
        cards.sort(key=lambda m: (len(str(m.get("number") or "")), str(m.get("number") or "")))
        out.append({
            "sid": k[0],
            "lang": k[1],
            "nome": i.get("nome") or cards[0].get("set") or k[0],
            "possedute": len(owned),
            "totale": len(owned) + len(catalogo[k]),
            "mancanti": len(cards),
            "logo": f"/setimg/{k[1]}/{k[0]}" if _set_file(k[0], k[1]).exists() else "",
            "cards": [{
                "card_id": m["id"],
                "nome": m.get("name") or m["id"],
                "set": m.get("set") or i.get("nome") or k[0],
                "numero": m.get("number") or "",
                "lang": m["lang"],
                "rarita": m.get("rarity") or "N/D",
            } for m in cards],
        })
    return jsonify(sorted(out, key=lambda x: (x["nome"] or "").lower()))


def carica_noimg():
    M.noimg = []      # Scryfall ha un'immagine per (quasi) ogni carta: niente elenco "senza immagine"


def aggiorna_noimg():
    carica_noimg()


carica_noimg()


def _primo_noimg():
    """Al primo avvio genera da solo l'elenco delle carte senza immagine (poi si aggiorna con il resto delle carte)."""
    time.sleep(90)
    try:
        if not list(ps.DATA.glob("noimg_*.json")):
            aggiorna_noimg()
    except Exception as e:
        print("elenco carte senza immagine:", e)


threading.Thread(target=_primo_noimg, daemon=True).start()


@app.post("/api/impara")
def impara():
    """Usa la foto appena scattata come immagine di riferimento di una carta che Scryfall ha senza immagine."""
    cid, lang = request.form.get("card_id", ""), request.form.get("lang", "")
    m = next((x for x in getattr(M, "noimg", []) if x["id"] == cid and x["lang"] == lang), None)
    if not m:      # carta salvata in una lingua in cui Scryfall non la elenca: i dati arrivano dall'app
        nome = request.form.get("nome", "")
        if not (cid and lang and nome):
            return jsonify(errore="dati della carta mancanti"), 400
        if any(x["id"] == cid and x["lang"] == lang for x in M.meta):
            return jsonify(errore="la carta e' gia' nell'indice di questa lingua"), 409
        m = {"id": cid, "name": nome, "number": request.form.get("numero", ""), "set": request.form.get("set", ""), "lang": lang}
    ims = imgs_in()
    if not ims:
        return jsonify(errore="immagine non valida"), 400
    qd = ps.trova_carta(ims[0], SFONDO.get(uid()))
    if qd is None:
        return jsonify(errore="carta non rilevata nella foto: riprova con la carta ferma su uno sfondo chiaro e uniforme (i bordi neri delle carte Magic si confondono con uno sfondo scuro)"), 422
    card = ps.raddrizza(ims[0], qd)
    from PIL import Image
    p = ps.percorso(m)
    p.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(p), card)
    with lock:
        v = M.model.encode([Image.fromarray(cv2.cvtColor(ps.riduci_riflessi(card), cv2.COLOR_BGR2RGB))], normalize_embeddings=True, convert_to_numpy=True)
    f_emb, f_meta = ps.file_indice(lang)
    fe, fm = ps.DATA / f_emb, ps.DATA / f_meta
    meta = json.loads(fm.read_text(encoding="utf-8")) if fm.exists() else []
    E = np.load(fe) if fe.exists() else np.zeros((0, v.shape[1]), v.dtype)
    meta.append({"id": m["id"], "name": m["name"], "number": m["number"], "set": m["set"], "lang": lang})
    with open(str(fe) + ".tmp", "wb") as fh:
        np.save(fh, np.vstack([E, v]))
    pathlib.Path(str(fm) + ".tmp").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(str(fe) + ".tmp", fe)
    os.replace(str(fm) + ".tmp", fm)
    with lock:
        M.carica()
    costruisci_sets()
    carica_noimg()
    M.noimg = [x for x in M.noimg if not (x["id"] == cid and x["lang"] == lang)]
    return jsonify(ok=True)


COND = ("NM", "LP", "MP", "HP", "DMG")


def _sposta(i, cond=None, fin=None):
    """Sposta UNA copia in un'altra condizione e/o finitura (unendola a una riga uguale, se esiste)."""
    r = q("select * from carte where id=? and utente=?", (i, uid()))
    if not r:
        return False
    r = r[0]
    c0, f0 = (r.get("condiz") or "NM"), (r.get("fin") or "")
    c1, f1 = (cond or c0), (f0 if fin is None else fin)
    if (c1, f1) == (c0, f0):
        return True
    dest = q("select id from carte where card_id=? and lang=? and coalesce(condiz,'NM')=? and coalesce(fin,'')=? and id!=? and utente=?",
             (r["card_id"], r["lang"], c1, f1, i, r["utente"]))
    if (r.get("qta") or 1) > 1:
        q("update carte set qta=qta-1 where id=?", (i,), True)
        if dest:
            q("update carte set qta=coalesce(qta,1)+1 where id=?", (dest[0]["id"],), True)
        else:
            q("insert into carte(ts,card_id,nome,set_nome,numero,lang,valore,valuta,stato,rarita,qta,condiz,fin,utente) "
              "select ts,card_id,nome,set_nome,numero,lang,valore,valuta,stato,rarita,1,?,?,utente from carte where id=?", (c1, f1, i), True)
    elif dest:
        q("update carte set qta=coalesce(qta,1)+1 where id=?", (dest[0]["id"],), True)
        q("delete from carte where id=?", (i,), True)
    else:
        q("update carte set condiz=?, fin=? where id=?", (c1, f1, i), True)
    threading.Thread(target=prezzi_carta, args=(r["card_id"], r["lang"]), daemon=True).start()
    return True


@app.post("/api/condizione/<int:i>")
def condizione(i):
    c = (request.get_json() or {}).get("c")
    if c not in COND or not _sposta(i, cond=c):
        return jsonify(errore="richiesta non valida"), 400
    return jsonify(ok=True)


@app.post("/api/finitura/<int:i>")
def finitura(i):
    f = (request.get_json() or {}).get("f")
    if f not in FIN or not _sposta(i, fin=f):
        return jsonify(errore="richiesta non valida"), 400
    return jsonify(ok=True)


@app.get("/api/correzioni")
def correzioni():
    t = q("select count(*) n, coalesce(sum(esatta),0) e from correzioni")[0]
    err = q("select proposta, scelta, count(*) n from correzioni where esatta=0 group by proposta, scelta order by n desc limit 20")
    return jsonify(totale=t["n"], esatte=t["e"], errori=err)


@app.post("/api/backup")
def backup_ora():
    backup(True)
    return jsonify(ok=True)


def imgs_in():
    out = []
    for f in request.files.getlist("foto")[:3]:
        im = cv2.imdecode(np.frombuffer(f.read(), np.uint8), cv2.IMREAD_COLOR)
        if im is not None:
            s = 1280 / max(im.shape[:2])
            out.append(cv2.resize(im, None, fx=s, fy=s) if s < 1 else im)
    return out


def fondi(tutti):
    """Unisce i risultati di piu' fotogrammi: medie di punti SIFT e similarita', piu' accordo sul primo posto."""
    n = len(tutti)
    acc = {}
    for top in tutti:
        for r in top:
            a = acc.setdefault(r["m"]["id"], {"m": r["m"], "inl": 0.0, "sim": 0.0, "primo": 0})
            a["inl"] += r["inl"] / n
            a["sim"] += r["sim"] / n
        acc[top[0]["m"]["id"]]["primo"] += 1
    v = list(acc.values())
    v.sort(key=(lambda a: (a["inl"], a["sim"])) if max(a["inl"] for a in v) >= 10 else (lambda a: a["sim"]), reverse=True)
    st = stato_di(v)
    if n > 1 and v[0]["primo"] * 2 <= n:
        st = "verifica"
    return v[:6], st


def stato_di(top):
    b = top[0]
    s = top[1] if len(top) > 1 else {"inl": 0, "sim": 0}
    if b["inl"] >= 15 and b["inl"] >= 1.5 * max(s["inl"], 1):
        return "ok"
    if b["inl"] < 10 and b["sim"] >= ps.SOGLIA_SCORE and b["sim"] - s["sim"] >= ps.SOGLIA_MARGINE:
        return "ok"
    return "verifica"


def cand(m, inl=0, sim=0):
    return {"card_id": m["id"], "nome": m["name"], "set": m["set"], "numero": m["number"], "fins": m.get("fins") or "S",
            "lang": m["lang"], "punti": int(round(inl)), "sim": round(float(sim), 3)}


def img_in():
    f = request.files.get("foto")
    im = cv2.imdecode(np.frombuffer(f.read(), np.uint8), cv2.IMREAD_COLOR) if f else None
    if im is None:
        return None
    s = 1280 / max(im.shape[:2])
    return cv2.resize(im, None, fx=s, fy=s) if s < 1 else im


@app.get("/")
def home():
    return send_from_directory("static", "index.html")


@app.get("/img/<lang>/<cid>")
def img(lang, cid):
    for l in dict.fromkeys([secure_filename(lang), "en", "it", "fr", "de", "es"]):      # se manca nella lingua, si mostra la stessa carta di un'altra lingua
        p = ps.percorso({"id": secure_filename(cid), "lang": l})
        if p.exists():
            return send_file(p, max_age=86400 if l == secure_filename(lang) else 300)
    import html
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 250 350"><rect x="2" y="2" width="246" height="346" rx="16" fill="#1d1d22" stroke="#58585e" stroke-width="3"/>'
           '<text x="125" y="165" fill="#a0a0a8" font-family="sans-serif" font-size="18" text-anchor="middle">Senza immagine</text>'
           f'<text x="125" y="195" fill="#76767c" font-family="sans-serif" font-size="14" text-anchor="middle">{html.escape(secure_filename(cid))}</text></svg>')
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "max-age=300"})      # segnaposto per le carte senza immagine


@app.get("/api/filtri")
def filtri():
    langs = sorted({m["lang"] for m in M.meta})
    return jsonify(langs=[{"id": l, "nome": LANGS.get(l, l.upper())} for l in langs],
                   sets=[{"id": s["id"], "names": s["names"], "langs": sorted(s["langs"]), "n": s["n"]} for s in SETS.values()])


SFONDO = {}      # sfondo vuoto memorizzato: uno per utente


@app.errorhandler(Exception)
def errore_json(e):
    """Per le chiamate /api rispondo sempre in JSON (e annoto l'errore nel log), cosi' la pagina mostra la causa vera."""
    from werkzeug.exceptions import HTTPException
    if not request.path.startswith("/api/"):
        if isinstance(e, HTTPException):
            return e
        raise e
    codice = e.code if isinstance(e, HTTPException) else 500
    if codice >= 500:
        log(f"ERRORE {request.path}: " + traceback.format_exc()[-400:])
    return jsonify(errore=f"{type(e).__name__}: {e}"[:200]), codice


@app.route("/api/sfondo", methods=["POST", "DELETE"])
def sfondo():
    if request.method == "DELETE":
        SFONDO.pop(uid(), None)
        return jsonify(ok=True)
    im = img_in()
    if im is None:
        return jsonify(errore="immagine non valida"), 400
    SFONDO[uid()] = im
    return jsonify(ok=True)


@app.post("/api/rileva")
def rileva():
    im = img_in()
    if im is None:
        return jsonify(errore="immagine non valida"), 400
    qd = ps.trova_carta(im, SFONDO.get(uid()))
    h, w = im.shape[:2]
    firma = None
    if qd is not None:      # miniatura 16x22 della carta: serve a capire se e' arrivata una carta diversa
        firma = cv2.resize(cv2.cvtColor(ps.raddrizza(im, qd), cv2.COLOR_BGR2GRAY), (16, 22),
                           interpolation=cv2.INTER_AREA).flatten().tolist()
    return jsonify(trovata=qd is not None, firma=firma,
                   quad=(qd / np.float32([w, h])).tolist() if qd is not None else None)


def aggiungi_fins(lista):
    """Le finiture esistono gia' in ogni candidata (le legge dall'indice Scryfall): qui si garantisce solo l'ordine."""
    for c in lista:
        c["fins"] = [f for f in FIN if f in (c.get("fins") or "S")]
    return lista


@app.post("/api/scan")
def scan():
    t0 = time.time()
    ims = imgs_in()
    if not ims:
        return jsonify(errore="immagine non valida"), 400
    lang, s_ = request.form.get("lang") or None, request.form.get("set") or None
    tutti, trovata = [], False
    for im in ims:
        qd = ps.trova_carta(im, SFONDO.get(uid()))
        trovata = trovata or qd is not None
        card = ps.raddrizza(im, qd) if qd is not None else cv2.resize(im, (ps.W, ps.H))
        card = ps.riduci_riflessi(card)
        with lock:
            top = M.match(card, lang, s_, 6)
        if top:
            tutti.append(top)
    if not tutti:
        return jsonify(errore="nessuna carta con questi filtri"), 404
    top, st = fondi(tutti)
    log(f"riconoscimento: {int((time.time() - t0) * 1000)} ms su {len(ims)} fotogrammi")
    return jsonify(trovata=trovata, stato=st, frames=len(tutti), candidati=aggiungi_fins([cand(r["m"], r["inl"], r["sim"]) for r in top]))


@app.get("/api/cerca")
def cerca():
    t = request.args.get("q", "").strip().lower()
    lang, s = request.args.get("lang"), request.args.get("set")
    out = []
    if len(t) < 2:
        return jsonify(out)
    toks = t.split()
    num = next((x.lstrip("0") or "0" for x in toks if x.isdigit()), None)       # "zapdos 098" cerca per nome E numero
    nome_q = " ".join(x for x in toks if not x.isdigit()) or t

    def ok(m):
        return nome_q in (m.get("name") or "").lower() and (num is None or str(m.get("number", "")).lstrip("0") == num) \
            and (not s or sid(m["id"]) == s)

    for m in M.meta:
        if ok(m) and (not lang or m["lang"] == lang):
            out.append(cand(m))
            if len(out) >= 30:
                break
    noimg = list(getattr(M, "noimg", []))
    for m in noimg:      # carte senza immagine in Scryfall: solo per nome (poi si possono 'imparare' dalla foto)
        if len(out) >= 40:
            break
        if ok(m) and (not lang or m["lang"] == lang):
            c = cand(m)
            c["senza_img"] = True
            out.append(c)
    if lang:      # carte che Scryfall ha solo in altre lingue (es. promo uscite in italiano ma elencate solo in inglese): salvabili nella lingua scelta
        gia = {m["id"] for m in M.meta if m["lang"] == lang} | {m["id"] for m in noimg if m["lang"] == lang}
        visti = set()
        for senza, lista in ((True, noimg), (False, M.meta)):
            for m in lista:
                if len(out) >= 120:
                    break
                if m["lang"] != lang and m["id"] not in gia and m["id"] not in visti and ok(m):
                    visti.add(m["id"])
                    c = cand(m)
                    c["altra_lingua"] = True
                    if senza:
                        c["senza_img"] = True
                    out.append(c)
    return jsonify(aggiungi_fins(out))


def dopo_salvataggio(cid, lang):
    """Prezzo Cardmarket e rarita' da Scryfall: in background, cosi' il salvataggio risponde subito."""
    try:
        primo = not q("select 1 from prezzi where card_id=?", (cid,))
        x = dettagli(cid, lang)
        if x["valore"] is not None:
            q("update carte set valore=?, valuta=? where card_id=? and lang=?", (x["valore"], x["valuta"], cid, lang), True)
        if x["rarita"] != "N/D":
            q("update carte set rarita=? where card_id=? and lang=?", (x["rarita"], cid, lang), True)
        punto(cid, x["valore"], x["valuta"], x["cm"] if primo else None)
    except Exception:
        log("ERRORE dopo salvataggio " + traceback.format_exc()[-300:])


@app.post("/api/salva")
def salva():
    t0 = time.time()
    d = request.get_json()
    cid = d["card_id"]
    cd = d.get("condiz") if d.get("condiz") in COND else "NM"
    fn = d.get("fin") if d.get("fin") in FIN else "S"
    ts = time.strftime("%Y-%m-%d %H:%M")
    r = q("select id from carte where card_id=? and lang=? and coalesce(condiz,'NM')=? and coalesce(fin,'')=? and utente=?", (cid, d["lang"], cd, fn, uid()))
    if r:
        q("update carte set qta=coalesce(qta,1)+1, ts=? where id=?", (ts, r[0]["id"]), True)
    else:
        q("insert into carte(ts,card_id,nome,set_nome,numero,lang,valore,valuta,stato,rarita,qta,condiz,fin,utente) values(?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
          (ts, cid, d["nome"], d["set"], d["numero"], d["lang"], None, "", d.get("stato", "ok"), "N/D", cd, fn, uid()), True)
    qta = q("select qta from carte where card_id=? and lang=? and coalesce(condiz,'NM')=? and coalesce(fin,'')=? and utente=?", (cid, d["lang"], cd, fn, uid()))[0]["qta"]
    if d.get("proposta"):      # registro delle correzioni: la proposta era giusta?
        q("insert into correzioni(ts,proposta,scelta,lang,esatta,pos,stato,punti) values(?,?,?,?,?,?,?,?)",
          (ts, d["proposta"], cid, d["lang"], int(d["proposta"] == cid),
           d.get("pos", 0), d.get("stato", ""), d.get("punti", 0)), True)
    for f, args in (
        (dopo_salvataggio, (cid, d["lang"])),
        (meta_set, (sid(cid), d["lang"])),
        (prezzi_carta, (cid, d["lang"])),
    ) + (((cardtrader_resolve, (cid, d["nome"], d["set"], d["numero"], d["lang"])),) if VENDI_ON else ()):
        threading.Thread(target=f, args=args, daemon=True).start()
    log(f"salvataggio {cid}: {int((time.time() - t0) * 1000)} ms")
    return jsonify(qta=qta)


@app.get("/api/prezzo")
def prezzo():
    """Prezzo di una carta SENZA salvarla: TCGplayer (dollari) e Cardmarket (euro) da Scryfall, per finitura."""
    cid, lang = request.args.get("card_id", ""), request.args.get("lang", "en")
    if not cid:
        return jsonify(errore="carta mancante"), 400
    x = dettagli(cid, lang)
    p = x.get("prezzi") or {}
    tcg = {f: {"NM": float(p["usd" + suf])} for f, suf in FIN_PREZ.items() if p.get("usd" + suf)}      # Scryfall: un solo prezzo (NM) per finitura
    return jsonify(cm=x.get("cm") or {}, rarita=x.get("rarita"), tcg=tcg or None,
                   motivo="" if tcg else ("Scryfall non ha prezzi per questa carta" if p or x.get("valore") else "carta non trovata su Scryfall"))


@app.get("/api/collezione")
def collezione():
    righe = q("select * from carte where utente=? order by id desc", (uid(),))
    for r in righe:
        r["qta"] = r.get("qta") or 1
        r["rarita"] = r.get("rarita") or "N/D"
        r["condiz"] = r.get("condiz") or "NM"
    ult = {(r["card_id"], r["fin"], r["cond"]): r["valore"] for r in q(
        "select card_id, fin, cond, valore from jp2 where giorno=(select max(giorno) from jp2 j "
        "where j.card_id=jp2.card_id and j.fin=jp2.fin and j.cond=jp2.cond)")}
    for r in righe:
        r["fin"] = r.get("fin") or ""
        r["usd"] = ult.get((r["card_id"], r["fin"], r["condiz"]))
        r["eur"] = r["valore"] if (r.get("valuta") == "EUR" and r.get("valore") is not None) else None      # Cardmarket: si usa solo se manca il prezzo TCG
    tot = sum((r["usd"] or 0) * r["qta"] for r in righe)
    tot_cm = sum((r["eur"] or 0) * r["qta"] for r in righe if r["usd"] is None)
    return jsonify(righe=righe, totale_usd=round(tot, 2), totale_eur_cm=round(tot_cm, 2), chiave=True,
                   senza_prezzo=sum(r["qta"] for r in righe if r["usd"] is None and r["eur"] is None))


def _vendi_gruppi():
    """Copie identiche = stessa carta, lingua, condizione e finitura (non-foil, foil ed etched non si sommano)."""
    gruppi = {}
    for r in q("select * from carte where utente=? order by nome, numero", (uid(),)):
        k = (r["card_id"], r["lang"], r.get("condiz") or "NM", r.get("fin") or "")
        e = gruppi.setdefault(k, {
            "card_id": r["card_id"], "lang": r["lang"], "nome": r["nome"],
            "set": r["set_nome"], "numero": r["numero"], "rarita": r.get("rarita") or "N/D",
            "condiz": k[2], "fin": k[3], "qta": 0,
        })
        e["qta"] += r.get("qta") or 1
    return gruppi


def _ct_lookup_blueprint(blueprint_id):
    for _, items in CT_BLUEPRINT_CACHE.values():
        for b in items:
            if int(b.get("id") or b.get("blueprint_id") or 0) == blueprint_id:
                return b
    return None


@app.get("/api/vendi")
def vendi():
    """Carte con almeno 2 copie identiche, con blueprint e prezzo consigliato CardTrader."""
    gruppi = [e for e in _vendi_gruppi().values() if e["qta"] >= 2]
    key = cardtrader_key()
    mapping, info = cardtrader_map(), cardtrader_info()
    if key:
        ora = time.time()
        scoperte = [e for e in gruppi if e["card_id"] not in mapping and
                    (e["card_id"] not in CT_UNRESOLVED or ora - CT_UNRESOLVED[e["card_id"]]["ts"] >= CT_RETRY_SECS)]
        if scoperte:
            ct_resolve_start()
    chiavi = []
    for e in gruppi:
        bp = mapping.get(e["card_id"])
        e["blueprint_id"] = bp
        e["img"] = f"/img/{e['lang']}/{e['card_id']}"
        e["prezzo_consigliato"] = None
        if bp:
            e["match"] = info["metodo"].get(e["card_id"])
            hit = ct_price_get(bp, e["lang"], e["condiz"], e["fin"] or "S") if key else None
            if hit is not None:
                e.update(prezzo_consigliato=hit.get("prezzo"), valuta=hit.get("valuta"), prezzo_info=hit.get("base"),
                         offerte=hit.get("offerte"), prezzo_errore=hit.get("errore") or hit.get("motivo"))
            elif key:
                chiavi.append((bp, e["lang"], e["condiz"], e["fin"] or "S"))
        else:
            u = CT_UNRESOLVED.get(e["card_id"])
            if u:
                e.update(mapping_stato=u["stato"], mapping_motivo=u["motivo"],
                         candidati=[{k: c[k] for k in ("id", "nome", "version", "numero", "espansione")} for c in u["candidati"][:8]])
    if key:
        ct_price_start(chiavi)
    return jsonify(configurato=bool(key), blueprint_in_corso=CT_STATE["running"], prezzi_in_corso=CT_PRICE_STATE["running"],
                   stato={k: CT_STATE[k] for k in ("tot", "fatte", "ok", "mancanti", "ambigui", "errori")},
                   prezzi={"tot": CT_PRICE_STATE["tot"], "fatte": CT_PRICE_STATE["fatte"]}, errore_ct=CT_STATE["errore"],
                   righe=sorted(gruppi, key=lambda x: (x["set"], x["numero"], x["nome"])))


@app.post("/api/vendi/blueprint")
def vendi_blueprint():
    """Pulsante 'Scarica blueprint': riscarica espansioni e blueprint e riprova subito le carte non collegate."""
    if not cardtrader_key():
        return jsonify(errore="Token CardTrader non configurato: vedi DEPLOYMENT.md"), 400
    CT_PRICE_CACHE.clear()
    return jsonify(ok=True, avviato=ct_resolve_start(force=True))


@app.post("/api/vendi/mappa")
def vendi_mappa():
    """Collegamento manuale carta -> blueprint, solo tra i blueprint gia' scaricati (evita ID sbagliati)."""
    d = request.get_json() or {}
    card_id = d.get("card_id")
    try:
        bp = int(d.get("blueprint_id"))
    except (TypeError, ValueError):
        return jsonify(errore="ID blueprint non valido"), 400
    if not card_id or not q("select 1 from carte where card_id=? and utente=? limit 1", (card_id, uid())):
        return jsonify(errore="Carta non presente in collezione"), 400
    cand = next((c for c in (CT_UNRESOLVED.get(card_id) or {}).get("candidati", []) if c["id"] == bp), None)
    props = cand["props"] if cand else None
    if cand is None:
        b = _ct_lookup_blueprint(bp)
        if b is None:
            return jsonify(errore="Blueprint non trovato tra quelli scaricati: premi prima 'Scarica blueprint'"), 400
        props = _ct_props(b)
    ct_save_mapping(card_id, bp, props, "manuale", overwrite=True)
    return jsonify(ok=True)


@app.get("/api/vendi/diagnostica")
def vendi_diagnostica():
    """Cosa sta succedendo con CardTrader, senza mostrare il token."""
    out = {"token": bool(cardtrader_key()), "carte_collegate": len(cardtrader_map()), "stato": dict(CT_STATE),
           "log": list(CT_LOG)[-25:],
           "non_collegate": [{"card_id": k, "stato": v["stato"], "motivo": v["motivo"]} for k, v in list(CT_UNRESOLVED.items())[:40]]}
    if out["token"]:
        try:
            out["app"] = cardtrader_get("/info").get("name")
            out["espansioni_magic"] = len(_ct_expansions())
        except CTError as e:
            out["errore"] = str(e)
    else:
        out["errore"] = "Token CardTrader non configurato"
    return jsonify(out)


@app.post("/api/vendi/pubblica")
def pubblica_vendita():
    d = request.get_json() or {}
    card_id, lang, fin = d.get("card_id"), d.get("lang"), d.get("fin") or ""
    cond = d.get("condiz") or "NM"
    cond = cond if cond in CT_COND else CT_COND_ALIAS.get(cond)
    blueprint_id = cardtrader_map().get(card_id) or d.get("blueprint_id")
    try:
        quantity, price = int(d.get("quantity") or 0), round(float(d.get("price") or 0), 2)
    except (TypeError, ValueError):
        return jsonify(errore="Prezzo o quantita' non validi"), 400
    if not blueprint_id or not cond or not lang or quantity < 1 or price <= 0:
        return jsonify(errore="Carta non collegata a un blueprint, oppure prezzo/quantita' non validi"), 400
    available = q("select coalesce(sum(coalesce(qta,1)), 0) qta from carte where card_id=? and lang=? "
                  "and coalesce(condiz,'NM')=? and coalesce(fin,'')=? and utente=?", (card_id, lang, cond, fin, uid()))[0]["qta"]
    try:
        props = ct_properties(blueprint_id, lang, cond, fin)
        gia = ct_already_listed(int(blueprint_id), props)
        if quantity + gia >= available:
            return jsonify(errore=f"Hai {available} copie, ne hai gia' {gia} in vendita su CardTrader: "
                                  f"ne restano vendibili al massimo {max(available - 1 - gia, 0)} (una resta in collezione)"), 400
        result = cardtrader_post("/products", {
            "blueprint_id": int(blueprint_id), "quantity": quantity, "price": price, "error_mode": "strict",
            "user_data_field": f"magicscan:{card_id}:{lang}:{fin}", "properties": props,
        })
    except CTError as e:
        ctl(f"pubblicazione {card_id}: {e}")
        return jsonify(errore=str(e)), 502
    if isinstance(result, dict) and result.get("result") not in (None, "ok"):
        return jsonify(errore="CardTrader ha rifiutato l'annuncio: " + json.dumps(result.get("errors") or result)[:300]), 502
    ctl(f"pubblicato {quantity} x {card_id} {lang} {cond} {fin or '-'} a {price:.2f}")
    return jsonify(ok=True, prodotto=result, avvisi=(result or {}).get("warnings") or {})


@app.get("/api/log")
def log_eventi():
    return jsonify(eventi=list(JTLOG))


@app.get("/api/tcg/<cid>")
def tcg(cid):
    own = set(combos_di(cid))
    serie = {}
    for r in q("select cond, fin, giorno, valore from jp2 where card_id=? order by giorno", (cid,)):
        if (r["cond"], r["fin"]) in own:
            serie.setdefault(r["cond"] + "|" + r["fin"], []).append({"giorno": r["giorno"], "valore": r["valore"]})
    return jsonify(collegata=bool(serie), serie=serie)


@app.get("/api/storico/<cid>")
def storico(cid):
    return jsonify(q("select giorno, valore, valuta from prezzi where card_id=? order by giorno", (cid,)))


@app.post("/api/qta/<int:i>")
def qta(i):
    n = int((request.get_json() or {}).get("d", 1))
    q("update carte set qta=coalesce(qta,1)+? where id=? and utente=?", (n, i, uid()), True)
    q("delete from carte where id=? and qta<=0 and utente=?", (i, uid()), True)
    return jsonify(ok=True)


@app.delete("/api/carta/<int:i>")
def elimina(i):
    q("delete from carte where id=? and utente=?", (i, uid()), True)
    return jsonify(ok=True)


@app.post("/api/elimina")
def elimina_molte():
    ids = [int(i) for i in ((request.get_json() or {}).get("ids") or [])][:500]
    q_molti("delete from carte where id=? and utente=?", [(i, uid()) for i in ids])
    return jsonify(ok=True, eliminate=len(ids))


AGG = {"attivo": False, "ultimo": 0.0}
AGG_LOCK = threading.Lock()


@app.post("/api/aggiorna")
def aggiorna_ora():
    """Aggiornamento prezzi di tutte le carte di tutti gli utenti: al massimo uno ogni 30 minuti, qualunque utente lo chieda."""
    with AGG_LOCK:
        ora = time.time()
        if AGG["attivo"] or ora - AGG["ultimo"] < 1800:
            return jsonify(ok=True, avviato=False, messaggio="Prezzi gia' aggiornati da poco: si aggiornano comunque ogni giorno.")
        AGG["attivo"], AGG["ultimo"] = True, ora

    def lavoro():
        try:
            aggiorna()
        finally:
            AGG["attivo"] = False
    threading.Thread(target=lavoro, daemon=True).start()
    return jsonify(ok=True, avviato=True)


@app.get("/export.csv")
def export():
    o = io.StringIO()
    w = csv.writer(o, delimiter=";")
    w.writerow(["data", "id", "nome", "set", "numero", "lingua", "rarita", "quantita", "valore", "valuta", "stato", "condizione", "finitura"])
    for r in q("select * from carte where utente=? order by id", (uid(),)):
        w.writerow([r["ts"], r["card_id"], r["nome"], r["set_nome"], r["numero"], r["lang"], r.get("rarita") or "",
                    r.get("qta") or 1, str(r["valore"] if r["valore"] is not None else "").replace(".", ","),
                    r["valuta"], r["stato"], r.get("condiz") or "NM", {"S": "Non-foil", "H": "Foil", "R": "Etched"}.get(r.get("fin") or "", "")])
    return Response("\ufeff" + o.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=collezione.csv"})
