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

r = c.get("/api/filtri").get_json()
ok({l["id"] for l in r["langs"]} == {"en", "it"} and any(s["id"] == "2x2" for s in r["sets"]), "filtri: lingue e set dall'indice")
add("2x2-117", "it", "NM", "H", 3)            # Bolt italiana foil
add("2x2-117", "en", "NM", "S", 2)
add("mh2-138", "en", "NM", "H", 2)            # numero diverso su CardTrader
add("neo-12u2605", "en", "NM", "H", 2)
add("neo-12", "en", "LP", "S", 2)
add("mid-81", "en", "HP", "S", 2)

print("3) salvataggio e prezzi Scryfall")
app.aggiorna()
righe = {(r["card_id"], r["lang"], r["fin"]): r for r in c.get("/api/collezione").get_json()["righe"]}
ok(righe[("2x2-117", "it", "H")]["usd"] == 4.0 and righe[("2x2-117", "en", "S")]["usd"] == 2.0, "prezzo USD per finitura (foil 4.00, non-foil 2.00)")
ok(righe[("mh2-138", "en", "H")]["usd"] == 60.0 and righe[("mh2-138", "en", "H")]["rarita"] == "Rare", "foil 60.00, rarita' dalla scheda")
ok(righe[("2x2-117", "en", "S")]["valuta"] == "EUR" and righe[("2x2-117", "en", "S")]["valore"] == 1.5, "Cardmarket (euro) salvato")
app.prezzi_carta("2x2-117", "it")
ok(app.q("select count(*) n from jp2 where card_id='2x2-117'")[0]["n"] >= 2, "storico prezzi")
p = c.get("/api/prezzo?card_id=mh2-138&lang=en").get_json()
ok(p["tcg"]["R"]["NM"] == 80.0 and p["tcg"]["H"]["NM"] == 60.0 and p["rarita"] == "Rare", f"/api/prezzo: {p['tcg']}")
app.meta_set("2x2", "en")
ok(app.q("select nome, totale from setinfo where sid='2x2'")[0]["totale"] == 99 and app._set_file("2x2", "en").exists(), "informazioni e simbolo SVG del set")
rr = c.get("/setimg/en/2x2")
ok(rr.status_code == 200 and "svg" in rr.mimetype, f"simbolo servito come {rr.mimetype}")
cs = c.get("/api/cerca?q=boseiju").get_json()
ok(len(cs) == 2 and all(x["fins"] for x in cs), f"ricerca per nome con finiture: {[(x['numero'], x['fins']) for x in cs]}")
ok(any(x["fins"] == ["S", "H", "R"] for x in c.get("/api/cerca?q=ragavan").get_json()), "etched disponibile per Ragavan")

if os.environ["MAGIC_VENDI"] != "1":
    print("4) Vendi spenta")
    r = c.get("/api/vendi")
    ok(r.status_code == 404 and c.post("/api/vendi/pubblica", json={}).status_code == 404 and c.get("/api/vendi/diagnostica").status_code == 404, "tutte le /api/vendi rispondono 404")
    ok(c.get("/api/stato").get_json()["vendi"] is False, "/api/stato dice vendi=False")
    app.q("delete from carte", (), True); add("2x2-117", "en", "NM", "S", 1)
    pathlib.Path("magicdata/cardtrader.key").write_text("TESTTOKEN")
    r = c.post("/api/salva", json={"card_id": "2x2-117", "nome": "Lightning Bolt", "set": "x", "numero": "117", "lang": "en"})
    time.sleep(1.5)
    ok(r.status_code == 200 and not any("cardtrader" in x[1] or x[1].startswith("/blueprints") for x in CALLS) and not pathlib.Path("magicdata/cardtrader_blueprints.json").exists(), "salvando una carta non parte nessuna chiamata a CardTrader")
    print(); print("FALLITI:", fails[0]); sys.exit(1 if fails[0] else 0)
print("4) CardTrader per Magic")
pathlib.Path("magicdata/cardtrader.key").write_text("TESTTOKEN")
def attendi(pred, t=40):
    t0 = time.time()
    while time.time() - t0 < t:
        d = c.get("/api/vendi").get_json()
        if pred(d): return d
        time.sleep(0.3)
    return d
d = attendi(lambda d: not d["blueprint_in_corso"] and not d["prezzi_in_corso"] and all(r.get("blueprint_id") for r in d["righe"]))
mp = json.loads(pathlib.Path("magicdata/cardtrader_blueprints.json").read_text())
ok(mp.get("2x2-117") == 1001 and mp.get("mh2-138") == 1101, f"collegate (anche con numero diverso, via scryfall_id): {mp}")
ok(mp.get("neo-12") == 1201 and mp.get("neo-12u2605") == 1202, "12 e 12★ distinti grazie allo scryfall_id")
ok(mp.get("mid-81") == 1301, "carta a doppia faccia collegata")
inf = json.loads(pathlib.Path("magicdata/cardtrader_blueprint_info.json").read_text())
ok(inf["metodo"]["mh2-138"] == "scryfall", "metodo di collegamento: scryfall_id")
ok(all(x[2]["expansion_id"] != 99 for x in CALLS if x[1] == "/blueprints/export"), "espansione Pokemon ignorata")
righe = {(r["card_id"], r["lang"], r["fin"]): r for r in d["righe"]}
b = righe[("2x2-117", "it", "H")]
ok(b["prezzo_consigliato"] is None or True, "")
ok(righe[("2x2-117", "en", "S")]["prezzo_consigliato"] == 0.5, f"non-foil EN NM: 0.50 (non 1.00 foil): {righe[('2x2-117', 'en', 'S')]['prezzo_consigliato']}")
ok(b["prezzo_consigliato"] == 1.0 and "qualsiasi lingua" in b["prezzo_info"], f"foil IT: nessuna offerta IT foil -> ripiega su qualsiasi lingua, 1.00: {b['prezzo_consigliato']} [{b.get('prezzo_info')}]")
mk = [x for x in CALLS if x[1] == "/marketplace/products"]
ok(all(x[2].get("foil") in ("true", "false") for x in mk), "il filtro foil viene sempre inviato al marketplace")

print("5) pubblicazione")
def pub(card, lang, cond, fin, qty, price=1.0):
    return c.post("/api/vendi/pubblica", json={"card_id": card, "lang": lang, "fin": fin, "condiz": cond, "quantity": qty, "price": price})
r = pub("2x2-117", "it", "NM", "H", 2)
ok(r.status_code == 200 and POSTED[-1]["properties"] == {"condition": "Near Mint", "mtg_language": "it", "mtg_foil": True}, f"foil italiana: {POSTED[-1]['properties']}")
r = pub("2x2-117", "en", "NM", "S", 1)
ok(r.status_code == 200 and POSTED[-1]["properties"] == {"condition": "Near Mint", "mtg_language": "en", "mtg_foil": False}, f"non-foil: {POSTED[-1]['properties']}")
r = pub("mid-81", "en", "HP", "S", 1)
ok(r.status_code == 200 and POSTED[-1]["properties"]["condition"] == "Heavily Played", f"HP -> Heavily Played: {POSTED[-1]['properties']}")
r = pub("neo-12", "en", "LP", "S", 1)
ok(r.status_code == 200 and POSTED[-1]["properties"]["condition"] == "Slightly Played", "LP -> Slightly Played")
r = pub("mh2-138", "en", "NM", "R", 1)
ok(r.status_code == 400 or r.status_code == 502, f"etched senza proprieta' su CardTrader: rifiutato ({r.status_code})")
r = pub("2x2-117", "it", "NM", "H", 3)
ok(r.status_code == 400, "non vende tutte le copie")
add("2x2-117", "en", "MP", "S", 2)
app.q("update carte set lang='ja' where card_id='2x2-117' and condiz='MP'", (), True)
c.get("/api/vendi")
r = c.post("/api/vendi/pubblica", json={"card_id": "2x2-117", "lang": "ja", "fin": "S", "condiz": "MP", "quantity": 1, "price": 1})
ok(r.status_code == 200 and POSTED[-1]["properties"]["mtg_language"] == "jp", f"giapponese ja -> jp: {POSTED[-1]['properties']}")

print()
print("FALLITI:", fails[0])
sys.exit(1 if fails[0] else 0)
