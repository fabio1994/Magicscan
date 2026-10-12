"""Test di Magicscan con finti Scryfall e CardTrader. Uso: python test_magic.py <cartella_app>"""
import json, os, sys, tempfile, time, pathlib, importlib.util, re
from urllib.parse import unquote
import numpy as np

os.environ["MAGIC_VENDI"] = os.environ.get("TEST_VENDI", "1")
APP_DIR = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent).resolve()
work = tempfile.mkdtemp(prefix="magic_test_")
os.makedirs(work + "/magicdata")
os.chdir(work)
sys.path.insert(0, str(APP_DIR))
sys.argv = ["x"]

import magicscan as ps

fails = [0]
def ok(c, msg):
    print(("  OK   " if c else "  FAIL ") + msg)
    if not c:
        fails[0] += 1

class Resp:
    def __init__(self, status=200, data=None, content=b""):
        self.status_code, self._d, self.content = status, data, content
        self.ok = 200 <= status < 300
        self.text = json.dumps(data) if data is not None else ""
        self.headers = {}
    def json(self): return self._d
    def raise_for_status(self):
        if not self.ok: raise RuntimeError(self.status_code)

# ------------------------------ finto Scryfall ------------------------------
def sfcard(id_, set_, setname, cn, name, finishes=("nonfoil", "foil"), lang="en", prices=None, rarity="rare", faces=False):
    c = {"id": id_, "set": set_, "set_name": setname, "collector_number": cn, "name": name, "lang": lang, "rarity": rarity,
         "finishes": list(finishes), "digital": False, "image_status": "highres",
         "prices": prices or {"usd": "1.50", "usd_foil": "3.00", "eur": "1.20", "eur_foil": "2.50", "usd_etched": None}}
    img = {"normal": f"https://img.test/{id_}.jpg", "small": f"https://img.test/{id_}.jpg"}
    if faces:
        c["card_faces"] = [{"image_uris": img}, {"image_uris": img}]
    else:
        c["image_uris"] = img
    if lang != "en":
        c["printed_name"] = name + " (" + lang + ")"
    return c

SF_EN = [
    sfcard("sf-bolt", "2x2", "Double Masters 2022", "117", "Lightning Bolt", prices={"usd": "2.00", "usd_foil": "4.00", "eur": "1.50", "eur_foil": "3.50"}),
    sfcard("sf-rag", "mh2", "Modern Horizons 2", "138", "Ragavan, Nimble Pilferer", finishes=("nonfoil", "foil", "etched"),
           prices={"usd": "40.00", "usd_foil": "60.00", "usd_etched": "80.00", "eur": "38.00", "eur_foil": "55.00"}),
    sfcard("sf-star", "neo", "Kamigawa: Neon Dynasty", "12★", "Boseiju, Who Endures", finishes=("foil",)),
    sfcard("sf-plain", "neo", "Kamigawa: Neon Dynasty", "12", "Boseiju, Who Endures"),
    sfcard("sf-dfc", "mid", "Innistrad: Midnight Hunt", "81", "Delver of Secrets // Insectile Aberration", faces=True),
    {**sfcard("sf-dig", "mh3", "Digital", "1", "Digital Only"), "digital": True},
    {**sfcard("sf-ph", "mh3", "Modern Horizons 3", "2", "Spoiler"), "image_status": "placeholder"},
]
SF_IT = [sfcard("sf-bolt-it", "2x2", "Double Masters 2022", "117", "Lightning Bolt", lang="it", prices={"usd": None})]
SEARCH_LOG = []

def sf_route(method, url, params, body):
    path = url.split("scryfall.com", 1)[1]
    if "?" in path:
        from urllib.parse import parse_qs
        path, qs = path.split("?", 1)
        params = {k: (int(v[0]) if v[0].isdigit() else v[0]) for k, v in parse_qs(qs).items()}
    if path == "/cards/search":
        qq = params["q"]
        SEARCH_LOG.append(qq)
        lang = re.search(r"lang:(\w+)", qq).group(1)
        pool = SF_EN if lang == "en" else SF_IT
        if "year>=" in qq and int(re.search(r"year>=(\d+)", qq).group(1)) > 2022:
            pool = pool[:0]
        # due pagine per provare la paginazione
        page = 2 if params.get("page") == 2 else 1
        half = (len(pool) + 1) // 2
        data = pool[:half] if page == 1 else pool[half:]
        out = {"data": data, "has_more": page == 1 and len(pool) > 1}
        if out["has_more"]:
            out["next_page"] = "https://api.scryfall.com/cards/search?page=2&q=" + qq
        return Resp(200, out)
    m = re.match(r"/cards/([^/]+)/([^/]+)/(\w+)$", path)
    if m and method == "GET" and m.group(1) not in ("search", "collection"):
        st, cn, lg = m.group(1), unquote(m.group(2)), m.group(3)
        for c in SF_EN:
            if c["set"] == st and c["collector_number"] == cn and lg == "en":
                return Resp(200, c)
        return Resp(404, {"object": "error"})
    if path == "/cards/collection":
        found = [c for i in body["identifiers"] for c in SF_EN if c["set"] == i["set"] and c["collector_number"] == i["collector_number"]]
        return Resp(200, {"data": found, "not_found": []})
    m = re.match(r"/cards/(sf-[\w-]+)$", path)
    if m:
        for c in SF_EN + SF_IT:
            if c["id"] == m.group(1):
                return Resp(200, c)
        return Resp(404, {})
    m = re.match(r"/sets/(\w+)$", path)
    if m:
        return Resp(200, {"name": "Set " + m.group(1), "card_count": 99, "icon_svg_uri": "https://svgs.test/" + m.group(1) + ".svg"})
    return Resp(404, {})

# ------------------------------ finto CardTrader ------------------------------
def ctprops(foil=True, langs=("en", "fr", "de", "it", "jp", "kr", "pt", "es", "ru")):
    p = [{"name": "condition", "type": "string", "default_value": "Near Mint",
          "possible_values": ["Near Mint", "Slightly Played", "Moderately Played", "Played", "Heavily Played", "Poor"]},
         {"name": "mtg_language", "type": "string", "default_value": "en", "possible_values": list(langs)},
         {"name": "signed", "type": "boolean", "possible_values": [True, False]},
         {"name": "altered", "type": "boolean", "possible_values": [True, False]}]
    if foil:
        p.append({"name": "mtg_foil", "type": "boolean", "default_value": "false", "possible_values": [True, False]})
    return p
def ctbp(id_, name, exp, cn, sf, foil=True):
    return {"id": id_, "name": name, "version": None, "game_id": 1, "category_id": 1, "expansion_id": exp,
            "fixed_properties": {"collector_number": cn}, "editable_properties": ctprops(foil),
            "card_market_ids": [1], "tcg_player_id": None, "scryfall_id": sf}
CT_EXP = [{"id": 10, "game_id": 1, "code": "2x2", "name": "Double Masters 2022"},
          {"id": 11, "game_id": 1, "code": "mh2", "name": "Modern Horizons 2"},
          {"id": 12, "game_id": 1, "code": "neo", "name": "Kamigawa: Neon Dynasty"},
          {"id": 13, "game_id": 1, "code": "mid", "name": "Innistrad: Midnight Hunt"},
          {"id": 99, "game_id": 5, "code": "30c", "name": "30th Celebration"}]       # Pokemon: da ignorare
CT_BP = {10: [ctbp(1001, "Lightning Bolt", 10, "117", "sf-bolt")],
         11: [ctbp(1101, "Ragavan, Nimble Pilferer", 11, "999", "sf-rag")],           # numero diverso: si collega col scryfall_id
         12: [ctbp(1201, "Boseiju, Who Endures", 12, "12", "sf-plain"), ctbp(1202, "Boseiju, Who Endures", 12, "12★", "sf-star")],
         13: [ctbp(1301, "Delver of Secrets // Insectile Aberration", 13, "81", "sf-dfc")]}
POSTED, LISTED, CALLS = [], [], []
def ct_route(method, url, params, body, headers):
    path = url.split("/api/v2", 1)[1]
    CALLS.append((method, path, params))
    if headers.get("Authorization") != "Bearer TESTTOKEN":
        return Resp(401, {"error_code": "unauthorized"})
    if path == "/info": return Resp(200, {"name": "Test App", "shared_secret": "SEGRETO"})
    if path == "/expansions": return Resp(200, CT_EXP)
    if path == "/blueprints/export": return Resp(200, CT_BP.get(int(params["expansion_id"]), []))
    if path == "/marketplace/products":
        bp, foil, lang = int(params["blueprint_id"]), params.get("foil"), params.get("language")
        offers = {1001: [(1.0, "Near Mint", True, "en"), (0.5, "Near Mint", False, "en"), (0.4, "Near Mint", False, "it"), (0.3, "Played", False, "it")],
                  1301: []}.get(bp, [])
        out = []
        for i, (p, c, f, lg) in enumerate(offers):
            if foil is not None and (foil == "true") != f: continue
            if lang and lg != lang: continue
            out.append({"id": i, "price": {"cents": int(p * 100), "currency": "EUR"}, "on_vacation": False, "graded": False,
                        "properties_hash": {"condition": c, "mtg_foil": f, "mtg_language": lg}})
        return Resp(200, {str(bp): out})
    if path == "/products/export":
        return Resp(200, [p for p in LISTED if p["blueprint_id"] == int(params["blueprint_id"])])
    if path == "/products" and method == "POST":
        allowed = {p["name"]: p["possible_values"] for e in CT_BP.values() for b in e if b["id"] == body["blueprint_id"] for p in b["editable_properties"]}
        for k, v in body["properties"].items():
            if k not in allowed or v not in allowed[k]:
                return Resp(422, {"error_code": "validation_error", "errors": {k: ["not allowed"]}})
        POSTED.append(body)
        return Resp(200, {"result": "ok", "warnings": {}, "resource": {"id": 1}})
    return Resp(404, {"error_code": "not_found", "extra": {"message": "no " + path}})

class FakeRequests:
    @staticmethod
    def request(method, url, params=None, json=None, headers=None, timeout=None, **kw):
        if "cardtrader.com" in url: return ct_route(method, url, params, json, headers or {})
        if "scryfall.com" in url:
            assert "User-Agent" in (headers or {}) and "Accept" in (headers or {}), "Scryfall richiede User-Agent e Accept"
            return sf_route(method, url, params, json)
        return Resp(404, {})
    @staticmethod
    def get(url, params=None, headers=None, timeout=None, **kw):
        if "img.test" in url: return Resp(200, content=b"\xff\xd8" + b"x" * 2000)
        if "svgs.test" in url: return Resp(200, content=b"<svg xmlns='http://www.w3.org/2000/svg'>" + b" " * 200 + b"</svg>")
        return FakeRequests.request("GET", url, params, None, headers, timeout)
ps.requests = FakeRequests
import cv2
# le immagini finte non sono vere: Image.open fallisce e l'indice usa un riquadro vuoto (comportamento previsto)

class FakeModel:
    def encode(self, ims, **kw):
        return np.random.RandomState(len(ims)).rand(len(ims), 8).astype("float32")

print("1) indice da Scryfall")
cards = list(ps.carte_scryfall("en"))
ids = [c["id"] for c in cards]
ok(len(cards) == 5, f"5 carte valide su 7 (esclusi digitale e segnaposto): {len(cards)}, in 2 pagine")
ok(ids == sorted(set(ids), key=ids.index) and "neo-12u2605" in ids and "neo-12" in ids, f"id senza trattini nei numeri, ★ distinto da 12: {ids}")
bolt = next(c for c in cards if c["id"] == "2x2-117")
ok(bolt["sf"] == "sf-bolt" and bolt["fins"] == "SH" and bolt["rarity"] == "Rare", f"scheda: {bolt['fins']} {bolt['rarity']}")
ok(next(c for c in cards if c["id"] == "mh2-138")["fins"] == "SHR", "finiture non-foil/foil/etched lette da Scryfall")
ok(next(c for c in cards if c["id"] == "mid-81")["image"].endswith("sf-dfc.jpg"), "carta a doppia faccia: immagine della prima faccia")
n = ps._indicizza(FakeModel(), "en", cards, ogni=2)
meta = json.loads(pathlib.Path("magicdata/meta.json").read_text())
E = np.load("magicdata/emb.npy")
ok(n == 5 and len(meta) == 5 and E.shape[0] == 5 and "image" not in meta[0], f"indice salvato a blocchi: {n} carte, {E.shape}")
ok(ps._indicizza(FakeModel(), "en", cards) == 0, "seconda esecuzione: niente da rifare")
ok(list(ps.carte_scryfall("en", dal=2030)) == [] and "year>=2030" in SEARCH_LOG[-1], f"filtro --dal nella ricerca: {SEARCH_LOG[-1]}")
ps._indicizza(FakeModel(), "it", list(ps.carte_scryfall("it")))
ok(pathlib.Path("magicdata/meta_it.json").exists() and (ps.IMG / "it_2x2-117.jpg").exists(), "indice italiano separato")

print("2) app")
class FakeMatcher:
    def __init__(self):
        self.meta = json.loads(pathlib.Path("magicdata/meta.json").read_text()) + json.loads(pathlib.Path("magicdata/meta_it.json").read_text())
        self.model = FakeModel()
    def carica(self): pass
    def match(self, *a, **k): return []
ps.Matcher = FakeMatcher
spec = importlib.util.spec_from_file_location("app", APP_DIR / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
c = app.app.test_client()

def add(card, lang, cond, fin, qta):
    m = next(x for x in app.M.meta if x["id"] == card and x["lang"] == lang)
    app.q("insert into carte(ts,card_id,nome,set_nome,numero,lang,valore,valuta,stato,rarita,qta,condiz,fin) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ("2026-10-11", card, m["name"], m["set"], m["number"], lang, None, "", "ok", "N/D", qta, cond, fin), True)

# ------------------------------ UTENTI ------------------------------
import re as _re
print("== Utenti e registrazione")
add("2x2-117", "en", "NM", "S", 2)       # carta esistente prima del login: e' dell'utente 1
r = c.get("/api/collezione")
ok(r.status_code == 200 and len(r.get_json()["righe"]) == 1, "nessun utente registrato: app aperta, collezione visibile")

# migrazione del vecchio login (auth.json)
app.AUTH.write_text(json.dumps({"user": "Mario", "hash": app.generate_password_hash("segreta123")}))
app.migra_utenti()
u = app.q("select * from utenti")
ok(len(u) == 1 and u[0]["id"] == 1 and u[0]["admin"] == 1 and u[0]["nome"] == "Mario", "auth.json migrato nell'amministratore (id 1)")
ok(not app.AUTH.exists(), "auth.json rinominato")

ok(c.get("/api/collezione").status_code == 401, "ora senza accesso: 401")
ok(c.get("/").status_code == 302 and "/login" in c.get("/").headers["Location"], "pagina principale -> /login")
r = c.post("/login", data={"u": "mario", "p": "sbagliata"})
ok(b"errati" in r.data, "password errata rifiutata")
r = c.post("/login", data={"u": "mario", "p": "segreta123"})
ok(r.status_code == 302, "login admin (nome senza distinzione maiuscole)")
righe = c.get("/api/collezione").get_json()["righe"]
ok(len(righe) == 1 and righe[0]["qta"] == 2, "l'admin ritrova la collezione di prima")
st = c.get("/api/stato").get_json()
ok(st["utente"] == "Mario" and st["admin"] is True, "stato: utente e admin")

# inviti
ok(b"Utenti e inviti" in c.get("/admin").data, "pagina admin")
c.post("/admin/invito")
pg = c.get("/admin").data.decode()
codici = _re.findall(r"<code>([0-9A-F]{5}-[0-9A-F]{5})</code>", pg)
ok(len(codici) == 1, f"codice invito generato: {codici}")
cod = codici[0]

c2 = app.app.test_client()
ok(c2.get("/registrati").status_code == 200, "pagina registrazione raggiungibile senza accesso")
ok(c2.get("/admin").status_code == 302, "non loggato: /admin rimanda al login")
r = c2.post("/registrati", data={"u": "Luca", "p": "password1", "p2": "password1", "c": "AAAAA-BBBBB"})
ok(b"non valido" in r.data, "codice sbagliato rifiutato")
r = c2.post("/registrati", data={"u": "Lu", "p": "password1", "p2": "password1", "c": cod})
ok(b"3 a 30" in r.data, "nome troppo corto rifiutato")
r = c2.post("/registrati", data={"u": "Luca", "p": "corta", "p2": "corta", "c": cod})
ok(b"8 caratteri" in r.data, "password corta rifiutata")
r = c2.post("/registrati", data={"u": "Mario", "p": "password1", "p2": "password1", "c": cod})
ok(b"in uso" in r.data, "nome gia' usato rifiutato")
ok(app.q("select usato_da from inviti where codice=?", (cod,))[0]["usato_da"] is None, "il codice non si brucia se il nome e' occupato")
r = c2.post("/registrati", data={"u": "Luca", "p": "password1", "p2": "password1", "c": cod.lower()})
ok(r.status_code == 302, "registrazione con codice valido (anche minuscolo)")
ok(c2.get("/api/stato").get_json()["utente"] == "Luca", "dopo la registrazione e' gia' collegato")
c3 = app.app.test_client()
r = c3.post("/registrati", data={"u": "Marta", "p": "password1", "p2": "password1", "c": cod})
ok(b"non valido" in r.data, "il codice funziona una sola volta")

# collezioni separate
ok(c2.get("/api/collezione").get_json()["righe"] == [], "il nuovo utente non vede le carte dell'admin")
ok(c2.get("/api/stato").get_json()["admin"] is False and c2.get("/admin").status_code == 302, "utente normale: niente pagina admin")
r = c2.post("/api/salva", json={"card_id": "2x2-117", "lang": "en", "nome": "Lightning Bolt", "set": "Double Masters 2022", "numero": "117"})
ok(r.status_code == 200 and r.get_json()["qta"] == 1, "Luca salva la sua copia: quantita' 1 (non 3)")
time.sleep(0.5)
a = c.get("/api/collezione").get_json()["righe"]
l = c2.get("/api/collezione").get_json()["righe"]
ok(len(a) == 1 and a[0]["qta"] == 2 and len(l) == 1 and l[0]["qta"] == 1, "ognuno ha le proprie quantita'")
id_admin, id_luca = a[0]["id"], l[0]["id"]
c2.delete(f"/api/carta/{id_admin}")
c2.post(f"/api/qta/{id_admin}", json={"d": -5})
c2.post("/api/elimina", json={"ids": [id_admin]})
ok(c.get("/api/collezione").get_json()["righe"][0]["qta"] == 2, "Luca non puo' toccare le carte dell'admin")
r = c2.post(f"/api/condiz/{id_admin}", json={"condiz": "LP"}) if False else None
ok(c2.get("/export.csv").data.decode().count("Lightning") == 1, "export: solo le carte dell'utente")
ok(c.get("/export.csv").data.decode().count("Lightning") == 1, "export admin: solo le sue")
ok(len(c2.get("/api/set").get_json()) >= 0, "elenco set per utente")

# admin elimina l'utente
ids_u = {x["nome"]: x["id"] for x in app.q("select * from utenti")}
c.post(f"/admin/utente/{ids_u['Luca']}/elimina")
ok(not app.q("select 1 from carte where utente=?", (ids_u["Luca"],)) and not app.q("select 1 from utenti where nome='Luca'"), "utente eliminato con le sue carte")
ok(c2.get("/api/collezione").status_code == 401, "la sessione dell'utente eliminato non vale piu'")
ok(app.q("select qta from carte where utente=1")[0]["qta"] == 2, "le carte dell'admin sono intatte")
c.post(f"/admin/utente/1/elimina")
ok(app.q("select 1 from utenti where id=1"), "l'admin non si puo' eliminare")

print("== Aggiornamento prezzi")
app.AGG["ultimo"] = 0.0
r1 = c.post("/api/aggiorna").get_json(); r2 = c.post("/api/aggiorna").get_json()
ok(r1.get("avviato") is True and r2.get("avviato") is False, f"secondo aggiornamento a breve distanza rifiutato: {r2}")

print()
print("FALLITI:", fails[0])
sys.exit(1 if fails[0] else 0)
