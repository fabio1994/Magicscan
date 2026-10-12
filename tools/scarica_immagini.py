"""
Scarica su un PC le immagini delle carte Magic (da Scryfall) con gli stessi nomi che usa Magicscan.
Poi si copiano sul server e 'magicscan.py index' non le riscarica (vedi README.md).

Serve solo Python 3 e:   pip install requests

Esempi:
    python tools/scarica_immagini.py                          # inglese + italiano -> C:\\MagicImmagini (Windows) o ./MagicImmagini
    python tools/scarica_immagini.py --dest D:\\img            # altra cartella
    python tools/scarica_immagini.py --lang en                # solo inglese
    python tools/scarica_immagini.py --piccole                # immagini piccole (~1,5 GB invece di ~8 GB)
    python tools/scarica_immagini.py --bulk all-cards.jsonl   # elenco letto da un file, senza l'API

Se l'API di Scryfall risponde 429 (troppe richieste) per ore, scarica dal browser il file "All Cards" da
https://scryfall.com/docs/api/bulk-data (server diverso, nessun limite) e passalo con --bulk.
Si puo' interrompere (Ctrl+C) e rilanciare: riprende da dove era arrivato.
"""
import argparse, json, os, pathlib, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

API = "https://api.scryfall.com"
HEADERS = {"User-Agent": "Magicscan/1.0 (collezione personale)", "Accept": "application/json;q=0.9,*/*;q=0.8"}


def numero_sicuro(cn):        # identico a magicscan.py
    return (re.sub(r"[^A-Za-z0-9]", lambda m: f"u{ord(m.group()):x}", str(cn or "")) or "0").lower()


def voce(c, lang, size):      # identico a magicscan.meta_carta (solo id e immagine)
    if c.get("digital") or c.get("image_status") in ("missing", "placeholder") or not c.get("set"):
        return None
    iu = c.get("image_uris") or ((c.get("card_faces") or [{}])[0].get("image_uris") or {})
    url = iu.get(size) or iu.get("normal")
    if not url:
        return None
    cid = f"{c['set']}-{numero_sicuro(c.get('collector_number'))}"
    return cid, url, (f"{cid}.jpg" if lang == "en" else f"{lang}_{cid}.jpg")


def get_json(url, params=None):
    for t in range(8):
        attesa = 3 * (t + 1)
        try:
            time.sleep(0.2)
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code in (429, 403, 503):
                attesa = max(attesa, int(r.headers.get("Retry-After", 0) or 0), 30 * (t + 1))
                print(f"  Scryfall risponde {r.status_code} (troppe richieste): pausa di {attesa} s", flush=True)
                time.sleep(attesa)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  errore ({e.__class__.__name__}: {str(e)[:120]}), riprovo tra {attesa} s", flush=True)
            time.sleep(attesa)
    return None


def elenco(lang, size, dal):
    q = f"game:paper lang:{lang}" + (f" year>={dal}" if dal else "")
    url, params, visti, out = f"{API}/cards/search", {"q": q, "unique": "prints", "order": "set",
                                                      "include_extras": "true", "include_variations": "true"}, set(), []
    stampato = 0
    while url:
        d = get_json(url, params)
        params = None
        if not d:
            print("  Scryfall non ha risposto: elenco incompleto, rilancia lo script piu' tardi.")
            break
        for c in d.get("data", []):
            v = voce(c, lang, size)
            if v and v[2] not in visti:
                visti.add(v[2])
                out.append(v)
        if len(out) - stampato >= 5000:
            stampato = len(out)
            print(f"  [{lang}] elenco: {len(out)} carte", flush=True)
        url = d.get("next_page") if d.get("has_more") else None
    return out


def elenco_file(path, lang, size, dal):
    """Legge l'elenco da un file 'bulk data' di Scryfall gia' scaricato (nessuna chiamata all'API).
    Il file ha una carta per riga ("[", poi {...}, poi "]"), quindi si legge riga per riga senza caricarlo tutto."""
    visti, out = set(), []
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
            if dal and int(str(c.get("released_at") or "0")[:4] or 0) < dal:
                continue
            v = voce(c, lang, size)
            if v and v[2] not in visti:
                visti.add(v[2])
                out.append(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=r"C:\MagicImmagini" if os.name == "nt" else "MagicImmagini")
    ap.add_argument("--lang", default="en,it")
    ap.add_argument("--dal", type=int, help="solo carte uscite da questo anno")
    ap.add_argument("--bulk", help="file JSON 'All Cards' o 'Default Cards' scaricato da scryfall.com/docs/api/bulk-data (evita l'API)")
    ap.add_argument("--piccole", action="store_true")
    ap.add_argument("--thread", type=int, default=8)
    a = ap.parse_args()
    dest = pathlib.Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    size = "small" if a.piccole else "normal"
    tot = ok = gia = err = 0
    lock = threading.Lock()
    for lang in [x.strip() for x in a.lang.split(",") if x.strip()]:
        print(f"[{lang}] leggo l'elenco delle carte da Scryfall (qualche minuto)...", flush=True)
        carte = elenco_file(a.bulk, lang, size, a.dal) if a.bulk else elenco(lang, size, a.dal)
        print(f"[{lang}] {len(carte)} immagini da controllare in {dest}", flush=True)
        t0 = time.time()

        def scarica(v):
            nonlocal ok, gia, err, tot
            p = dest / v[2]
            if p.exists() and p.stat().st_size > 1000:
                with lock:
                    gia += 1
                    tot += 1
                return
            for t in range(4):
                try:
                    r = requests.get(v[1], headers=HEADERS, timeout=60)
                    if r.ok and len(r.content) > 1000:
                        tmp = p.with_name(p.name + ".tmp")
                        tmp.write_bytes(r.content)
                        os.replace(tmp, p)
                        with lock:
                            ok += 1
                        break
                except Exception:
                    pass
                time.sleep(2 * (t + 1))
            else:
                with lock:
                    err += 1
            with lock:
                tot += 1
                if tot % 1000 == 0:
                    print(f"  {tot} controllate: {ok} scaricate, {gia} gia' presenti, {err} errori "
                          f"({(ok / max(time.time() - t0, 1)):.1f} img/s)", flush=True)

        with ThreadPoolExecutor(a.thread) as ex:
            list(ex.map(scarica, carte))
    print(f"FINITO: {ok} scaricate, {gia} gia' presenti, {err} errori. Cartella: {dest}")
    if err:
        print("Rilancia lo script: riprova solo quelle mancanti.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrotto: rilancia lo script per riprendere.")
