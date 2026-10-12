"""
magicscan - riconosce carte Magic: The Gathering (anche rovinate) e ne assegna il valore.

Come funziona:
  1) un modello CLIP confronta la carta con le immagini ufficiali e propone i 40 candidati piu' simili;
  2) un secondo controllo (punti caratteristici SIFT) verifica i candidati e sceglie quello che coincide davvero.

Dati, immagini e prezzi da Scryfall (gratuito, nessuna chiave necessaria).

Uso (di solito dentro Docker, vedi DEPLOYMENT.md):
    python magicscan.py index                       # indice inglese di tutte le carte cartacee
    python magicscan.py index --dal 2015            # solo le carte uscite dal 2015 (molto piu' veloce)
    python magicscan.py index --set mh3,otj,blb     # solo alcuni set (codici Scryfall)
    python magicscan.py index --lang it             # carte stampate in italiano
Gli indici si possono estendere in qualsiasi momento: vengono aggiunte solo le carte nuove.
"""
import argparse, csv, datetime as dt, json, os, pathlib, re, sys, time
from collections import OrderedDict
from urllib.parse import quote
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import cv2, numpy as np, requests
from PIL import Image

BASE = "https://api.scryfall.com"
HEADERS = {"User-Agent": "Magicscan/1.0 (collezione personale)", "Accept": "application/json;q=0.9,*/*;q=0.8"}
DATA = pathlib.Path(os.environ.get("MAGIC_DATA", "magicdata"))      # su PC: MAGIC_DATA=D:\\ (immagini in D:\\img)
IMG = DATA / "img"
CSV_OUT = "collezione.csv"
W, H = 300, 420
SOGLIA_SCORE = 0.80     # similarita' CLIP minima per fidarsi quando SIFT non basta
SOGLIA_MARGINE = 0.02
CANDIDATI = 40          # quanti candidati ricontrolla SIFT
IMG_SIZE = os.environ.get("MAGIC_IMG", "normal")      # 'normal' (488x680, ~8 GB per tutto) oppure 'small' (146x204, ~1.5 GB)
FIN_SF = {"nonfoil": "S", "foil": "H", "etched": "R"}  # finiture Scryfall -> codici dell'app


def file_indice(lang):
    return ("emb.npy", "meta.json") if lang == "en" else (f"emb_{lang}.npy", f"meta_{lang}.json")


def percorso(m):
    lang = m.get("lang", "en")
    return IMG / (f"{m['id']}.jpg" if lang == "en" else f"{lang}_{m['id']}.jpg")


def get_json(url, tries=8, timeout=60, params=None):
    """GET con le intestazioni richieste da Scryfall e una pausa tra le richieste (max ~5 al secondo).
    Con 429 (troppe richieste) aspetta sempre piu' a lungo, come indica Scryfall."""
    for t in range(tries):
        attesa = 3 * (t + 1)
        try:
            time.sleep(0.2)
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 404:
                return None          # non esiste: inutile riprovare
            if r.status_code in (429, 403, 503):
                attesa = max(attesa, int(r.headers.get("Retry-After", 0) or 0), 60 * (t + 1))
                print(f"Scryfall risponde {r.status_code} (troppe richieste): pausa di {attesa} s, poi riprovo...", flush=True)
                time.sleep(attesa)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"Errore ({e.__class__.__name__}) su {url}, riprovo tra {attesa}s...")
            time.sleep(attesa)


def numero_sicuro(cn):
    """Il numero di collezione diventa parte dell'id: solo lettere e cifre ('123★' -> '123u2605', 'A12' -> 'a12')."""
    return (re.sub(r"[^A-Za-z0-9]", lambda m: f"u{ord(m.group()):x}", str(cn or "")) or "0").lower()      # minuscolo: Windows e NAS non distinguono le maiuscole nei nomi file


def meta_carta(c, lang):
    """Scheda dell'indice da una carta Scryfall, o None se non ha un'immagine utilizzabile."""
    if c.get("digital") or c.get("image_status") in ("missing", "placeholder"):
        return None
    iu = c.get("image_uris") or ((c.get("card_faces") or [{}])[0].get("image_uris") or {})
    url = iu.get(IMG_SIZE) or iu.get("normal")
    if not url or not c.get("set"):
        return None
    fins = "".join(f for k, f in FIN_SF.items() if k in (c.get("finishes") or [])) or "S"
    nome = c.get("printed_name") or c.get("name", "")
    return {"id": f"{c['set']}-{numero_sicuro(c.get('collector_number'))}", "name": nome, "number": c.get("collector_number", ""),
            "set": c.get("set_name", c["set"]), "lang": lang, "sf": c.get("id"), "rarity": (c.get("rarity") or "").capitalize() or "N/D",
            "fins": fins, "image": url}


def query_carte(lang, dal=None, sets=None):
    q = f"game:paper lang:{lang}"
    if dal:
        q += f" year>={int(dal)}"
    if sets:
        q += " (" + " or ".join(f"e:{s}" for s in sets) + ")"
    return q


def carte_scryfall(lang="en", dal=None, sets=None):
    """Tutte le stampe che corrispondono (paginando la ricerca di Scryfall: 175 carte per pagina)."""
    url, params = f"{BASE}/cards/search", {"q": query_carte(lang, dal, sets), "unique": "prints", "order": "set",
                                           "include_extras": "true", "include_variations": "true"}
    n = pagina = 0
    while url:
        d = get_json(url, tries=12, params=params)
        params = None
        pagina += 1
        if not d:
            if pagina > 1:      # elenco interrotto a meta': meglio fermarsi che indicizzare solo una parte senza accorgersene
                sys.exit(f"\nScryfall ha smesso di rispondere dopo {n} carte: l'elenco e' incompleto. Aspetta qualche minuto e rilancia "
                         "(oppure usa --bulk con il file All Cards).")
            break
        for c in d.get("data", []):
            m = meta_carta(c, lang)
            if m:
                n += 1
                yield m
        url = d.get("next_page") if d.get("has_more") else None
        if n and n // 1000 != (n - 175) // 1000:
            print(f"[{lang}] trovate {n} carte...", flush=True)


def carte_da_file(path, lang="en", dal=None, sets=None):
    """Come carte_scryfall, ma leggendo un file 'bulk data' di Scryfall gia' scaricato (nessuna chiamata all'API).
    Il file ha una carta per riga ("[", poi {...}, poi "]"), quindi si legge senza caricarlo tutto in memoria."""
    sets = {x.lower() for x in (sets or [])}
    n = 0
    with open(path, encoding="utf-8") as f:
        for riga in f:
            riga = riga.strip().rstrip(",")
            if not riga.startswith("{"):
                continue
            try:
                c = json.loads(riga)
            except ValueError:
                continue
            if c.get("lang") != lang or "paper" not in (c.get("games") or []):
                continue
            if dal and int(str(c.get("released_at") or "0")[:4] or 0) < int(dal):
                continue
            if sets and str(c.get("set", "")).lower() not in sets:
                continue
            m = meta_carta(c, lang)
            if m:
                n += 1
                yield m
    print(f"[{lang}] {n} carte lette dal file", flush=True)


def _scarica(c):
    p = percorso(c)
    if not p.exists():
        try:
            r = requests.get(c["image"], headers=HEADERS, timeout=60)
            if r.ok:
                p.write_bytes(r.content)
        except Exception:
            return None
    return c if p.exists() and p.stat().st_size > 1000 else None


def _salva_indice(lang, meta, E):
    f_emb, f_meta = file_indice(lang)
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / (f_emb + ".tmp"), "wb") as fh:
        np.save(fh, E)
    (DATA / (f_meta + ".tmp")).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(DATA / (f_emb + ".tmp"), DATA / f_emb)
    os.replace(DATA / (f_meta + ".tmp"), DATA / f_meta)


def _indicizza(model, lang, nuove, lock=None, ogni=4096):
    """Scarica le immagini e aggiunge le carte all'indice, salvando ogni 'ogni' carte (si puo' interrompere e riprendere)."""
    IMG.mkdir(parents=True, exist_ok=True)
    f_emb, f_meta = file_indice(lang)
    meta = json.loads((DATA / f_meta).read_text(encoding="utf-8")) if (DATA / f_meta).exists() else []
    E = np.load(DATA / f_emb) if (DATA / f_emb).exists() else None
    visti = {m["id"] for m in meta}
    unici = {}
    for c in nuove:
        unici.setdefault(c["id"], c)      # due stampe con lo stesso id (rarissimo): si tiene la prima
    nuove = [c for c in unici.values() if c["id"] not in visti]
    aggiunte = 0
    t0, gia_fatte = time.time(), 0
    for i in range(0, len(nuove), ogni):
        with ThreadPoolExecutor(8) as ex:
            blocco = [c for c in ex.map(_scarica, nuove[i:i + ogni]) if c]
        embs = []
        for j in range(0, len(blocco), 64):
            ims = []
            for c in blocco[j:j + 64]:
                try:
                    ims.append(Image.open(percorso(c)).convert("RGB"))
                except Exception:
                    ims.append(Image.new("RGB", (245, 342)))
            with (lock or nullcontext()):
                embs.append(model.encode(ims, batch_size=32, normalize_embeddings=True, convert_to_numpy=True))
            if sys.stdout.isatty():      # avanzamento in tempo reale nel terminale (non nei log di Docker)
                fatte = i + j + len(ims)
                el = max(time.time() - t0, 1e-3)
                vel = (fatte - gia_fatte) / el
                resto = (len(nuove) - fatte) / vel if vel else 0
                print(f"\r[{lang}] {fatte}/{len(nuove)} ({100 * fatte // max(len(nuove), 1)}%)  {vel:.0f} carte/s  "
                      f"mancano circa {int(resto // 3600)} h {int(resto % 3600 // 60)} min   ", end="", flush=True)
        if not embs:
            continue
        nuovo = np.vstack(embs)
        E = nuovo if E is None else np.vstack([E, nuovo])
        meta += [{k: v for k, v in c.items() if k != "image"} for c in blocco]
        _salva_indice(lang, meta, E)
        aggiunte += len(blocco)
        print(f"\n[{lang}] indicizzate {aggiunte}/{len(nuove)}" if sys.stdout.isatty() else f"[{lang}] indicizzate {aggiunte}/{len(nuove)}", flush=True)
    return aggiunte


def build_index(lang="en", dal=None, sets=None, bulk=None):
    print(f"Cartella dati: {DATA.resolve()}  (immagini in {IMG.resolve()})", flush=True)
    print("Carico PyTorch e il modello CLIP (la prima volta puo' richiedere un minuto o due)...", flush=True)
    from sentence_transformers import SentenceTransformer
    print(f"[{lang}] leggo l'elenco delle carte " + ("dal file" if bulk else "da Scryfall (qualche minuto)") + "...", flush=True)
    cards = list(carte_da_file(bulk, lang, dal, sets) if bulk else carte_scryfall(lang, dal, sets))
    if not cards:
        sys.exit("Scryfall non ha risposto o non ci sono carte con questi filtri. Riprova tra qualche minuto.")
    print(f"[{lang}] {len(cards)} carte da indicizzare (quelle gia' presenti vengono saltate).")
    n = _indicizza(SentenceTransformer("clip-ViT-B-32"), lang, cards)
    print(f"Indice [{lang}] pronto: {n} carte aggiunte.")


def aggiorna_indice(matcher, lang, lock=None, giorni=60):
    """Aggiunge all'indice le carte uscite (o annunciate) negli ultimi 'giorni' giorni. Restituisce quante."""
    since = (dt.date.today() - dt.timedelta(giorni)).isoformat()
    esistenti = {m["id"] for m in matcher.meta if m.get("lang") == lang}
    q = f"game:paper lang:{lang} date>={since}"
    url, params, nuove = f"{BASE}/cards/search", {"q": q, "unique": "prints", "include_extras": "true", "include_variations": "true"}, []
    while url:
        d = get_json(url, tries=3, params=params)
        params = None
        if not d:
            break
        for c in d.get("data", []):
            m = meta_carta(c, lang)
            if m and m["id"] not in esistenti:
                nuove.append(m)
        url = d.get("next_page") if d.get("has_more") else None
    return _indicizza(matcher.model, lang, nuove, lock) if nuove else 0


# ---------- 2) RICONOSCIMENTO ----------
class Matcher:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.carica()
        self.model = SentenceTransformer("clip-ViT-B-32")
        self._init_sift()

    def carica(self):
        """(Ri)carica gli indici dal disco."""
        Es, meta = [], []
        lingue = ["en"] + [p.stem[4:] for p in sorted(DATA.glob("emb_*.npy"))]
        for lang in lingue:
            f_emb, f_meta = file_indice(lang)
            if (DATA / f_emb).exists() and (DATA / f_meta).exists():
                Es.append(np.load(DATA / f_emb))
                for m in json.loads((DATA / f_meta).read_text(encoding="utf-8")):
                    m.setdefault("lang", lang)
                    meta.append(m)
                print(f"Indice caricato: {lang}")
        if not Es:
            sys.exit("Indice mancante: esegui prima  python magicscan.py index")
        self.E = np.vstack(Es)
        self.lang_arr = np.array([m["lang"] for m in meta])
        self.sid_arr = np.array([m["id"].rsplit("-", 1)[0] for m in meta])
        self.meta = meta

    def _init_sift(self):
        self.sift = cv2.SIFT_create(nfeatures=700)
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        self.bf = cv2.BFMatcher(cv2.NORM_L2)
        self.cache = OrderedDict()          # ultime 3000 carte in memoria
        (DATA / "sift").mkdir(parents=True, exist_ok=True)

    def _feat(self, bgr):
        g = cv2.cvtColor(cv2.resize(bgr, (W, H)), cv2.COLOR_BGR2GRAY)
        kp, des = self.sift.detectAndCompute(self.clahe.apply(g), None)
        pts = np.float32([k.pt for k in kp]).reshape(-1, 2) if kp else np.zeros((0, 2), np.float32)
        return pts, des

    def _carta(self, m):
        """Punti SIFT della carta di riferimento: memoria -> disco (magicdata/sift) -> calcolo e salvataggio."""
        key = (m.get("lang", "en"), m["id"])
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        f = DATA / "sift" / f"{key[0]}_{key[1]}.npz"
        feat = None
        try:
            with np.load(f) as z:
                feat = (z["p"], z["d"])
        except Exception:
            img = cv2.imread(str(percorso(m)))
            if img is not None:
                pts, des = self._feat(img)
                if des is not None:
                    feat = (pts, des.astype(np.uint8))
                    try:
                        tmp = f.with_suffix(".tmp")
                        with open(tmp, "wb") as fh:
                            np.savez(fh, p=pts, d=feat[1])
                        os.replace(tmp, f)
                    except Exception:
                        pass
        feat = feat or (None, None)
        self.cache[key] = feat
        if len(self.cache) > 3000:
            self.cache.popitem(last=False)
        return feat

    def _punti(self, q, m):
        """Quanti punti caratteristici coincidono (dopo RANSAC) tra la carta scansionata e la candidata."""
        p2, d2 = self._carta(m)
        p1, des1 = q
        if des1 is None or d2 is None or len(p1) < 8 or len(p2) < 8:
            return 0
        mt = self.bf.knnMatch(des1, d2.astype(np.float32), k=2)
        buoni = [x[0] for x in mt if len(x) == 2 and x[0].distance < 0.75 * x[1].distance]
        if len(buoni) < 8:
            return len(buoni)
        src = p1[[g.queryIdx for g in buoni]].reshape(-1, 1, 2)
        dst = p2[[g.trainIdx for g in buoni]].reshape(-1, 1, 2)
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
        return int(mask.sum()) if mask is not None else 0

    def match(self, bgr, lang=None, sid=None, n=3):
        """Restituisce le n migliori carte distinte, opzionalmente solo di una lingua e/o di un set (sid)."""
        mask = np.ones(len(self.meta), bool)
        if lang:
            mask &= self.lang_arr == lang
        if sid:
            mask &= self.sid_arr == sid
        idx = np.where(mask)[0]
        if len(idx) == 0:
            return []
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        imgs = [Image.fromarray(rgb), Image.fromarray(cv2.rotate(rgb, cv2.ROTATE_180))]
        v = self.model.encode(imgs, normalize_embeddings=True, convert_to_numpy=True)
        sims = np.full(len(self.meta), -1.0)
        sims[idx] = (self.E[idx] @ v.T).max(axis=1)
        corto = np.argsort(-sims)[:min(CANDIDATI, len(idx))]
        q = self._feat(bgr)
        ris = [{"m": self.meta[i], "sim": float(sims[i]), "inl": self._punti(q, self.meta[i])} for i in corto]
        if max(r["inl"] for r in ris) >= 10:
            ris.sort(key=lambda r: (r["inl"], r["sim"]), reverse=True)    # SIFT affidabile
        else:
            ris.sort(key=lambda r: r["sim"], reverse=True)                # foto troppo scarsa: solo CLIP
        uniche, visti = [], set()
        for r in ris:
            if r["m"]["id"] not in visti:
                visti.add(r["m"]["id"])
                uniche.append(r)
            if len(uniche) == n:
                break
        return uniche


def prezzo(card):
    """(valore, valuta) da una scheda dell'indice: Cardmarket (euro) se c'e', altrimenti TCGplayer (dollari)."""
    d = get_json(f"{BASE}/cards/{card['sf']}", tries=3, timeout=30) if card.get("sf") else None
    p = (d or {}).get("prices") or {}
    for k, v in (("eur", "EUR"), ("eur_foil", "EUR"), ("usd", "USD"), ("usd_foil", "USD")):
        if p.get(k):
            return float(p[k]), v
    return None, ""


def registra(matcher, bgr):
    top = matcher.match(bgr)
    best, second = top[0], top[1]
    if best["inl"] >= 15 and best["inl"] >= 1.5 * max(second["inl"], 1):
        stato = "ok"
    elif best["inl"] < 10 and best["sim"] >= SOGLIA_SCORE and best["sim"] - second["sim"] >= SOGLIA_MARGINE:
        stato = "ok"
    else:
        stato = "verifica"
    c = best["m"]
    val, valuta = prezzo(c)
    nuovo = not pathlib.Path(CSV_OUT).exists()
    with open(CSV_OUT, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if nuovo:
            w.writerow(["data", "id", "nome", "set", "numero", "lingua_indice", "similarita", "punti",
                        "valore", "valuta", "stato", "alternative"])
        alt = " | ".join(f"{r['m']['name']} ({r['m']['set']} {r['m']['number']})" for r in top[1:])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), c["id"], c["name"], c["set"], c["number"],
                    c.get("lang", "en"), f"{best['sim']:.3f}", best["inl"],
                    str(val).replace(".", ",") if val is not None else "", valuta, stato, alt])
    print(f"[{stato}] {c['name']} - {c['set']} #{c['number']} ({c.get('lang', 'en')})  "
          f"sim={best['sim']:.2f} punti={best['inl']}  valore={val} {valuta}")
    return c, best["sim"], val, valuta, stato


# ---------- 3) RILEVAMENTO CARTA ----------
def ordina(p):
    """Ordina i 4 angoli in senso orario partendo da quello in alto a sinistra."""
    c = p.mean(axis=0)
    p = p[np.argsort(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0]))]
    return np.roll(p, -int(p.sum(axis=1).argmin()), axis=0).astype("float32")


def _maschere(frame, sfondo=None):
    h, w = frame.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    ms = [cv2.Canny(gray, lo, hi) for lo, hi in ((30, 90), (50, 150), (80, 200))]
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ms += [otsu, 255 - otsu,
           cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 5)]
    # differenza di colore dal fondo, stimato dal bordo dell'immagine: vale per sfondi chiari, scuri o colorati
    lab = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    b = max(4, int(min(h, w) * 0.04))
    bordo = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                            lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    dist = np.linalg.norm(lab - np.median(bordo, axis=0), axis=2)
    ms += [((dist > t) * 255).astype(np.uint8) for t in (12, 20, 32)]
    # bordo giallo della carta: saturazione
    sat = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 1], (5, 5), 0)
    ms.append(cv2.threshold(sat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
    # contrasto locale amplificato (CLAHE): serve con bordi grigi su sfondi chiari
    eq = cv2.createCLAHE(3.0, (8, 8)).apply(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    ms += [cv2.Canny(cv2.GaussianBlur(eq, (5, 5), 0), lo, hi) for lo, hi in ((10, 30), (20, 60))]
    # differenza dallo sfondo vuoto memorizzato (se c'e'): trova la carta anche grigio su grigio
    if sfondo is not None:
        lb = cv2.cvtColor(cv2.GaussianBlur(cv2.resize(sfondo, (w, h)), (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
        d = lab - lb
        d -= np.median(d.reshape(-1, 3), axis=0)         # compensa variazioni globali di luce/esposizione
        dd = np.linalg.norm(d, axis=2)
        ms += [((dd > t) * 255).astype(np.uint8) for t in (8, 14, 24)]
    # bordi su ciascun canale colore (non solo sul grigio)
    ms.append(np.maximum.reduce([cv2.Canny(cv2.GaussianBlur(c, (5, 5), 0), 40, 120) for c in cv2.split(frame)]))
    return ms


def riduci_riflessi(img):
    """Cancella i riflessi del flash (macchie bianche isolate) con inpainting; ignora fondi bianchi che toccano i bordi."""
    h, w = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    s = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]
    n, lab, st, _ = cv2.connectedComponentsWithStats(((g >= 243) & (s < 45)).astype(np.uint8), connectivity=8)
    ok = [i for i in range(1, n) if 15 <= st[i][4] <= 0.05 * h * w and st[i][0] > 0 and st[i][1] > 0
          and st[i][0] + st[i][2] < w and st[i][1] + st[i][3] < h]
    if not ok:
        return img
    m = cv2.dilate(np.isin(lab, ok).astype(np.uint8) * 255, np.ones((7, 7), np.uint8))
    return cv2.inpaint(img, m, 3, cv2.INPAINT_TELEA)


def _cluster(off, ln, tol):
    cl = []
    for i in np.argsort(off):
        if cl and off[i] - cl[-1]["o"] < tol:
            c = cl[-1]
            c["o"] = (c["o"] * c["s"] + off[i] * ln[i]) / (c["s"] + ln[i])
            c["s"] += ln[i]
        else:
            cl.append({"o": float(off[i]), "s": float(ln[i])})
    return cl


def _contenuto(frame, q):
    """Vero se dentro il rettangolo c'e' qualcosa di diverso dal piano intorno (colore o texture): scarta le linee del tavolo."""
    h, w = frame.shape[:2]
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [q.astype(np.int32)], 255)
    inn = cv2.erode(m, np.ones((15, 15), np.uint8))
    ring = cv2.dilate(m, np.ones((41, 41), np.uint8)) & ~cv2.dilate(m, np.ones((9, 9), np.uint8))
    if not inn.any() or not ring.any():
        return False
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
    a, b = lab[inn > 0], lab[ring > 0]
    return bool(np.linalg.norm(a.mean(0) - b.mean(0)) > 6 or a.std(0).sum() > 1.8 * b.std(0).sum() + 6)


def _quad_da_linee(frame):
    """Ricostruisce il rettangolo dai segmenti dei bordi anche se interrotti (riflessi, bordo grigio su fondo chiaro)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    eq = cv2.createCLAHE(3.0, (8, 8)).apply(gray)
    ed = cv2.dilate(cv2.Canny(cv2.GaussianBlur(eq, (5, 5), 0), 15, 45), np.ones((3, 3), np.uint8))
    ls = cv2.HoughLinesP(ed, 1, np.pi / 180, 50, minLineLength=int(0.2 * min(h, w)), maxLineGap=int(0.05 * max(h, w)))
    if ls is None or len(ls) < 4:
        return None
    L = np.asarray(ls, dtype=np.float32).reshape(-1, 4)     # OpenCV 4 restituisce (N,1,4), OpenCV 5 (N,4)
    ang = np.degrees(np.arctan2(L[:, 3] - L[:, 1], L[:, 2] - L[:, 0])) % 180
    ln = np.hypot(L[:, 2] - L[:, 0], L[:, 3] - L[:, 1])
    hist = np.bincount((ang % 90).astype(int) % 90, weights=ln, minlength=90)
    phi = float(np.argmax(np.convolve(np.r_[hist[-4:], hist, hist[:4]], np.ones(7), "same")[4:-4]))
    r = np.radians(phi)
    u, v = np.array([np.cos(r), np.sin(r)]), np.array([-np.sin(r), np.cos(r)])
    mid = np.c_[(L[:, 0] + L[:, 2]) / 2, (L[:, 1] + L[:, 3]) / 2]
    dA = ((ang - phi + 90) % 180) - 90
    dB = ((ang - phi) % 180) - 90
    A, B = np.abs(dA) < 9, np.abs(dB) < 9
    if A.sum() < 2 or B.sum() < 2:
        return None
    cA, cB = _cluster(mid[A] @ v, ln[A], 8), _cluster(mid[B] @ u, ln[B], 8)
    best, best_s = None, 0
    for i in range(len(cA)):
        for j in range(i + 1, len(cA)):
            for k in range(len(cB)):
                for l in range(k + 1, len(cB)):
                    a1, a2, b1, b2 = cA[i]["o"], cA[j]["o"], cB[k]["o"], cB[l]["o"]
                    wd, ht = abs(a2 - a1), abs(b2 - b1)
                    if min(wd, ht) < 0.18 * min(h, w):
                        continue
                    rt = min(wd, ht) / max(wd, ht)
                    if not 0.62 < rt < 0.80:
                        continue
                    if min(cA[i]["s"], cA[j]["s"]) < 0.3 * ht or min(cB[k]["s"], cB[l]["s"]) < 0.3 * wd:
                        continue                      # ogni lato deve avere almeno un po' di bordo visibile
                    s = (cA[i]["s"] + cA[j]["s"] + cB[k]["s"] + cB[l]["s"]) * max(0.1, 1 - 4 * abs(rt - 0.716))
                    if s > best_s:
                        best_s = s
                        best = np.array([b * u + a * v for a, b in ((a1, b1), (a1, b2), (a2, b2), (a2, b1))], dtype=np.float32)
    return ordina(best) if best is not None and _contenuto(frame, best) else None


def trova_carta(frame, sfondo=None):
    """Prova piu' metodi e tiene il rettangolo piu' grande e piu' simile alle proporzioni di una carta (0.716).
    Se i contorni falliscono, ricostruisce il rettangolo dalle linee dei bordi."""
    frame = riduci_riflessi(frame)
    area_tot = frame.shape[0] * frame.shape[1]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    best, best_s = None, 0
    for m in _maschere(frame, sfondo):
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=2)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            a = cv2.contourArea(c)
            if a < 0.03 * area_tot or a > 0.95 * area_tot:
                continue
            rect = cv2.minAreaRect(c)
            w, h = rect[1]
            if min(w, h) < 1:
                continue
            r = min(w, h) / max(w, h)
            if 0.6 < r < 0.82 and a / (w * h) > 0.85:
                s = a * max(0.1, 1 - 4 * abs(r - 0.716))
                if s > best_s:
                    best, best_s = cv2.boxPoints(rect), s
    if best is not None:
        return ordina(best.astype("float32"))
    try:
        return _quad_da_linee(frame)
    except Exception:
        return None                       # il rilevamento non deve mai far fallire la richiesta


def raddrizza(frame, q):
    if np.linalg.norm(q[0] - q[1]) > np.linalg.norm(q[0] - q[3]):
        q = np.roll(q, -1, axis=0)                      # carta orizzontale -> verticale
    M = cv2.getPerspectiveTransform(q, np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
    return cv2.warpPerspective(frame, M, (W, H))


# ---------- 4) MODALITA' ----------
def riquadro(frame):
    fh, fw = frame.shape[:2]
    h = int(fh * 0.9)
    w = int(h * 0.716)
    return (fw - w) // 2, (fh - h) // 2, w, h


def esito(matcher, card):
    c, s, val, valuta, stato = registra(matcher, card)
    try:
        import winsound
        winsound.Beep(1000 if stato == "ok" else 500, 200)
    except Exception:
        pass
    return f"{c['name']} {val if val is not None else '?'} {valuta} [{stato}]"


def scan_webcam(camera=0):
    matcher = Matcher()
    cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    stabile, assente, pronta, ultimo, prev = 0, 0, True, "", None
    print("Appoggia una carta su sfondo scuro. Q = esci, SPAZIO = scansiona subito la carta dentro il riquadro bianco.")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Non riesco a leggere la webcam. Prova:  python magicscan.py scan --camera 1")
            break
        vista = frame.copy()
        x0, y0, w, h = riquadro(frame)
        cv2.rectangle(vista, (x0, y0), (x0 + w, y0 + h), (255, 255, 255), 1)
        q = trova_carta(frame)
        if q is None:
            assente += 1
            stabile, prev = 0, None
            if assente > 15:
                pronta = True
            cv2.putText(vista, "Nessuna carta rilevata", (10, frame.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            assente = 0
            cv2.polylines(vista, [q.astype(int)], True, (0, 255, 0), 2)
            stabile = stabile + 1 if prev is not None and np.abs(q - prev).max() < 8 else 0
            prev = q
            if pronta and stabile >= 10:
                ultimo = esito(matcher, raddrizza(frame, q))
                pronta = False
        cv2.putText(vista, ultimo, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow("magicscan", vista)
        tasto = cv2.waitKey(1) & 0xFF
        if tasto in (ord("q"), 27):
            break
        if tasto == ord(" "):                            # scansione manuale del riquadro bianco
            ultimo = esito(matcher, cv2.resize(frame[y0:y0 + h, x0:x0 + w], (W, H)))
    cap.release()
    cv2.destroyAllWindows()


def scan_cartella(cartella):
    matcher = Matcher()
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    for p in sorted(pathlib.Path(cartella).iterdir()):
        if p.suffix.lower() not in exts:
            continue
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        q = trova_carta(img)
        card = raddrizza(img, q) if q is not None else cv2.resize(img, (W, H))
        print(p.name, end=" -> ")
        registra(matcher, card)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("index"); i.add_argument("--lang", default="en"); i.add_argument("--dal", type=int); i.add_argument("--set", default=""); i.add_argument("--bulk", help="file bulk data di Scryfall gia' scaricato (evita l'API)")
    s = sub.add_parser("scan"); s.add_argument("--camera", type=int, default=0)
    f = sub.add_parser("folder"); f.add_argument("path")
    a = ap.parse_args()
    if a.cmd == "index":
        build_index(a.lang, a.dal, [x for x in a.set.split(",") if x] or None, a.bulk)
    elif a.cmd == "scan":
        scan_webcam(a.camera)
    else:
        scan_cartella(a.path)
