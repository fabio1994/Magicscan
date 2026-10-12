# Magicscan

Catalogo personale di carte **Magic: The Gathering** che si usa dal telefono: inquadri una carta con la fotocamera, l'app la riconosce, la salva nella tua collezione e ne mostra il prezzo. Gira sul tuo server di casa (NAS, Raspberry Pi, mini PC) dentro Docker.

> **English summary.** Free for non-commercial use with attribution (see [LICENSE](LICENSE)). Self-hosted web app that recognises Magic: The Gathering cards from a phone camera (CLIP embeddings + SIFT matching against Scryfall images), keeps one collection per user, tracks prices (Scryfall / TCGplayer / Cardmarket) and can optionally list duplicates on CardTrader. Runs in Docker on x86-64 and ARM64 (Synology/QNAP NAS, Raspberry Pi 4/5 with a 64-bit OS). The interface is in Italian. Follow the steps below; the commands are the same in any language.

> **Progetto non ufficiale.** Non è affiliato né approvato da Wizards of the Coast, Scryfall o CardTrader. *Magic: The Gathering* è un marchio di Wizards of the Coast. Vedi [Note legali](#note-legali).

## Indice

1. [Cosa fa](#cosa-fa)
2. [Come funziona](#come-funziona)
3. [Requisiti](#requisiti)
4. [Installazione rapida (qualsiasi server con Docker)](#installazione-rapida)
5. [Creare l'indice delle carte](#creare-lindice-delle-carte)
6. [Installazione su NAS Synology](#installazione-su-nas-synology)
7. [Installazione su Raspberry Pi](#installazione-su-raspberry-pi)
8. [Utenti, login e codici invito](#utenti-login-e-codici-invito)
9. [HTTPS e reverse proxy (necessari per la fotocamera)](#https-e-reverse-proxy)
10. [Uso quotidiano](#uso-quotidiano)
11. [Configurazione](#configurazione)
12. [Aggiornare, backup e ripristino](#aggiornare-backup-e-ripristino)
13. [Tab Vendi (CardTrader)](#tab-vendi-cardtrader)
14. [Problemi comuni](#problemi-comuni)
15. [Struttura del repository e test](#struttura-del-repository-e-test)
16. [Note legali](#note-legali)

## Cosa fa

- **Riconoscimento da fotocamera** della carta, in qualsiasi lingua indicizzata (inglese, italiano e altre: fr, de, es, pt, ja, ko, ru, zhs, zht).
- **Collezione** con quantità, lingua, condizione (NM, LP, MP, HP, DMG) e finitura (Non-foil, Foil, Etched). Esporta in CSV/Excel.
- **Prezzi** da Scryfall (TCGplayer in dollari, Cardmarket in euro), aggiornati ogni giorno, con storico per carta e totale della collezione.
- **Set e carte mancanti**: avanzamento per set e elenco di ciò che ti manca.
- **Più utenti**: ogni persona ha la propria collezione; si entra con un codice invito che genera l'amministratore.
- **Vendita su CardTrader** (facoltativa e spenta di default): propone il prezzo consigliato per le copie doppie e le pubblica.

## Come funziona

- **Backend:** Flask + gunicorn, database SQLite, tutto in un solo container.
- **Riconoscimento:** per ogni carta si calcola un'impronta con il modello CLIP (`clip-ViT-B-32`) dalle immagini ufficiali di Scryfall. Una foto viene confrontata con l'indice e i migliori candidati sono ricontrollati con SIFT sull'intera carta.
- **Dati:** elenco carte, immagini e prezzi arrivano dall'API pubblica di Scryfall (gratuita, senza chiave). Nessun dato lascia il tuo server, salvo le richieste a Scryfall e, se la attivi, a CardTrader.
- **Prezzi condivisi:** il prezzo appartiene alla carta, non all'utente; l'aggiornamento giornaliero lo scarica una volta per tutti (richieste raggruppate a 75 carte). Il pulsante "Aggiorna prezzi" è limitato a una volta ogni 30 minuti.

## Requisiti

| | Minimo | Consigliato |
|---|---|---|
| Architettura | x86-64 oppure ARM64 (64 bit) | |
| Software | Docker con il plugin Compose (`docker compose`) | |
| RAM libera | 2 GB (indice ridotto) | 4 GB |
| Spazio | 2 GB (immagini `small`) | 12 GB (immagini `normal`, inglese + italiano + indice) |
| Rete | accesso a Internet in uscita (Scryfall, Hugging Face) | |

Per usare la fotocamera dal telefono serve un indirizzo **HTTPS** ([vedi sotto](#https-e-reverse-proxy)).

Non servono GPU né chiavi API. Il modello CLIP (circa 600 MB) viene scaricato dal container al primo utilizzo.

## Installazione rapida

Questi passaggi valgono per qualunque server con Docker (NAS, Raspberry Pi, VPS, PC Linux).

```bash
git clone https://github.com/TUO-UTENTE/magicscan.git
cd magicscan
mkdir -p magicdata/img        # su alcuni NAS la cartella deve esistere prima dell'avvio
docker compose build
```

La costruzione dell'immagine scarica PyTorch e le altre librerie (alcuni minuti, e su Raspberry Pi anche più di un quarto d'ora).

**Prima di avviare serve almeno un indice**, perché l'app non parte senza. Per provare subito, indicizza un solo set (qualche minuto):

```bash
docker compose run --rm --no-deps magicscan python magicscan.py index --set m21
```

Poi avvia:

```bash
docker compose up -d
docker compose logs --tail=30
```

Apri `http://IP-DEL-SERVER:8086` dal browser. Per cambiare la porta crea un file `.env` accanto a `docker-compose.yml` con `MAGIC_PORT=8187` (o il numero che preferisci) e rilancia `docker compose up -d`.

Poi crea l'amministratore ([vedi sotto](#utenti-login-e-codici-invito)) e, quando vuoi, passa all'indice completo.

## Creare l'indice delle carte

Il riconoscimento confronta la foto con un indice delle carte, che si calcola una volta sola. Le stampe cartacee sono circa 100.000 in inglese più quelle nelle altre lingue.

Il calcolo è pesante: **conviene farlo su un PC** invece che sul NAS o sul Raspberry Pi (su un PC normale circa 10-20 carte al secondo, quindi 2-4 ore per l'inglese; su un NAS può richiedere un giorno o più). Poi si copiano sul server i file ottenuti.

### Opzione A: sul server (piccoli indici, prove)

```bash
# solo alcuni set (codici Scryfall)
docker compose run --rm --no-deps magicscan python magicscan.py index --set mh3,otj,blb
# solo le carte uscite dal 2018 in poi
docker compose run --rm --no-deps magicscan python magicscan.py index --dal 2018
# una lingua diversa dall'inglese
docker compose run --rm --no-deps magicscan python magicscan.py index --lang it --dal 2018
docker compose restart
```

Si può interrompere (Ctrl+C) e rilanciare: l'indice viene salvato ogni 4096 carte e si aggiungono solo le carte nuove.

### Opzione B: sul PC (consigliata per l'indice completo)

**1. Scarica le immagini** (circa 8 GB per l'inglese con le immagini `normal`; l'italiano ne aggiunge un'altra parte). Serve Python 3.10+:

```bash
pip install requests
python tools/scarica_immagini.py --dest D:\img          # Windows (cartella a piacere)
python tools/scarica_immagini.py --dest ~/img           # Linux/macOS
```

Per impostazione predefinita scarica inglese e italiano. Opzioni utili: `--lang en` (solo inglese), `--lang en,it,de,fr`, `--piccole` (immagini piccole, circa 1,5 GB), `--dal 2018`, `--thread 4` (meno richieste in parallelo). Si può interrompere e rilanciare: salta i file già presenti. Se alla fine restano errori, rilancia lo stesso comando.

Se Scryfall risponde `429` (troppe richieste) per molto tempo, scarica a mano dal browser il file **All Cards** da <https://scryfall.com/docs/api/bulk-data> (circa 2 GB, formato `.jsonl`) e aggiungi `--bulk percorso/del/file.jsonl`. Questo file serve anche per l'indice.

**2. Installa le librerie e crea l'indice sul PC:**

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

PowerShell (Windows):

```powershell
$env:MAGIC_DATA = "D:\"            # le immagini devono stare in D:\img, l'indice viene scritto in D:\
python magicscan.py index --bulk "C:\percorso\all-cards.jsonl"
python magicscan.py index --bulk "C:\percorso\all-cards.jsonl" --lang it
```

Linux/macOS:

```bash
export MAGIC_DATA=~                 # le immagini devono stare in ~/img
python magicscan.py index --bulk ~/all-cards.jsonl
python magicscan.py index --bulk ~/all-cards.jsonl --lang it
```

Senza `--bulk` l'elenco carte viene letto dall'API di Scryfall (qualche minuto in più, e con rischio di `429`). Nel terminale compare una riga di avanzamento con percentuale e tempo stimato. Alla fine nella cartella indicata da `MAGIC_DATA` ci sono `emb.npy`, `meta.json` e, per l'italiano, `emb_it.npy` e `meta_it.json`.

**3. Copia tutto sul server**, nella cartella `magicdata` accanto a `docker-compose.yml`:

- i file `emb*.npy` e `meta*.json` direttamente in `magicdata/`;
- le immagini in `magicdata/img/`.

Per le immagini (decine di migliaia di file piccoli) il modo più affidabile è un unico flusso `tar` via SSH, che si può anche riprendere. Da Linux/macOS o da `cmd` di Windows 10/11:

```bash
tar -cf - -C D:\img . | ssh UTENTE@IP-DEL-SERVER "tar -xf - -C /percorso/magicscan/magicdata/img"
```

Per interrompere e riprendere senza rimandare tutto, genera l'elenco dei file mancanti e passalo a `tar -T`. In alternativa usa `rsync -a --partial ~/img/ UTENTE@IP-DEL-SERVER:/percorso/magicscan/magicdata/img/` (Linux/macOS) oppure `robocopy` verso una cartella condivisa (Windows).

Gli indici si copiano con `scp` (su alcuni Synology serve l'opzione `-O`):

```bash
scp emb.npy meta.json emb_it.npy meta_it.json UTENTE@IP-DEL-SERVER:/percorso/magicscan/magicdata/
```

**4. Sul server:** `docker compose restart`. Nel log non deve più comparire "Indice mancante".

Dopo l'installazione l'app controlla da sola, ogni 7 giorni, le carte uscite negli ultimi 60 giorni e le aggiunge all'indice.

## Installazione su NAS Synology

Procedura per DSM 7 con Container Manager (nelle versioni più vecchie il pacchetto si chiama "Docker"). Serve un modello con processore Intel/AMD o ARM a 64 bit e almeno 4 GB di RAM.

1. In DSM installa **Container Manager** dal Centro pacchetti e abilita SSH (Pannello di controllo > Terminale e SNMP).
2. Crea una cartella condivisa o usa `docker`, per esempio `/volume1/docker/magicscan`, e copiaci il repository (con `git clone` da SSH oppure scaricando lo zip da GitHub e usando File Station).
3. Da SSH (`ssh utente@IP-DEL-NAS`, poi `sudo -i`):
   ```bash
   cd /volume1/docker/magicscan
   mkdir -p magicdata/img
   docker compose build
   docker compose run --rm --no-deps magicscan python magicscan.py index --set m21
   docker compose up -d
   ```
   Se `docker compose` non esiste, prova con `docker-compose` (con il trattino).
4. Se la porta 8086 è occupata crea un file `.env` con `MAGIC_PORT=8187`.
5. Crea l'indice completo sul PC e copialo ([vedi sopra](#creare-lindice-delle-carte)). Su Synology `scp` può richiedere `-O`.
6. Configura l'HTTPS con il Reverse Proxy di DSM ([vedi sotto](#https-e-reverse-proxy)).

Note: se l'avvio del container fallisce con "Bind mount failed ... does not exist", manca la cartella `magicdata` (punto 3). Gli utenti SSH senza cartella home vedono l'avviso "Could not chdir to home directory": è innocuo.

## Installazione su Raspberry Pi

L'app gira su **Raspberry Pi 4 o 5 con sistema a 64 bit** (Raspberry Pi OS 64-bit o Ubuntu Server arm64). Con il sistema a 32 bit PyTorch non è disponibile e l'installazione non riesce. La procedura usa le stesse immagini Docker multi-architettura e le stesse librerie del caso x86, ma non è stata verificata su ogni modello: se trovi un problema, apri una issue.

**Consigli per l'hardware**

- **RAM:** 4 GB o più. Con 2 GB funziona solo con un indice ridotto (per esempio `--dal 2015`) e con uno swap di almeno 2 GB. L'indice completo (inglese e italiano) occupa alcune centinaia di MB in RAM, più circa 1 GB per PyTorch e il modello.
- **Archiviazione:** usa un **SSD o un disco USB** per `magicdata`. Le immagini sono decine di migliaia di file e la scheda SD si consuma e rallenta; è meglio tenerci solo il sistema.
- **Indice:** non calcolarlo sul Raspberry Pi: farlo sul PC ([Opzione B](#opzione-b-sul-pc-consigliata-per-lindice-completo)) richiede ore invece di giorni.

**Procedura**

```bash
# 1. aggiorna il sistema e installa Docker (script ufficiale)
sudo apt update && sudo apt full-upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# esci e rientra in SSH perché il gruppo abbia effetto

# 2. (solo con 2 GB di RAM) aumenta lo swap a 2 GB
sudo dphys-swapfile swapoff
sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup && sudo dphys-swapfile swapon

# 3. scarica il progetto sul disco USB (esempio: montato in /mnt/ssd)
cd /mnt/ssd
git clone https://github.com/TUO-UTENTE/magicscan.git
cd magicscan
mkdir -p magicdata/img

# 4. costruisci l'immagine (può richiedere 15-30 minuti)
docker compose build

# 5. indice di prova con un solo set, poi avvio
docker compose run --rm --no-deps magicscan python magicscan.py index --set m21
docker compose up -d
docker compose logs --tail=30
```

Poi crea l'indice completo sul PC e copia `emb*.npy`, `meta*.json` e le immagini sul Raspberry Pi come descritto [sopra](#creare-lindice-delle-carte). Se usi `MAGIC_IMG=small` l'occupazione di spazio e il tempo di indicizzazione si riducono molto; ricorda di indicizzare con le stesse immagini.

Per raggiungere l'app da fuori casa e usare la fotocamera dal telefono serve l'HTTPS: sul Raspberry Pi la strada più semplice è **Caddy** (certificato automatico) oppure un tunnel come Tailscale o Cloudflare Tunnel ([vedi sotto](#https-e-reverse-proxy)).

## Utenti, login e codici invito

Finché non crei l'amministratore l'app è **aperta a chiunque la raggiunga**: fallo subito se è raggiungibile da Internet.

```bash
docker compose run --rm --no-deps magicscan python app.py --setpw
docker compose restart
```

Scrivi il nome utente (3-30 caratteri: lettere, numeri, `.`, `_`, `-`), premi Invio, poi la password (almeno 8 caratteri) e ripetila. Lancia il comando da solo, senza incollare altro nel terminale. Lo stesso comando cambia nome e password dell'amministratore.

Per aggiungere persone:

1. Entra come amministratore e apri **Utenti e codici invito**: nelle impostazioni dell'app oppure all'indirizzo `/admin`.
2. Premi **Genera codice**: vale 7 giorni e si usa una sola volta.
3. Passa il codice alla persona. Va su `/registrati`, sceglie nome utente e password e inserisce il codice. Entra subito con una collezione vuota.

Dalla pagina admin puoi anche revocare i codici non usati ed eliminare un utente (con la sua collezione). Ogni utente vede solo le proprie carte; indice, immagini e prezzi sono condivisi. Dopo 5 tentativi falliti l'accesso da uno stesso indirizzo è bloccato per 10 minuti (per il blocco corretto il reverse proxy deve inoltrare `X-Forwarded-For`, come negli esempi sotto). Non c'è il "reimposta password": se qualcuno la dimentica, elimina l'utente e invitalo di nuovo (perde la collezione, quindi esporta prima il CSV).

Se in passato usavi una versione con un solo utente, il vecchio login diventa automaticamente l'amministratore e le carte già salvate sono sue.

## HTTPS e reverse proxy

I browser concedono la fotocamera solo su pagine **HTTPS** (o su `localhost`). Davanti all'app serve quindi un reverse proxy con un certificato valido. Il proxy deve inoltrare a `http://IP-DEL-SERVER:8086` (o la porta scelta) con **timeout di lettura di almeno 180 secondi**, perché l'analisi di una foto può richiedere alcuni secondi.

**Synology DSM 7:** Pannello di controllo > Portale di accesso > Avanzate > Reverse Proxy > Crea.

- Origine: HTTPS, nome host `magic.tuodominio.it`, porta 443.
- Destinazione: HTTP, `localhost`, porta dell'app.
- Impostazioni personalizzate > Avanzate: timeout di lettura e invio a 180 secondi.
- Pannello di controllo > Sicurezza > Certificato > Configura: assegna alla voce un certificato Let's Encrypt (o wildcard) che copra il nome. Se hai già un'altra applicazione sulla porta 443, usa un sottodominio.

**Caddy** (certificato automatico, ottimo anche su Raspberry Pi):

```
magic.tuodominio.it {
    reverse_proxy IP-DEL-SERVER:8086
}
```

**Nginx:**

```nginx
server {
    listen 443 ssl;
    server_name magic.tuodominio.it;
    ssl_certificate     /percorso/fullchain.pem;
    ssl_certificate_key /percorso/privkey.pem;
    client_max_body_size 20m;
    location / {
        proxy_pass http://IP-DEL-SERVER:8086;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
    }
}
```

Se non vuoi aprire porte sul router, puoi usare **Tailscale** (rete privata, HTTPS con `tailscale serve`) o **Cloudflare Tunnel**.

Esponendo l'app a Internet attiva sempre il login e apri solo la porta 443.

## Uso quotidiano

- **Scansiona:** appoggia la carta su uno sfondo **chiaro e uniforme** (un foglio bianco o grigio chiaro): il bordo nero delle carte Magic si confonde con un tavolo scuro. Dalle impostazioni puoi memorizzare lo "sfondo vuoto" per aiutare il riconoscimento. L'app propone la carta; se sbaglia stampa o set usa **Correggi** o la ricerca per nome e filtra per set.
- **Conferma** lingua, condizione e finitura prima di salvare. Le finiture proposte sono solo quelle che esistono per quella stampa.
- **Prezzo:** mostra il prezzo senza salvare la carta.
- **Collezione:** filtra per nome, rarità, prezzo e condizione, modifica o elimina le righe, esporta in Excel/CSV, fai un backup immediato.
- **Set / Mancanti:** avanzamento per set e carte che ti mancano nei set che possiedi.

Sui prezzi: Scryfall ha **un solo prezzo per finitura**, riferito al Near Mint. L'app usa lo stesso valore per tutte le condizioni. Il totale in dollari usa TCGplayer; Cardmarket (euro) si aggiunge solo per le carte senza prezzo in dollari. I prezzi sono valori di riferimento, non offerte reali. Lo storico parte dal giorno in cui aggiungi la carta.

## Configurazione

Variabili d'ambiente (sezione `environment` di `docker-compose.yml`):

| Variabile | Valore | Effetto |
|---|---|---|
| `MAGIC_IMG` | `normal` (predefinito) o `small` | Dimensione delle immagini usate per l'indice: `normal` ≈ 8 GB e riconoscimento migliore, `small` ≈ 1,5 GB. Cambiandola vanno rigenerati le immagini e l'indice. |
| `MAGIC_VENDI` | `1` | Attiva la tab Vendi (CardTrader). |
| `MAGIC_DATA` | cartella | Solo per gli script sul PC: dove cercare `img/` e dove scrivere l'indice (predefinito `magicdata`). |
| `MAGIC_PORT` | numero | Nel file `.env`: porta sul server (predefinita 8086). |

Contenuto di `magicdata/` (non va mai cancellato durante gli aggiornamenti):

| File o cartella | Cosa contiene |
|---|---|
| `emb*.npy`, `meta*.json` | L'indice delle carte, uno per lingua |
| `img/` | Immagini delle carte (`id.jpg`, e `lingua_id.jpg` se non inglese) |
| `collezione.db` | Database SQLite: utenti, collezioni, prezzi, storico |
| `backup/` | Copia giornaliera del database (le ultime 14) |
| `secret.key` | Chiave dei cookie di sessione: non condividerla |
| `cardtrader.key` | Token CardTrader (solo se lo imposti) |
| `hf/` | Cache del modello CLIP (circa 600 MB) |
| `setimg/`, `sift/` | Cache di icone dei set e punti di riferimento |

Nomi dei file immagine: l'id di una carta è `codiceset-numero` in minuscolo (per esempio `m21-1`); i caratteri speciali nel numero sono codificati (`neo-12u2605` è la stampa `12★`).

## Aggiornare, backup e ripristino

**Aggiornare l'app:**

```bash
cd magicscan
git pull
docker compose build
docker compose up -d --force-recreate
```

`magicdata/` non viene toccata. Ricarica il browser con Ctrl+F5 per evitare la vecchia versione in cache. Un nuovo avvio con le nuove versioni aggiorna il database da solo.

**Backup:** l'app salva ogni giorno una copia del database in `magicdata/backup` e dall'app puoi lanciare un backup immediato. Per un backup completo copia l'intera cartella `magicdata` (esclusi, se vuoi, `img/` e `hf/`, che si possono rigenerare).

**Ripristino:** ferma il container, sostituisci `magicdata/collezione.db` con una copia di `backup/` e riavvia.

**Migrare su un altro server:** copia la cartella del progetto con `magicdata/` e rilancia `docker compose up -d --build`.

## Tab Vendi (CardTrader)

Spenta di default. La tab mostra le carte con **almeno due copie identiche** (stessa stampa, lingua, condizione e finitura), il blueprint CardTrader collegato tramite l'id Scryfall, il prezzo consigliato (l'offerta più bassa con la stessa lingua, condizione e finitura) e un pulsante per pubblicare. Una copia resta sempre in collezione; le foil *etched* si pubblicano a mano dal sito. Per attivarla:

1. Crea un token API dal tuo account CardTrader.
2. Salvalo senza mostrarlo a schermo:
   ```bash
   docker compose run --rm --no-deps magicscan python app.py --set-cardtrader-key
   ```
3. Decommenta `MAGIC_VENDI=1` in `docker-compose.yml` e ricrea il container: `docker compose up -d --force-recreate`.

Il token è unico per l'installazione, non per utente. Se un set non viene trovato puoi indicare l'espansione a mano in `magicdata/cardtrader_expansions.json`, per esempio `{"mh2": 11}` (codice set Scryfall → id espansione CardTrader).

## Problemi comuni

| Sintomo | Causa e soluzione |
|---|---|
| Nel log: `Indice mancante` e il container si riavvia di continuo | Non c'è ancora nessun indice in `magicdata`. Crealo o copialo ([indice](#creare-lindice-delle-carte)), poi `docker compose restart`. |
| `Bind mount failed ... magicdata does not exist` | Crea la cartella: `mkdir -p magicdata/img`. |
| Scryfall risponde `429` | Troppe richieste: aspetta alcuni minuti e rilancia; per gli script usa `--thread 4` o il file `--bulk`. Gli script ora fanno pause progressive da soli. |
| L'indice si ferma con "elenco incompleto" | Scryfall ha smesso di rispondere a metà elenco: riprova più tardi o usa `--bulk`. |
| La fotocamera non si apre | Serve HTTPS ([sezione](#https-e-reverse-proxy)); controlla anche i permessi del browser. |
| La carta non viene riconosciuta | Sfondo chiaro e uniforme, luce senza riflessi, carta intera nell'inquadratura. Prova a memorizzare lo sfondo vuoto. Controlla di avere indicizzato la lingua e il set della carta. |
| Errore `Permission denied` copiando i file | La cartella `magicdata/img` non appartiene all'utente che copia: `sudo chown -R UTENTE magicdata/img`. |
| Pagina vecchia dopo l'aggiornamento | Ricarica con Ctrl+F5 o svuota la cache del browser. |
| Memoria insufficiente su Raspberry Pi | Indice più piccolo (`--dal`), swap di 2 GB o immagini `small`. |
| `Could not chdir to home directory` su NAS | Avviso innocuo: l'utente SSH non ha la cartella home. |

Per vedere cosa succede: `docker compose logs -f --tail=100`.

## Struttura del repository e test

```
app.py               server web (Flask): API, utenti, prezzi, collezione
magicscan.py         riconoscimento e creazione dell'indice (riga di comando)
static/              interfaccia (index.html) e icone
tools/scarica_immagini.py   scarica le immagini sul PC
tests/               test con un Scryfall e un CardTrader simulati
Dockerfile, docker-compose.yml, requirements.txt
```

I test non usano la rete né i dati reali. Dopo `pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt` si lanciano dalla radice del progetto:

```bash
python tests/test_magic.py        # indice, id delle carte, prezzi, CardTrader simulato
python tests/test_utenti.py       # login, registrazione, collezioni separate, admin
```

Ogni test termina con `FALLITI: 0` se tutto va bene. Per provare l'app in locale senza Docker servono le stesse librerie e `gunicorn -b 127.0.0.1:8086 app:app` (con i dati in `magicdata/`).

Contributi e segnalazioni sono benvenuti tramite issue e pull request.

## Note legali

- Codice rilasciato con la **Non-Commercial Attribution License** (vedi [LICENSE](LICENSE), in inglese). In breve: puoi usarlo, copiarlo, modificarlo e ridistribuirlo gratis per scopi **non commerciali**, mantenendo il nome dell'autore, la licenza e un riferimento al repository originale, e indicando chiaramente le modifiche. Per qualunque uso commerciale serve il permesso scritto dell'autore (contatti nella licenza).
- Magicscan è un progetto non ufficiale: non è prodotto, approvato o sponsorizzato da Wizards of the Coast, Scryfall o CardTrader. *Magic: The Gathering*, i nomi, i simboli e le immagini delle carte sono marchi e opere di Wizards of the Coast LLC.
- I dati e le immagini delle carte vengono scaricati dall'API di Scryfall per uso personale: rispetta le [linee guida dell'API di Scryfall](https://scryfall.com/docs/api) (limite di richieste, intestazioni, nessuna rivendita dei dati) e la [politica sui contenuti dei fan di Wizards of the Coast](https://company.wizards.com/en/legal/fancontentpolicy). Le immagini delle carte non fanno parte di questo repository e non vanno ripubblicate.
- I prezzi sono solo indicativi e non costituiscono un'offerta o una consulenza.
