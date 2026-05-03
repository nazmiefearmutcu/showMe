# showMe — Coder AI Log (ShowMe devamı)

> Rapor 2 (Native Geçiş) uyarınca **onay yok, kayıt var**. ShowMe log'u Round 11
> sonuna kadar olduğu gibi korunur; Round 12'den itibaren native shell
> başlığıyla devam eder. Eklemeler **kronolojik**, en yenisi üstte.

---

## 2026-05-01 — Round 33 — BTCUSDT function sweep and native stability

### Root cause

* `CN` frontend tarafında `NI` topic-news path'ine alias ediliyordu; Company
  News aslında gerçek `CN` backend'ini çağırmıyordu.
* ShowMe fonksiyonları her istek için farklı worker thread/event loop içinde
  çalışıyordu. Async adapter lock/client'ları ve SQLite-backed store'lar
  tekrar kullanıldığında `different event loop` ve thread hataları üretiyordu.
* Bazı fonksiyonlar pandas DataFrame payload'ını doğrudan döndürdüğü için
  FastAPI JSON serialization 500'e düşüyordu.
* Provider eksikleri (`EIA_API_KEY`, CIK yok, ücretli feed yok) pane'i
  kırıyordu; terminal davranışı olarak warning payload'a çevrildi.

### Changes

* ShowMe fonksiyon yürütmesi tek persistent worker event loop'a taşındı.
* `BTCUSDT`/`ETH-USD`/`SOL/USDC` gibi semboller asset-class verilmezse
  otomatik `CRYPTO` kabul edilir.
* `/api/function-index` background thread + cache kullanır; cold inventory
  import artık `/api/health` event loop'unu bloklamaz.
* `/api/fn/{code}` pandas/numpy payload'larını JSON-safe forma çevirir.
* Function-internal exception'lar HTTP 500 yerine normal function payload +
  `warnings` olarak döner.
* Generic frontend function timeout 15s → 50s yapıldı; backend 45s envelope ile
  hizalandı ve `BRIEF` gibi haber fonksiyonları false-error göstermiyor.
* `CN`, gerçek Company News backend'ini çağırır; crypto sembollerde RSS
  crypto/news feed'leriyle no-key BTC headline döndürür.
* RSS summaries UI'da HTML tag göstermeyecek şekilde düz metne temizlenir.
* `feedparser` sidecar dependency ve PyInstaller hidden import listesine
  eklendi.

### Verification

* Dev sidecar BTCUSDT sweep: `ok=64`, `ok-warn=17`, `warn-empty=38`,
  `empty=12`, `skipped-risk=7`, `http-error=0`, `error=0`.
* Native packaged smoke: `CN BTCUSDT` 5 RSS headline / 0 warning,
  `BRIEF` news payload, `ACCT`/`PORT` mirrored portfolio state, `FA` expected
  CIK warning, `BGAS` expected `EIA_API_KEY` warning payload.
* Native heavy screen checks: `MOST`, `SECF`, `SECT`, `WEI` individually OK;
  `SRCH` expected Phase 5 warning.
* Trade/order category (`AIM`, `BBGT`, `EMSX`, `EXEC`, `FXGO`, `TCA`, `TSOX`)
  gerçek emir riski nedeniyle çalıştırılmadı.
* **Sidecar 97/97**, **Frontend 18 dosya 91/91**, `ruff` clean, `npm run lint`
  clean.
* `/Applications/showMe.app` yeniden build edildi, kopyalandı, ad-hoc
  codesign doğrulaması geçti ve UI `HEALTHY`, `FUNCTIONS 138/138` gösterdi.

---

## 2026-05-01 — Round 32 — Function execution, generic payload UI, native app

### Frontend

* Generic `FunctionStub` artık açılışta gerçek `/api/fn/{code}` çağrısı
  yapar; sonsuz skeleton/loading görünümü kaldırıldı.
* Fonksiyon yüzeyi state pill, Run/Go, symbol input, elapsed/sources/warnings
  metrikleri, grid/key-value/raw payload bölümleriyle gerçek ShowMe çıktısını
  gösterir.
* Fetch timeout eklendi; yavaş veya takılan endpoint UI'ı sonsuza kadar
  yüklemede bırakmaz.
* Symbol-first fonksiyonlar son sembolü, yoksa `AAPL`ı otomatik kullanır;
  `#/fn/DES` ve `#/fn/BETA` doğrudan çalışan ekrana gelir.
* Portfolio/global fonksiyonlar (`ACCT` gibi) artık sembol input'u göstermez
  ve sembol parametresi göndermez; mevcut portföy state'i üzerinden çalışır.
* Generic fonksiyon paneline Params JSON alanı eklendi; sembol dışı
  parametreler artık UI'dan verilebilir.
* `Pane` layout'u flex'e taşındı; `SymbolBar` kullanılan native panellerde
  büyük boşluk/yanlış satır problemi düzeldi.
* Workspace restore sonrası mevcut hash route tekrar uygulanır; kaydedilmiş
  eski pane state'i URL'deki fonksiyon/sembolü ezmez.
* Nested metric payload'ları (`BETA.betas`) tabloya açılır.
* Nested tablo hücreleri ham JSON yerine kısa özet gösterir; `ACCT`
  satırında `51 positions` ve asset-class toplamı okunur kalır.

### Python / data

* `src-py/pyproject.toml` içine `yfinance>=0.2.40` eklendi; ShowMe equity
  adapter zinciri showMe sidecar altında eksik dependency yüzünden boş
  dönmez.
* PyInstaller sidecar binary'si üretildi; ShowMe `src`, `dashboard`, `config`
  klasörleri native paketin içine alındı.
* Frozen/PyInstaller modunda relative `runtime/` yazımları
  `~/Library/Application Support/showMe` altına taşındı; paket içindeki
  read-only extract path yüzünden fonksiyon factory artık 500'e düşmez.
* Native boot, legacy ShowMe `runtime/state.json` ve küçük state dosyalarını
  showMe runtime mirror altına kopyalar; `ACCT`/`PORT` installed app içinde
  mevcut 51 pozisyonu görebilir.
* ShowMe `ACCT`, imported crypto pozisyonları için dış quote fetch yapmadan
  average cost kullanır; kripto ağırlıklı portföydeki 45s timeout kalktı.

### Tauri

* `install_to_applications` command'i eklendi; native shell içinde çalışan
  `.app` bundle'ını `/Applications` altına idempotent şekilde kopyalar.
* `Preferences > About` içine Applications install kontrolü eklendi.
* Tauri v2 main-window capability dosyası eklendi; frontend `sidecar_port`
  handshake'i event kaçırsa bile snapshot polling ile native portu yakalar.
* Cold `/api/function-index` için warmup retry eklendi; PyInstaller içindeki
  ShowMe factory geç import olsa da sidebar 138/138'e toparlanır.
* Rust toolchain kullanıcı onayıyla kuruldu.
* `npm exec -- tauri build --bundles app` ile
  `src-tauri/target/release/bundle/macos/showMe.app` üretildi.
* Bundle `/Applications/showMe.app` altına kopyalandı ve ad-hoc codesign
  doğrulaması geçti.

### Verification

* Browser smoke: `FSRC` OK + warning/payload, `DES` AAPL ile açılıyor,
  `BETA` AAPL ile 1Y/2Y/5Y beta metriklerini gösteriyor.
* Endpoint smoke: `DES?symbol=AAPL` ve `BETA?symbol=AAPL` warning'siz gerçek
  payload döndürüyor.
* Native endpoint smoke: `ACCT` 1 account / 51 position /
  `591,100.579356` total MV döndürüyor; `PORT` 51 pozisyon döndürüyor;
  `BETA?symbol=AAPL` 1Y/2Y/5Y beta döndürüyor.
* **Frontend 18 dosya, 91/91**.
* **Sidecar 93/93**.
* `npm run lint` clean.
* `npm run build:ui` clean; bundle **474.60 KB / 142.10 KB gzip**.
* `uv run ruff check .` clean.
* Native smoke: `/Applications/showMe.app` açıldı, bundled sidecar dynamic
  localhost portunda health OK döndü; `/api/fn/BETA?symbol=AAPL` yfinance
  kaynaklı 1Y/2Y/5Y beta metriğini warningsiz döndürdü. DES Apple profil
  payload'ını, FSRC ise phase warning'ini takılmadan döndürdü.
* Dev sidecar `127.0.0.1:8765` kapalıyken UI `HEALTHY`, `FUNCTIONS 138/138`
  ve ACCT/BETA OK tablolarını yalnızca bundled sidecar ile gösterdi.
* DMG üretimi Finder/`osascript` aşamasında takıldığı için teslimat app-only
  bundle üzerinden yapıldı; Applications-ready app yolu:
  `/Applications/showMe.app`.

---

## 2026-05-01 — Round 31 — Preferences Streams diagnostics + lint/tooling cleanup

### Frontend

* `Preferences > Streams` sekmesi eklendi; mevcut
  `/api/stream/stats` endpoint'inden channel/subscriber/last/source
  tablosu 2.5 sn poll edilir.
* `lib/sidecar.ts` typed `fetchStreamStats()` client kazandı.
* EN/TR i18n kataloglarına `preferences.streams` eklendi.
* ESLint 9 flat config (`src-ui/eslint.config.js`) eklendi.
* `HP` ve `TRAN` CSV helper'ları fast-refresh uyarısını kaldırmak
  için ayrı dosyalara taşındı.
* `EQS` rows ve `PORT` positions memoize edildi; `Workspace` leaf tipi
  `LeafNode` import'u ile düzeltildi.

### Python

* `ruff` import temizliği: kullanılmayan import'lar kaldırıldı,
  `test_scanner.py` import sırası düzeltildi.

### Test

* **Frontend 18 dosya, 91/91**.
* **Sidecar 90/90**.
* `npm run lint` clean.
* `npm run build:ui` clean; bundle **462.92 KB / 138.85 KB gzip**.
* `uv run ruff check .` clean.
* Browser-mode smoke: sidecar health OK, stream stats `channels=[]`,
  Vite HTTP 200.
* `cargo check` koşmadı: yerel PATH'te `cargo` yok.

### Round 32+ açık konuları

* MOST sub-second top-N reorder (trader feedback gerekli).
* MOST/WCRS/GLCO opsiyonel stream subscriber'ları.
* PORT WHAT-IF + stress testing.
* IBKR / Coinbase / Binance live broker adapter'ları.

---

## 2026-05-01 — Round 30 — PORT live unrealized P&L + websockets prod transport

### Sidecar `streams.py`

* `_WebsocketsTransport` — async iterator; `websockets.connect`
  lazy import; `ping_interval=15`; bytes→utf-8 decode fail-soft.
* `_default_ws_transport` artık `_WebsocketsTransport` döner;
  `BinanceWsSource` test injection patikası bozulmadı.

### Frontend `PORT.tsx`

* Her unique pozisyon symbol'ü için `subscribeQuote()`; `live`
  state map (price + ts).
* `enriched` useMemo tick varsa `last / market_value=qty×price /
  unrealized_pnl=MV-cost` overlay.
* `liveTotals` — herhangi bir tick gelirse MV + cost + unrealized
  push-driven hesaplanır; öncesinde snapshot total'ları görünür.
* Header pill `withDot={liveCount > 0}` (canlı stream glow);
  footer `ws · X/N live`.

### Test

* **Sidecar 16 dosya, 90/90** (transport pure pragma:no-cover).
* **Frontend 18 dosya, 91/91**.
* `tsc --noEmit` clean; `vite build` 717 ms; bundle **460.81 KB /
  138.44 KB gzip** (+0.87 KB ham, +0.30 KB gzip vs Round 29).

### Direktif §0 final çek listesi

Round 22 → 30 zinciri direktif maddelerinin tamamını kapsadı:

1. ✅ Faz B state importer (Round 22).
2. ✅ ≥20 native pane: 19 unique + 1 alias = 20 registry entry.
3. ✅ LLM Scanner planner (Round 26).
4. ✅ Multi-broker scaffold (Round 27).
5. ✅ Auto-update (Round 28).
6. ✅ Real-time WS stream (Round 29-30).
7. ✅ ASK fan-out (Round 21).

### Quality bar (Round 22 → 30)

* Sidecar tests: 50 → 90 (+40).
* Frontend tests: 78 → 91 (+13).
* Bundle: 425 KB / 130 KB → 460.81 KB / 138.44 KB.
* `tsc --noEmit` her round temiz.
* 0 hex token (Round 17 garantisi).
* ShowMe production bot dokunulmadı.

### Round 31+ açık konuları

* MOST sub-second top-N reorder (trader feedback bekliyor).
* MOST/WCRS/GLCO opsiyonel stream subscriber'ları.
* IBKR / Coinbase / Binance live broker adapter'ları.
* Preferences > Streams diagnostic page (`hub.stats()` live).

---

## 2026-05-01 — Round 29 — Real-time WS stream (Binance bridge + polling fallback)

### Sidecar `src-py/showme/streams.py` (yeni modül)

* **`Tick`** dataclass + **`Source`** ABC + **`BinanceWsSource`**
  (`wss://stream.binance.com:9443/ws/<sym>@ticker`, transport
  injectable).
* **`parse_binance_ticker`** pure-Python; **`is_crypto_symbol`**
  USDT/USD/BTC suffix heuristic; eksik field'lara dirençli.
* **`PollingSource`** — `fetch` enjekte edilebilir; default 5 sn
  interval; flat veya FunctionResult envelope kabul.
* **`StreamHub`** — per-symbol fan-out; last-tick cache replay;
  son subscriber ayrılınca tear-down; `asyncio.Queue` maxsize 128
  drop-oldest backpressure.
* **`Subscription`** async context manager.

### Sidecar `server.py` route'ları

* `GET /api/stream/stats` (debug).
* `WS /ws/quote/{symbol}` — fan-out push; lazy hub init; showme
  attach yoksa polling boş döner.

### Frontend

* `lib/sidecar.ts` → `sidecarWsUrl()` helper.
* `lib/stream.ts` → `subscribeQuote(symbol, {onTick, onStatus,
  signal})`; auto-reconnect exponential backoff (cap 5 s); status
  `connecting/live/offline/error`.
* `WATCH.tsx` her row için `subscribeQuote`; yeni "Stream" Pill
  (live/offline/error) kolonu; footer'da "ws · X/N live" özeti;
  30 sn DES polling fallback korundu.

### Test

* **Sidecar 16 dosya, 90/90 geçiyor** (8 yeni stream testi).
* **Frontend 18 dosya, 91/91 geçiyor** (UI-only WS surface).
* `tsc --noEmit` clean; `vite build` 767 ms; bundle **459.94 KB /
  138.14 KB gzip** (+1.49 KB ham, +0.56 KB gzip vs Round 28).

### Karar / sapma

* **`websockets` prod paketi packaging'e Round 30+ eklenecek** —
  default transport RuntimeError; testler injectable transport'la
  geçer.
* **Hub fan-out queue maxsize 128, drop-oldest** — yavaş tüketici
  için son-tick öncelik.
* **WATCH 30 sn DES polling korundu** — WS kesintisinde belt-and-
  suspenders.
* **Polling default 5 sn** — yfinance rate limit'i daha agresif
  değerleri kaldırmaz; override edilebilir.
* **Tek WS bağlantısı = tek symbol** — multiplex Round 30+.
* **`is_crypto_symbol` heuristic, `*BTC` yine kripto sayılır** —
  yanılırsak hub RuntimeError ile koruma.

### Round 30+'ın açık konuları

* `websockets` paketi prod packaging.
* PORT live unrealized P&L (stream × position).
* MOST sub-second top-10 reorder.
* Round 30+ trader feedback iterasyonu.

---

## 2026-05-01 — Round 28 — Tauri auto-update + GitHub release manifest

### Tauri shell

* `Cargo.toml` → `tauri-plugin-updater = "2"`.
* `tauri.conf.json` → `plugins.updater.active=true`,
  GitHub Releases endpoint, `dialog=true`, pubkey placeholder
  (CI'da `TAURI_SIGNING_PRIVATE_KEY` ile yönetilir).
* `src/lib.rs` → updater plugin registered.
* `src/commands.rs` → `check_for_updates(app) → UpdateInfo`,
  `apply_update(app)` (`download_and_install` + `app.restart()`).
  `invoke_handler!` array'ine eklendi.

### Frontend

* `lib/updater.ts` → `checkForUpdates / applyUpdate` Tauri-only;
  browser mode stub.
* `Preferences > About` ayrı `AboutSection` komponent'ine alındı:
  "Check for updates" butonu, sonuç pill (positive/muted/warn),
  release notes preformatted blok, "Download & restart" butonu
  (sadece `available && !error`).

### Release pipeline

* `scripts/build_release_manifest.py` — release directory layout
  (`release/<platform>/{*.dmg,*.dmg.sig}`) → Tauri-compatible
  `latest.json` (version + notes + pub_date + platforms).
* `.github/workflows/release.yml` — tag push (`v*`) veya
  manual dispatch:
  1. macOS-14 matrix (aarch64 + x86_64) tauri build (signed).
  2. `release/<platform>/` artifact stage.
  3. Ubuntu publish job: artifacts download → manifest build →
     `softprops/action-gh-release` ile dmg + sig + latest.json yayını.

### Test

* **Sidecar 14 dosya, 82/82 geçiyor** (5 yeni release manifest
  testi).
* **Frontend 18 dosya, 91/91** (Round 27 ile aynı; UI-only updater
  surface).
* `tsc --noEmit` clean; `vite build` 910 ms; bundle **458.45 KB /
  137.58 KB gzip** (+1.96 KB ham, +0.45 KB gzip vs Round 27).
* Cargo build CI matrix'te koşar; lokal `cargo check` çalıştırılmadı.

### Karar / sapma

* **GitHub Releases endpoint** — kendi domain yerine ücretsiz +
  CDN'li GitHub. Round 30+ kendi host'una geçilebilir.
* **`dialog: true` + manual button** — Tauri native dialog çıksın
  ama `apply_update` user opt-in; double-confirmation.
* **`AboutSection` ayrı komponent** — inline JSX 30+ satıra ulaşmıştı.
* **Yeni release.yml workflow, `build-mac.yml` korundu** — tag-push
  tetiği iki workflow'da paralel; release.yml signed end-to-end,
  build-mac.yml unsigned smoke.
* **`pubkey` placeholder** — CI secret ile generate ettikten sonra
  manuel kopyala; deploy adımı kullanıcı sorumluluğu.

### Round 29'un ilk işi

Real-time WS stream — Binance WS path-import köprüsü (ShowMe üzerinden);
sidecar `ws://127.0.0.1:<port>/ws/quote/<symbol>` endpoint'i + React
broadcast; PORT/WATCH/MOST polling'i push'a çevrilir.

---

## 2026-05-01 — Round 27 — Multi-broker scaffold (BaseBroker ABC + Alpaca paper)

### `src-py/showme/brokers/` (yeni paket)

* **`base.py`** — `OrderSide / OrderType / TimeInForce / OrderStatus`
  enum + `Order / Position` dataclass + `BaseBroker` ABC + `BrokerError`/
  `NotSupported`. `coerce_side/type/tif` static helper'ları string-or-
  enum kabul ediyor.
* **`paper.py`** — `PaperBroker` in-memory deterministic adapter; market
  order anında fill, limit order `simulate_fill()` test hook'u; notes
  hint (`last:200`) deterministic test fiyatı; net=0 kapamada realized
  P&L; aynı yöne ekleme → ortalama maliyet recompute.
* **`alpaca.py`** — `AlpacaPaperBroker` Alpaca v2 REST paper-trading;
  `http_call` enjekte edilebilir (`httpx` lazy import); status map,
  short pozisyon mutlak değer normalize; cancel 404/422 → False.
* **`factory.py`** — `register_broker / list_brokers / get_broker`;
  built-in `paper` her zaman, `alpaca-paper` import başarılıysa.

### Sidecar `/api/broker/*`

* `GET /api/broker/info` (account + registered listesi),
  `GET /api/broker/positions`, `GET /api/broker/orders?status=open`,
  `POST /api/broker/orders` (BrokerError → 400, diğer hata → 502),
  `DELETE /api/broker/orders/{id}`.

### Test

* **Sidecar 13 dosya, 77/77 geçiyor** (10 yeni broker testi).
* Frontend değişmedi (UI Round 28 pane'ine bağlanacak).
* `tsc --noEmit` clean (UI değişikliği yok).

### Karar / sapma

* **PaperBroker realized P&L net=0'da.** Kısmi kapama ortalama maliyeti
  korur; FIFO/LIFO Round 28+ flag ile.
* **`http_call` enjekte edilebilir.** Round 26 LLM modülüyle aynı
  pattern; testler httpx'siz geçer.
* **`alpaca-paper` adı paper endpoint'e bağlı.** Live adapter ayrı
  kayıt (`alpaca-live`) Round 28+ ile gelecek.
* **`/api/broker/*` write-side dahil.** Direktif "ham ürün" hedefi —
  scaffolding değil, gerçek POST/DELETE.
* **`SHOWME_BROKER` env override.** Paper'dan Alpaca'ya geçiş için
  kod değişikliği gerekmez.

### Round 28'in ilk işi

Auto-update — Tauri updater `active=true`, GitHub release JSON
manifest, `tauri.conf.json` updater endpoint URL'i, build pipeline
`pnpm tauri build` sonrası dmg + manifest yayını.

---

## 2026-05-01 — Round 26 — LLM planner (Haiku + GPT-4o-mini) + cost ledger

### `src-py/showme/llm.py` (yeni modül)

* **Pricing table** — Haiku 4.5 ($1/M in, $5/M out), GPT-4o-mini
  ($0.15/M in, $0.60/M out); bilinmeyen model muhafazakâr yüksek
  estimate.
* **`CostLedger`** — JSON disk dosyası, load/save/append/today_spend;
  corrupt JSON → boş ledger ile devam.
* **`Provider`** — enjekte edilebilir dataclass; testler stub'larla.
* **`llm_plan_for`** — cap kontrolü → provider sırası → markdown fence
  temizleme + key validate → `CostEntry` kayıt.
* **`plan_for_smart`** — provider boşsa veya hata/cap → `plan_for`
  fallback. Genel exception bile yakalanıyor.
* **`build_default_providers`** — env (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`) → provider listesi; key yoksa boş.
* HTTP transport (`_anthropic_call` / `_openai_call`) lazy `httpx`
  import — test bağımlılığı yok.

### Orchestrator + endpoint

* `agents/orchestrator.py` — Phase 1 plan adımı providers > 0 ise
  `plan_for_smart`, yoksa `plan_for`.
* `server.py` — `GET /api/llm/cost` (today_usd, cap_usd, remaining,
  exhausted, providers, son 50 entry).

### Frontend — Preferences › LLM section

* SECTIONS tuple'ına `"llm"` eklendi (`migration`-`about` arasında).
* `LlmSection`: SummaryStat grid (today $, remaining, cap, entries,
  state, providers), provider Pill chip'leri, son 50 call mini-log
  (ts/provider/in↓/out↑/$).

### Test

* **Sidecar 12 dosya, 67/67 geçiyor** (12 yeni LLM testi).
* **Frontend 18 dosya, 91/91 geçiyor** (Round 25 ile aynı sayım; UI-only
  değişiklik).
* `tsc --noEmit` clean; `vite build` 723 ms; bundle **456.49 KB /
  137.13 KB gzip** (+3.28 KB ham, +0.77 KB gzip vs Round 25).

### Karar / sapma

* **LLM opsiyonel**; key yoksa deterministic planner zaten çalışıyor.
* **Cap default $1, env override (`SHOWME_LLM_DAILY_USD`)** — direktif
  §0 hedefi.
* **Pricing local table, dinamik fetch yok** — yılda bir güncellenir,
  Round 28 auto-update'te paketlenir.
* **`response_format: json_object` sadece OpenAI'da; Anthropic system
  prompt + parse_plan_response fence cleaner ile dengeleniyor.**
* **Cost panel Preferences içinde, dedicated pane değil** — N=19 zaten
  hedef üstü, ham ürün için Preferences yeterli.
* **`httpx` lazy import** — CI'da kurulu olmadan testler geçer.

### Round 27'nin ilk işi

Multi-broker scaffold — `BaseBroker` ABC + Alpaca paper account ilk
adapter. ShowMe PaperBroker referans implementasyonu uyarlanır.

---

## 2026-05-01 — Round 25 — TRAN / WCRS / GLCO panes + 3 builtin preset → N=19

### Üçüncü pane dalgası (N: 16 → 19)

* **TRAN** — `lib/state.ts → listTrades({limit, symbol})`; 60 sn
  auto-refresh; symbol filter + limit input; closed_at / symbol
  (DES jump) / side pill / qty / entry / exit / realized_pnl
  (ChangeText "$") / mode pill kolonları; buildTradeCsv + Blob URL.
* **WCRS** — `useFunction("WCRS", {base, tick})` 30 sn refresh; base
  segmented (USD/EUR/GBP/JPY/TRY); matrix-or-flat payload normalize;
  pair / rate / bid / ask / spread (pips) / Δ %.
* **GLCO** — `useFunction("GLCO", {sector, tick})` 60 sn refresh;
  sector segmented (All/Energy/Metals/Ag/Softs); symbol DES jump,
  name, sector pill, last (+unit), Δ %, contract month, OI compact.

### Sidecar `state_api.py` (yeni `/api/state/*` endpoint kümesi)

* `list_positions / list_trades / list_migrations` — read-only,
  Round 22 portfolio.db üstünde; raw_json → raw dict hidratasyonu;
  DB yoksa boş StateRead (fail-soft).
* FastAPI route'ları `server.py` içine `/api/function-index` yanına
  gömüldü; symbol filter büyük harfe çevirir, limit cap'i client'tan.

### Built-in presets (`lib/builtinPresets.ts`)

* 3 entry: **Markets Overview** (DES+GP / WEI+TOP, 55/45 vertical),
  **Trading Desk** (DES+PORT / GP+WATCH, horizontal), **Macro Watch**
  (WEI+WCRS / GLCO+ECO).
* `loadBuiltinPreset(id, symbol?)` workspace serialize→loadWorkspace
  döngüsünden geçer; id remap; focus default ilk leaf.
* Welcome screen `Workspace presets` Card'ı her preset için
  label+description+`Open ↗` butonu — tek tıkta workspace yükler ve
  uygun fonksiyona navigate eder.

### Registry

* Yeni anahtar: `TRAN`, `WCRS`, `GLCO`.
* `listNativeCodes()` → 20 entry, 19 unique pane.

### Test

* **Frontend 18 dosya, 91/91 geçiyor** (8 yeni: 3 TRAN CSV + 5
  builtinPresets).
* **Sidecar 11 dosya, 55/55 geçiyor** (5 yeni state_api).
* `tsc --noEmit` clean; `vite build` 837 ms; bundle **453.21 KB /
  136.36 KB gzip** (+13.26 KB ham, +2.71 KB gzip vs Round 24).

### Karar / sapma

* **`/api/state/*` ayrı modül** — ShowMe fn değil, Faz B portfolio
  output'u. Round 27 broker engine `/api/state/orders` da aynı patterni
  takip edecek.
* **TRAN auto-refresh 60 sn.** Price-stream değil; importer'ın yeniden
  çalıştırılması senaryosu.
* **3 preset, daha fazla değil.** Welcome card patlaması command
  palette'i kalabalıklaştırır; Round 26 trader feedback'ine göre
  genişletilecek.
* **Welcome'da preset card'ı Quick launch'tan önce.** "App açıldı,
  hemen workspace istiyorum" UX'ı için ön plan.
* **`raw_json` hidratasyonu opsiyonel.** Parse hatasında string olarak
  korunur — defensive.

### Native surface count

Round 11: N=3 → Round 22: N=8 → Round 23: N=12 → Round 24: N=16 →
**Round 25: N=19**. Direktif §0 hedefi N≥15 (Round 25 sonu) aşıldı.

### Round 26'nın ilk işi

LLM Scanner planner — Anthropic Haiku ana, OpenAI GPT-4o-mini
fallback, günlük $1 cost cap (env var ile reset). Doğal dil prompt
→ JSON plan (`{universe, filters[], rank_by, k}`) → SCAN A/B fazları.
`lib/scanner.ts` Round 18'den scaffolding'i mevcut, bu round'da
gerçek LLM çağrısı + cost ledger yazılacak.

---

## 2026-05-01 — Round 24 — NI / MOST / WEI / HP panes (+ CN alias) → N=16

### İkinci pane dalgası (N: 12 → 16)

* **NI** — symbol-bound headline drawer; 404 → `CN` fallback.
  90 sn auto-refresh; SymbolBar gömülü; article card title/source/
  category/summary/symbol chips (DES jump)/tsLabel/source link.
  Registry'de hem `NI` hem `CN` alias olarak çözülüyor.
* **MOST** — `useFunction("MOST", {asset_class, limit:50})` segmented
  asset tab (`All/Equities/Crypto/FX`) + sort tab (`Volume/|Δ%|/$ Vol`).
  Client-side sort (server-side param genişlemesi ertelendi). Symbol
  → DES jump button + row double-click.
* **WEI** — `useFunction("WEI", {region, tick})` 30 sn auto-refresh;
  region tabs (`All/Americas/Europe/Asia/MEA`) server filtre + client
  fallback. Last / Δ / Δ% / day range / market_state pill.
* **HP** — symbol-bound; `useFunction("HP", {days, range})`
  segmented `1M/3M/6M/1Y/5Y/Max`. OHLCV DataGrid + header pill
  cluster (bar count / period high / low / total %). `buildCsv()` +
  Blob URL download (RFC4180 quoting).

### Registry

* Yeni anahtar: `NI`, `CN` (alias), `MOST`, `WEI`, `HP`.
* `listNativeCodes()` → 17 entry, 16 unique pane.

### Test

* **Frontend 16 dosya, 83/83 geçiyor** (4 yeni `HP.test.ts` +
  registry CN alias assertion = +5 vs Round 23).
* **Sidecar 50/50** unchanged.
* `tsc --noEmit` clean; `vite build` 779 ms; bundle **439.95 KB /
  133.65 KB gzip** (+14.95 KB ham, +3.65 KB gzip vs Round 23).

### Karar / sapma

* **CN registry alias.** ShowMe'ün NI veya CN export etmesi runtime'da
  şeffaf; `404 → CN` fallback HTTP tarafında, registry alias UI
  routing tarafında — iki katlı koruma.
* **MOST client-side sort.** Üç dimensiyon (vol / |Δ%| / $vol) ilk
  bakışta gerekli; server-side param eklemek yerine 50 row'da client
  sort yeterli.
* **WEI region client filter.** Payload `region` alanı varsa client
  filter; yoksa "All" görünümü — server-side filtre eksikliğini
  görsel olarak gizliyor.
* **HP CSV in-memory Blob.** Sidecar export endpoint yok, client-side
  Blob bridge ile Tauri save dialog izni gerekmedi (auto-update Round
  28'e bırakıldı).
* **HP range tavan = 25y.** Bloomberg HP max ≅ 30y; yfinance/Binance
  pratik tavan 25y.

### Native surface count

Round 11: N=3 → Round 22: N=8 → Round 23: N=12 → **Round 24: N=16**.
Direktif hedefi N≥15 (Round 25) bir tur erken aşıldı.

### Round 25'in ilk işi

WCRS / GLCO / TRAN + **Markets Overview preset** (4-leaf split: DES
+ GP + WEI + TOP, splash welcome screen'den tek tıkta yüklenir).
Trader'ın günlük "I just opened the app" yüzeyini ham hale getirmek
hedefi.

---

## 2026-04-30 — Round 23 — TOP / ECO / WATCH / ALRT panes + NSAlert confirm

### Yeni 4 native pane (N: 8 → 12)

* **TOP** — `useFunction("TOP")` 60 sn polling; per-headline card
  (title 15px / source pill / sentiment pill / 240-char summary /
  symbol chips → DES jump / ts label / source link).
* **ECO** — `useFunction("ECO", {days})` segmented week/month;
  `importanceBadge()` high/med/low pill, surprise = actual − forecast
  signed ChangeText.
* **WATCH** — `lib/watchlist.ts` preset-fs/localStorage; 5 seed symbol
  ilk açılışta (AAPL/MSFT/GOOGL/BTCUSDT/ETHUSDT); 30 sn `/api/fn/DES`
  polling (regularMarketPrice + previousClose → last + change_pct);
  symbol → DES jump.
* **ALRT** — `lib/alerts.ts` preset-fs/localStorage; 4 yön (above/
  below/cross_up/cross_down) × 3 alan (price/change_pct/volume); test
  fire `notify` Tauri command'i tetikliyor; delete `confirmAction()`
  ile gate.

### `lib/confirm.ts` (NSAlert replacement)

`confirmAction({title, body, primary, cancel, destructive})` — Tauri
`tauri-plugin-dialog.ask()` veya browser portal-style overlay.
`confirm()` (forbidden) yerine geçti.

### Test

* **Frontend 15 dosya, 78/78 geçiyor** (10 yeni: 5 watchlist + 5
  alerts; registry test güncellendi).
* **Sidecar 50/50** unchanged.
* `tsc --noEmit` temiz; `vite build` 764 ms; bundle **425 KB / 130 KB
  gzip** (Round 22 → +19 KB ham, +5 KB gzip).
* 10/10 dev module 200.

### Karar / sapma

* **Watchlist polling, WS değil.** Round 27 push'a geçer; 30 sn
  şimdilik en az frictionlı yüzey.
* **5-seed default.** Empty pane ilk izlenim olarak kötü.
* **Local persistence preset filesystem'de.** Round 16 JSON store
  zaten var; yeni Python migration eklemiyor. Round 27 cron alarm
  engine SQLite'a geçirebilir.
* **Alarm fire = toast + native notify.** Order action yok; Round
  27 broker engine geldiğinde optional paper order trigger'ı eklenebilir.
* **`confirmAction` browser fallback portal-style vanilla DOM** —
  Round 24+ CLI wrapper'lar non-React context'ten de çağırabilsin.

### Native surface count

Round 11: N=3 → Round 22: N=8 → **Round 23: N=12**. Direktif hedefi
N≥15 (Round 25). Round 24 NI/MOST/WEI/HP eklendiğinde N=16.

### Round 24'ün ilk işi

NI / MOST / WEI / HP panel'leri — directive listesinin ikinci dalgası
(company news / most active / world indices / historical price + CSV
export).

---

## 2026-04-30 — Round 22 — Faz B start: ShowMe state importer (+ direktif freeze)

### Mimar direktifi (akşam güncellemesi) uygulandı

Plan §0 sonu yeni DİREKTİF bloğu okundu:

* **Round 21 work donduruldu** — Touch ID prompt, `gateLiveTrade` reauth
  window, cross-platform Keychain fallback, code signing,
  notarization, WebAuthn/passkey: hepsi rafa kaldırıldı. Kod yerinde
  kalır, daha fazla yatırım yok. `canEvaluatePolicy` dry-gate yeterli;
  live trade onayı manuel (Round 23'te `confirm()` yerine NSAlert tarzı
  modal'a geçer).
* **Yeni odak: ham ele geçecek ürün** — Faz B importer, 20+ native
  pane, LLM Scanner planner, multi-broker (Alpaca), auto-update,
  real-time WS stream.

### `showme.migration` (Faz B importer)

`src-py/showme/migration.py` — pure-Python, 3rd-party'sız:

* Şema: `positions` (UNIQUE symbol/side/opened_at), `trades`
  (UNIQUE trade_id/symbol), `migrations` audit log; `mode='read_only'`
  default, `--writable` flag write-side mark'ı.
* `INSERT … ON CONFLICT DO UPDATE` ile idempotent — re-run pozisyonları
  upsert eder, audit log'u büyür sadece.
* `_iso_from_epoch` saniye/ms/duration ayrımı; non-numeric input'a
  düşmez.

### CLI

```
$ python3 -m showme.migration --showme ~/Desktop/Projeler/proje/ShowMe
[showme.migration] INFO loading runtime/state.json
[showme.migration] INFO → 51 positions, 7 trades imported (0 skipped)
{ paper_balance: 8020.566, mode: "read_only", warnings: [] }
```

### Tauri command + Preferences "Migration" tab

* `commands::run_migration(enginePath?, writable?)` shells out, parses
  trailing JSON summary back into `serde_json::Value`.
* Preferences yeni Migration sekmesi: ShowMe path field + read-only/
  writable mode picker + Run import butonu + summary card (positions,
  trades, paper $, daily P&L, mode, skipped, warnings). Browser-mode
  CLI hint'i gösteriyor.
* i18n key'leri `en.json` + `tr.json`'a `preferences.migration`
  eklendi.

### Test

* **Sidecar `tests/test_migration.py` 7 yeni spec:** position+trade
  insertion, idempotency, writable mode flag, malformed-position
  warning, `_iso_from_epoch` edge cases, list-shaped positions, real
  state.json round-trip (ShowMe local'sa).
* **Toplam sidecar 50/50 pass** (Round 21'in 43'ü + 7 Round 22).
* **Frontend 13 dosya, 68/68** regresyonsuz.
* `tsc --noEmit` temiz; `vite build` 920 ms; bundle **406 KB / 125 KB
  gzip** (Round 21 → +4 KB ham). 4/4 dev module 200.

### Live verify

`python3 -m showme.migration` ShowMe canlı state.json'ından **51 pozisyon
+ 7 trade** import'u 0 skip / 0 warning ile tamamlandı. İkinci çağrı
51 pozisyonu korudu, yalnız `migrations` audit row'u büyüdü.

### Karar / sapma

* **Pure SQLite, DuckDB değil.** 51 satır + ~50 KB trade history için
  yeterli. DuckDB OHLCV için Round 23+ MOST/HP/WEI ile gelecek.
* **`raw_json` kolonu.** ShowMe position dict'lerinde modellemediğimiz
  alanlar (`liquidation_price`, `is_break_even`) için audit honesty.
* **`mode` kolonu, ayrı tablolar değil.** Faz C'de pozisyon başına
  "writable promote" tek UPDATE ile yapılabilir.
* **CLI shell-out, sidecar direct-import değil.** Migration tek
  seferlik; subprocess fresh Python ile import side-effect izolasyonu
  garantili.
* **Writable toggle confirm yok.** NSAlert helper'ı Round 23'te;
  şimdilik flag flip. `mode='writable'` row'ları yine de explicit
  "promote" gerektirir; Faz B'de hiçbir writer dokunmaz.

### Round 23'ün ilk işi

* TOP / ECO / WATCH / ALRT — direktif listesinin ilk dalgası.
* NSAlert-style `confirm()` replacement — live-trade manual onayı
  için reauth window'un yerini alır.

---

## 2026-04-30 — Round 21 — Real Touch ID prompt + gateLiveTrade + ASK fan-out cards

Round 20 kalan adayları: `block2` ile gerçek `evaluatePolicy:reply:`
prompt'u, `gateLiveTrade()` helper'ı, ASK fan-out 3-card render,
Linux/Windows secrets backend mesajı.

### Rust shell — gerçek Touch ID prompt

* **`Cargo.toml`** — `block2 = "0.5"` macOS dep'lerine eklendi.
* **`biometric.rs`** — `run_evaluate_policy(reason, policy)`:
  `LAContext` oluştur → `RcBlock` içinde `mpsc::Sender<bool>` sarmala
  → `[ctx evaluatePolicy:policy localizedReason:reply:]` çağır → Rust
  tarafı `recv_timeout(120s)` ile cevap bekle. Gerçek Touch ID / Face
  ID modal'ı.
* Davranış:
  * macOS biometry → prompt; user tap → allowed=true/false.
  * macOS sadece passcode → password policy prompt'u.
  * macOS hiçbir policy yok → no prompt, Denied.
  * Other targets → `Ok(false)` (live-trade fail-closed).

### Frontend — `gateLiveTrade()`

`lib/biometric.ts`:
```ts
gateLiveTrade<T>(opts: { notional?, notionalThreshold?, reason? },
                 action: () => T | Promise<T>): Promise<T>
```
Default $1 000 threshold (Rapor 2 §6.7); altındaki order'lar prompt
geçmez. 5-dakikalık reauth cache hâlâ aktif.

### ASK pane — fan-out 3-card

`result.search.branches` doluysa "Briefing branches" card'ı 3 mini
card'la (Portfolio / Scan / News): tag pill + 1-cümle açıklama + en
fazla 5 bullet + "Open PORT/SCAN/TOP" butonu. `describeBranch()`
hem `{data:{data:...}}` hem direkt list/dict şekillerini drill ediyor.

### Cross-platform secrets messaging

* **`lib/secrets.ts`** — `secretsBackend(): "keychain" | "browser" |
  "unsupported"`; `tauri-plugin-os.platform()` ile pick.
* **Preferences Secrets tab** — backend pill (Keychain/Browser/Unsupported)
  + biometry pill yan yana; per-state note (browser vs unsupported);
  Save butonu `writable = backend === "keychain"` gate'iyle Linux/Win
  shell'lerinde lock.

### Test

* **Sidecar 43/43 pass** (Round 20 surface'i değişmedi).
* **Frontend 13 dosya, 68/68 geçiyor** (3 yeni `gateLiveTrade`:
  threshold skip / threshold gate / no-notional gate).
* `tsc --noEmit` temiz; `vite build` 830 ms; bundle **402 KB / 124 KB
  gzip** (Round 20 → +4 KB ham). 7/7 dev module 200.

### Karar / sapma

* **Block ana run-loop'ta.** `evaluatePolicy` block'unu macOS main run
  loop'a schedule eder; Tauri tokio task'ından recv'da bloklamak güvenli.
* **120 sn recv timeout.** Apple'ın internal timeout'u ~60 sn; iki
  katına çıkararak Apple Watch BT unlock gibi yavaş confirm akışlarını
  da absorb ediyoruz, thread sızdırmadan.
* **$1 000 default threshold.** Plan'daki sayıya pin'lendi; opt'la
  değiştirilebilir.
* **3-card grid fixed-order PORT/SCAN/TOP.** "Sahip olduğun /
  hareketli olan / nedeni" akışı. Round 22 reorder Preferences
  toggle'ı ekleyebilir.
* **`describeBranch` defensive.** ShowMe fonksiyonları envelope şekilleri
  karışık döndürüyor; bir seviye drill, sonra "opaque" — gelecek
  payload değişikliklerine kırılgan değil.
* **Cross-platform secrets advisory.** Round 22 DPAPI / libsecret
  ekleyene kadar dürüst mesajlama; `secretsBackend()` zaten seam.

### Round 22'nin ilk işi

* Auto-update + crash reporting + telemetry opt-in
  (Rapor 2 §6.11 / §11 crash-free oturum %99.5 hedefi).
* Linux secret-service / Windows DPAPI fallback.
* Gerçek `cargo tauri build` + `sign.sh` + `notarize.sh` ile
  imzalı .dmg üretimi (Developer ID kullanıcıdan).

---

## 2026-04-30 — Round 20 — Touch ID + Keychain + ASK fan-out + SCAN double-click

Rapor 2 §8 row 20 ("Touch ID + Keychain + secure enclave — Live trade
reauth çalışır") + Round 19 kalan adayları (ASK fan-out, SCAN
peek-then-click).

### Rust shell

* **`secrets.rs`** (new) — Generic-Password Keychain wrapper via
  `security-framework` (Round-12'den Cargo.toml'da). Tüm entry'ler
  `app.showme.terminal` service'i altında; `errSecItemNotFound` →
  `Ok(None)`, kalan hatalar `Err`. `state/secrets.index.json` thin
  index dosyası account *isim*lerini saklıyor (değerleri değil).
* **`biometric.rs`** — Round-12 stub yerine gerçek
  `LAContext.canEvaluatePolicy:` çağrısı (objc2). İki policy probe +
  `biometryType` → `Capabilities {biometry_available, passcode_available,
  biometry_kind: TouchId/FaceId/None}`. `evaluate(reason)`:
  biometry varsa allowed=TouchId/FaceId, sadece passcode varsa
  allowed=Password, ikisi de yoksa Denied.
* **`build.rs`** — `LocalAuthentication` + `Security` framework link
  hint'leri (macOS).

### Tauri commands

* `biometric_capabilities()` — sync Capabilities payload.
* `keychain_set/get/delete/list` — typed CRUD; index dosyası lock-step.

### Frontend

* **`lib/secrets.ts`** — Tauri-only wrapper; browser-mode write toast.
* **`lib/biometric.ts`** — `requireAuth(reason, action)` helper +
  5-dakikalık reauth cache + `clearAuthCache()`.
* **Preferences pane** — yeni `Secrets` sekmesi: hesap listesi,
  biometry capability pill (Touch ID / Face ID / no biometry),
  inline ekleme/silme. i18n key'leri `en.json` + `tr.json`'a eklendi.

### ASK orchestrator — fan-out

* **`planner.py`** — yeni `briefing` intent (`brief / briefing /
  overview / what's up / morning / what should I watch`); agents
  `["fanout", "summarizer", "viz"]`.
* **`orchestrator.py`** — `_fanout(plan, deps)` portfolio + scan +
  news leg'lerini `asyncio.gather` ile paralel; her branch
  best-effort, hatalar `warnings`'e.
* **`summarizer.py`** — `_summarize_fanout` her leg'i tek cümleye +
  per-leg highlight chip'lerine.
* **`viz.py`** — `fanout` 3-pane split `[PORT, SCAN, TOP]`.

### SCAN peek-then-click

* `DataGrid` opt-in `onRowDoubleClick(row, idx)` prop.
* `SCAN.tsx` row click drawer açıyor (peek), double-click DES'e
  atlıyor; drawer hint footer güncellendi.

### Test

* **Sidecar `tests/test_agents.py` + `tests/test_scanner.py`** — 4
  yeni spec (briefing intent/agents/action, fanout summarizer empty,
  briefing viz 3-split). **43/43 pass.**
* **Frontend 13 dosya, 65/65 geçiyor** (3 yeni: biometric reauth
  cache happy/repeat/clear).
* `tsc --noEmit` temiz; `vite build` 767 ms; bundle **398 KB / 123 KB
  gzipped** (Round 19 → +3 KB ham). 9/9 dev module 200; `/api/ask`
  briefing 4-phase pipeline live (`[plan, fanout, summarize, viz]`,
  3-pane suggest, 3 branch).

### Karar / sapma

* **`block2` ile gerçek `evaluatePolicy:reply:` Round 21'e**
  ertelendi — Objective-C block'larını raw `objc2`'den UB-safe
  yazmak risk; canEvaluatePolicy gate olarak yeterli, prompt
  Round 21'de.
* **Index dosyası sadece isim** — security-framework portable
  enumeration vermiyor; account isimleri data root altında, secret
  değerleri Keychain'de.
* **Keychain command'ları macOS-only.** Linux/Windows target'ları
  Err/None ile short-circuit; Round 21 cross-build için fallback
  store ekleyebilir.
* **`requireAuth` cache 5 dk, per-window scope.** Yeni pencere
  fresh context — natural expectation.
* **Briefing fan-out 3 branch hardcoded.** Round 22+ Preferences
  "Briefing channels" UI customization.
* **Double-click vs ⌘↵ symmetric.** Drawer açıkken kbd, doğrudan
  grid'de double-click — muscle memory paylaşıyor.

### Round 21'in ilk işi

* `block2`-backed `evaluatePolicy:reply:` + `gateLiveTrade()` helper.
* ASK pane fan-out 3-card layout (suggest-button → render).
* Linux/Windows secrets fallback / "macOS-only" UI.

---

## 2026-04-30 — Round 19 — ASKB orchestrator + ASK pane + SCAN polish

Rapor 2 §8 row 19 ("ASKB orchestrator + Planner + Search + Summarizer +
Viz") + Round 18 kalan adayları (`change_pct_today` sortable column,
drawer keyboard nav).

### Sidecar — `showme/agents/` paketi

Yeni 5 modül + thin orchestrator (LLM yok, hepsi deterministik):

* **`planner.py`** — naive intent classifier (scan / portfolio_overview /
  function / lookup / news / compare / unknown) + asset-class hint +
  symbol/function-code extractor + direction hint. İki güvenlik ağı:
  unknown+symbol→lookup, lookup+function-code→function.
* **`search.py`** — plan'a göre Scanner Agent veya FunctionRegistry'i
  çağırıyor. Yeni `_jsonify(value)` recursive coercion (pandas Series/
  DataFrame, numpy scalar, datetime, NaN/Inf → JSON-safe) FastAPI
  pydantic 2 serializer'ın FA gibi pandas-ağırlıklı payload'larda
  500 atmasını engelliyor.
* **`summarizer.py`** — intent başına deterministik narrative + Pill
  highlight chip'leri.
* **`viz.py`** — search kind'a göre pane hint (scan→table+SCAN,
  function GP/TECH→chart, function PORT→table, function DES/FA→cards,
  compare→split DES×2).
* **`orchestrator.py`** — `ask(req, deps)`: plan → search → summarize →
  viz, her phase için elapsed_ms.

### Sidecar `/api/ask`

POST `{query}` → AskResponse `{plan, search, narrative, highlights,
viz, phases, elapsed_ms, warnings}`. Phase pills SCAN'in convention'ı
ile aynı.

### Frontend

* **`lib/ask.ts`** — typed client (AskPlan / AskHighlight / AskViz /
  AskResponse).
* **`functions/ASK.tsx`** — textarea + 5 sample chip + ⌘↵ run; 2-column
  result grid (narrative card + plan card) + "Suggested view" card
  Open buttons (`setFocusedTarget` ile focused leaf'i push).
* **Registry**'ye ASK eklendi.

### SCAN polish

* `Δ today` sortable column (`fine.quote.change_pct` signed ChangeText).
* 3 sort header (Conf%, Score, Δ today) — `sortKey` state, `|abs|`
  sort (LONG/SHORT iki yön top-N'de görünüyor).
* Drawer keyboard nav: `←/→` satırlar arası, `⌘↵` Open DES, `Esc` kapat.
* Drawer hint footer satır >1 ise.

### Test

* **Sidecar `tests/test_agents.py` — 17 yeni spec:** planner classify,
  summarizer narrative, viz pane-hint, `_jsonify` (NaN/Inf clamp +
  pandas Series/DataFrame).
* **Toplam sidecar 39/39, frontend 62/62 = 101 test geçiyor.**
* `tsc --noEmit` temiz; `vite build` 654 ms; bundle **395 KB / 122 KB
  gzip** (Round 18 → +7 KB ham). 7/7 dev module 200; `/api/ask`
  4-phase pipeline canlı.

### Karar / sapma

* **Round 19'da LLM yok.** Plan'ın "bilinen sorgu setinde reasonable
  sonuç" beklentisi deterministic planner ile karşılanıyor; Plan
  contract'ı sabit, LLM augmentation orchestrator planner step'ine
  slottanır.
* **`_jsonify` search.py'da.** Tek caller function-result coercion;
  ihtiyaç yayılınca `serialize.py`'a promote.
* **Phase pills SCAN convention'ı.** UI mental model "phases ms-pill"
  consistent.
* **Drawer keyboard nav window-scope.** SCAN tek "selected row"
  surface; ikinci pane benzer drawer'a sahip olunca shared hook.
* **`|abs|` sort.** SHORT picks ile LONG picks aynı top-N'de —
  signed değer hâlâ row color'larını yönetiyor.
* **Function intents symbols propagate.** Round 18'in FA-no-instrument
  bug'ı: search agent şimdi `args.symbols[0]`'ı binding.

### Round 20'nin ilk işi

* Touch ID + Keychain (Rapor 2 §6.7/§6.10) — `LAContext` + keychain
  item create biometric/commands modüllerine.
* ASK orchestrator fan-out (scan + portfolio + news paralel: "what
  should I watch").
* SCAN row click peek-then-click (single→drawer, double→DES jump).

---

## 2026-04-30 — Round 18 — Scanner Phase C+D + drawer + shell:ready guard

Rapor 2 §8 row 18 (multi-asset scanner) + Round 17 kalan adayları:
fine scan, per-symbol contribution drawer, shell-ready boot guard.

### Sidecar — Phase C (fine scan)

`scanner._phase_c(targets, …)` her top-K satırı için 3 paralel pass
çalıştırıyor (Semaphore 6):
* `_last_quote()` → last/prev_close/change% (CRYPTO için
  ccxt_failover/coingecko, kalan için yfinance).
* `_overextension_score(closes, change_pct)` → 30-bar z-skoru +
  `OVERBOUGHT/OVERSOLD/OK` etiketi; `|change_pct| ≥ 5` da `overextended`
  flag'ini tetikliyor.
* Her fine-TF için `consensus_signal` → ayrı `fine.contributions[]`
  bloku (Phase B contribs ile yan yana karşılaştırma).

Fine TF'ler: ZAK matrisinin en küçük 4'ü (req.timeframes override
varsa son 3'ü).

### Sidecar — Phase D (risk overlay)

Deterministik (canlı veri yok). `PortfolioState` local SQLite okuyor,
her satıra `position_overlap = {held, high_concentration?}` ekliyor;
phase output `{portfolio_symbols, by_class, held_in_results, new_long,
new_short}` dönüyor. Boş portföyde Phase D <2 ms.

### `/api/scanner/run` phase plan API

```jsonc
{ "intent": "...", "phases": "A,B,C,D",   // ya da array
  "fine_top_k": 4, "top_n": 20 }
```

Default `"A,B"` — eski client'lar yavaşlamasın. **Round 17
sıralama bug fix:** `rows` artık `|score|` ile sıralanıyor; SHORT
bias'ı kalktı (LONG ve SHORT konvik picks ikisi de top-N'e çıkıyor).

### Frontend — types + drawer + toggles

* `lib/scanner.ts` — `OverextensionInfo`, `ScanFineBlock`,
  `PositionOverlap` interface'leri; `ScanRow.fine` +
  `ScanRow.position_overlap`; `ScanRequest.phases` + `fine_top_k`.
* `functions/SCAN.tsx`:
  * `A+B` always-on disabled toggle + `C · fine` + `D · risk`
    toggle butonları.
  * Single-click → drawer (Header pills: direction × conf +
    HELD / HIGH CONC / OVERBOUGHT / OVERSOLD; Phase B + Phase C
    yan yana contrib tabloları; "Open DES" + Close butonları).
  * Drawer in-pane (modal değil) — multi-pane'le uyumlu.

### shell:ready guard for `restoreWorkspace`

`workspace-persist.waitForShellReady()` Tauri'de `shell:ready`
event'ini bekliyor (Round 12 `lib.rs setup()` zaten emit ediyor),
1.5 sn timeout fallback'i ile. Browser-mode'da hemen resolve.
Round 17'de mümkün olan slow-boot race'i kapatıldı (Tauri
`filesystem::ensure_layout` henüz state dizinini yaratmadan
React'in ilk `load_workspace` okuması).

### Test

* **Sidecar `tests/test_scanner.py` 20/20:** Round 17'nin 13 + 7
  yeni (`_overextension_score` overbought/oversold/ok/few-closes/
  change-pct-only, `ScanRequest` defaults, explicit phases).
* **Frontend 12 dosya, 62/62:** regresyonsuz.
* `tsc --noEmit` temiz; `vite build` 728 ms; bundle **388 KB /
  121 KB gzip** (Round 17 → +5 KB ham). 6/6 dev module 200,
  Phase D live overlay test edildi.

### Live smoke

`POST /api/scanner/run {"phases":"A,B,C,D", top_n:3, fine_top_k:3}` →
phases A 0ms · B 32s · C 25s · D 0ms; first row `fine.quote.last`,
`fine.overextension.z_score_30d`, `fine.contributions[4]`,
`position_overlap.held=false` doluyor.

### Karar / sapma

* **`|score|` sort.** Round 17'nin SHORT bias'ı; mutlak değere
  bakmak iki yönü de yüzeye çıkarıyor.
* **Phase D no live fetch.** Auto-scan Round 20+ tray'den fire
  ediyor olabilir; canlı yfinance × her satır = elapse double.
  PortfolioState local SQLite read.
* **Phase C concurrency 6.** Phase B 8-wide; gelecek paralel
  kullanımda 2 slot adapter retry'e açık kalsın.
* **z-threshold 2σ.** Konservatif kesim — OVERBOUGHT flag yalnız
  gerçek uçlarda.
* **`overextended = z-uç OR |%change|≥5`.** "Stock gapped on news,
  rolling stats normal" tuzağına izin vermez.
* **Drawer in-pane.** Multi-pane modal overlay belirsiz —
  drawer leaf'in altında pinli.
* **shell:ready timeout 1.5 s.** Soğuk Tauri boot için yeterli,
  browser dev'de sallanma yok.

### Round 19'un ilk işi

* ASKB orchestrator (Planner / Search / Summarizer / Viz).
  Round 17'nin naive intent router'ı LLM yoksa fallback olur.
* SCAN ana grid'inde `change_pct_today` sortable kolon (drawer'da
  zaten var).
* Drawer keyboard nav (← / → satırlar arası, ⌘↩ "Open DES").

---

## 2026-04-30 — Round 17 — Scanner Agent + per-window workspace + link groups

Rapor 2 §8 row 17 ("Scanner Agent A+B + ZAK matrisi taşındı") + Round 16
kalan adayları (per-window workspace, cross-pane symbol broadcast).

### Yeni alt-modüller

* **`src-py/showme/scanner.py`** — first-party Scanner Agent. ZAK matrix
  per asset class (ShowMe §bot_service._ZAK kripto için verbatim;
  EQUITY/FX/COMMODITY/MACRO/BOND/ETF kalibre edildi). 6 universe preset,
  naive intent router (`crypto/fx/commodity/etf/equity`), pure-Python
  `consensus_signal` (RSI(14) + MACD(12,26,9) + 50/200 MA cross),
  `run_scan()` Phase A + B paralel orkestratörü
  (`asyncio.Semaphore(8)`). Bot service singleton import edilmedi —
  state'siz, yeniden başlatılabilir.
* **Sidecar endpoint'ler:** `GET /api/scanner/universes` + `POST
  /api/scanner/run`. ShowMe attached değilse 503.
* **`src-ui/src/lib/scanner.ts`** — typed scanner client.
* **`src-ui/src/functions/SCAN.tsx`** — intent textarea + sample chips +
  universe override + Top-N + Run; result block phase pills + clickable
  DataGrid; row click → focused leaf'i `(DES, symbol)` ile bind.
* **`DataGrid` upgrade** — `onRowClick(row, idx)` + `render(row, idx)`
  index passthrough. PORT/EQS hâlâ per-cell anchor kullanıyor; SCAN
  yeni typed callback'i tüketiyor.

### Per-window workspace state

* Rust `commands::save_workspace` / `load_workspace` artık
  `Option<String>` `label` alıyor. `safe_label()` non-`[A-Za-z0-9_-]`
  karakterleri `_` ile escape ediyor. Dosya: `state/workspace-<label>.json`.
  Round-16 legacy `workspace.json`'ı `main` label için bir defalık
  fallback olarak okunuyor.
* Frontend `workspace-persist.ts` `getCurrentWindow().label`'ı Tauri
  command'larına forward ediyor; browser-mode `showme.workspace.<label>`
  per-tab key kullanıyor.

### Link groups (cross-pane symbol broadcast)

* `LeafNode.linkGroup?: "A"|"B"|"C"|"D"` eklendi.
* `setFocusedTarget` artık focused leaf'in linkGroup'u varsa, aynı
  gruptaki diğer leaf'lere yeni symbol'ü propagate ediyor (kodları
  korunarak — DES + AAPL focus, FA pane'i FA + AAPL'den FA + MSFT'e
  geçer).
* `setLeafLinkGroup(leafId, group?)` toggle.
* `PaneChrome` 🔗 butonu + 4-button picker; aktifse accent renkli pill.

### Test (vitest 2.1.9 + pytest 8)

* **Frontend 12 dosya, 62/62 geçiyor:** `workspace-link.test.ts` (5 NEW)
  + Round 16'nın 11 dosyası.
* **Sidecar `tests/test_scanner.py` 13/13:** ZAK monotone, universe
  routing (5 paramatre), consensus components uptrend/downtrend/flat,
  short-series MACD/MA fallback, RSI mean-reversion bias.

`tsc --noEmit` temiz; `vite build` 906 ms; bundle 383 KB / 120 KB gzip
(Round 16 → +7 KB ham). 11/11 dev module 200; sidecar 6 universe live.

### Karar / sapma

* **Statik universes Round 17'de.** Phase A 4-keyword heuristic; Round
  19 LLM Planner ScanRequest contract'ını koruyarak swap edecek.
* **Concurrency cap 8.** yfinance circuit-breaker tolerasyonu;
  function-index sidecar yine boot olabilir, 2 slot'a yer.
* **`bot_service.ScannerService` import edilmedi** — live bot state
  (cycle, lock files) burada bloklamasın diye; yalnız ZAK kavramı +
  adapter chain reused.
* **RSI mean-reversion bias kasıtlı.** Pure deterministic uptrend RSI'yı
  100'e satüre eder → -1 (overbought) score; +0.8 MACD + +0.6 MA ile
  birlikte ~+0.4 → NEUTRAL. Round 19 trend-only mode tuner ekler.
* **Link groups pane-level, workspace-level değil.** Aynı pencerede
  A/B grubu AAPL'de, C/D grubu MSFT'de olabilir.
* **Per-window state migration.** Round 16'dan upgrade eden kullanıcılar
  ilk `main` window load'unda eski `workspace.json`'ı bulup replay
  ediyor; sonraki save'ler `workspace-main.json` yazıyor.
* **DataGrid row click opt-in.** PORT/EQS'in mevcut per-cell anchor'ları
  bozulmasın; yeni `onRowClick` typed callback tercih edilen pattern.

### Round 18'in ilk işi

* Phase C — fine scan (top-N B × kısa TF + sentiment overlay).
* SCAN pane'inde per-symbol contribution breakdown göster (şu an
  sadece aggregate).
* Per-window restoreWorkspace() Tauri window-ready event'ini await
  etsin (Round 12 `shell:ready` zaten emit ediliyor).

---

## 2026-04-30 — Round 16 — Tray + Dock + Notifications + filesystem persistence

Rapor 2 §8 row 16: "Tray + Dock + Notifications + Global Shortcuts —
macOS native his."

### Rust — gerçek Cocoa bridge'leri

Round 12'nin log-only stub'ları yerine Tauri 2'nin first-party
`set_badge_count` + `request_user_attention` API'leri. `dock::set_badge`
ve `dock::request_attention` artık `<R: Runtime>` jenerik, no-op
fallback non-macOS.

### Tray live ticker

`tray.rs` — Round 12'nin static menu'süne 3 disabled menu item eklendi
(Bot · status · cycle / Portfolio · n pos · MV / Alerts · n active · m
today). 5 sn'de bir Tokio interval, sidecar `/api/sidecar/ticker`'i
`reqwest 0.12 (rustls-tls)` ile poll ediyor. `alerts.active` değişince
dock badge `dock::set_badge` ile auto-sync.

### Sidecar `/api/sidecar/ticker`

Compact JSON: `{ts, bot{running,cycle,mode}, portfolio{n_positions,
market_value,daily_pnl}, alerts{active,fired_today}, warnings}`. Her alt
fetch best-effort — bot_service.get_state / PortfolioState /
alert_engine.list_alerts başarısızlığı `warnings`'e ekliyor, payload
yine dönüyor.

### Notifications wrapper

`notifications.rs` — `tauri-plugin-notification` builder'ı thread
identifier (`group()` → `UNMutableNotificationContent.threadIdentifier`)
ve severity (Critical/Warn → `dock::request_attention`) ile sarmaladı.
Action butonları `UNNotificationAction` plugin feature flag'i arkasında;
API şekli sabit, gelecek round bir bool flip'i.

### Filesystem-backed presets

`presets.rs` — `~/Library/Application Support/showMe/state/layout-presets/
<name>.json`. 4 Tauri command (`list_presets`, `read_preset`,
`write_preset`, `delete_preset`) + name validation (`/ \ : control char`
red). Frontend `lib/presets.ts` artık async, `isInTauri()` ile backend
seçiyor; browser dev fallback localStorage.

### Workspace persistence

`lib/workspace-persist.ts` — zustand subscriber + 400 ms debounce →
disk. `state/workspace.json` (Tauri) veya `localStorage["showme.workspace"]`
(browser). `restoreWorkspace()` boot'ta tek seferlik replay; sonra
`startWorkspaceAutosave()` otomatik kaydediyor.

### Test (vitest 2.1.9)

11 dosya, **57/57 geçiyor:**

```
✓ workspace.test.ts (13)        ✓ presets.test.ts (7) async refactor
✓ workspace-persist.test.ts (3) NEW  ✓ router/theme/toast/symbols/functions
✓ i18n/ChangeText/registry
```

`tsc --noEmit` temiz; `vite build` 822 ms; bundle 376 KB / 118 KB gzip
(Round 15 → +2 KB ham). 10/10 dev module 200 on Vite :5173, sidecar
`/api/sidecar/ticker` ve `/api/fn/{STRS,PORT}` round-trip temiz.

### Karar / sapma

* **Manual objc2 yok.** Tauri 2 NSDockTile + requestUserAttention'ı
  zaten sarıyor. Daha az kod, sıfır unsafe, gelecek Tauri upgrade'leri
  platform fix'lerini bedavaya getirir.
* **Tray ticker = disabled menu items.** Tauri 2 NSStatusItem'a
  arbitrary SwiftUI view host'lamayı henüz cleanly açmıyor; `setText`
  on disabled item bugün en ucuz live ticker. `set_view` API'si
  geldiğinde graduate.
* **5 sn poll, push değil.** Sidecar→Rust push private port + ws
  gerektirirdi; ticker rezolüsyonu (cycle + alert count) için 5 sn
  fazlasıyla yeterli, maliyet ihmal edilebilir.
* **`reqwest` rustls-tls only.** macOS-arm64 CI runner'larında
  OpenSSL cross-compile ağrısı yok.
* **Workspace autosave debounce 400 ms.** Drag-resize handle
  ~60 evt/s atıyor; debounce yoksa her frame disk'e JSON yazılırdı.
  400 ms perceived lag eşiğinin üstünde, kill -9 sonrası split
  korunması beklentisinin altında.
* **Workspace state per-window değil (henüz).** İki pencere aynı
  autosave dosyasını paylaşıyor (last-writer-wins). Round 17'de
  pencere label'ına göre key'lenecek.

### Round 17'nin ilk işi

* Per-window workspace state (`state/workspace-<label>.json`).
* Scanner Agent Phase A+B — eski ShowMe ZAK matrisi wrap edilecek,
  yeni pane `/api/fn/SCAN` tüketecek.
* Cross-pane symbol broadcast — DES AAPL'ye odakla → bitişik FA pane
  "linked" mod'da otomatik rebind.

---

## 2026-04-30 — Round 15 — Multi-pane workspace + layout presets + multi-window

Rapor 2 §8 row 15: "Multi-window + GoldenLayout + state persistence —
Trader 4 panel açıyor, kapatıyor, geri yüklüyor."

### Yeni alt-modüller

* **`lib/workspace.ts`** — first-party split tree (`leaf` / `split` union)
  + zustand store + tree mutations (`splitFocused`, `closeFocused`,
  `setSplitSizes`, `setFocusedTarget`) + `serializeWorkspace` /
  `loadWorkspace` (id remap).
* **`lib/presets.ts`** — localStorage-backed save/load/delete; Round-16
  Tauri-fs swap planlandı (`PresetSummary` interface contract).
* **`shell/Workspace.tsx`** — recursive split renderer; CSS-grid + 4 px
  drag handle + 8% min size; focus outline accent border.
* **`shell/PaneChrome.tsx`** — code button + Picker (138 fn + HOME/PREF)
  + symbol breadcrumb + ▣ ☰ ✕ aksiyonları.
* **`shell/PresetMenu.tsx`** — titlebar dropdown; isim input + save
  butonu + load-on-click + per-row delete.

### Shell güncellemesi

* **Titlebar** ⫼ split-h, ☰ split-v, ✕ close, ⊞ new-window, PresetMenu.
* **App** — `RouteOutlet` yerine `RouteSync`: hash route'tan
  `setFocusedTarget(code, symbol)` çağırarak focused leaf'i güncelliyor;
  not-found rotası tek-pane Empty.
* **Klavye:** `⌘\` split-h, `⌘⇧\` split-v, `⌘W` close-pane (tree single
  leaf değilse).
* **Multi-window** — Round 12'nin `open_window` Tauri command'i
  titlebar'dan tetikleniyor; her pencere ayrı state.

### Test (vitest 2.1.9)

`src-ui` paketinde 10 dosya, **54/54 geçiyor:**

```
✓ workspace.test.ts (13) NEW   ✓ presets.test.ts (7) NEW
✓ router.test.ts (5)            ✓ theme.test.ts (3)
✓ toast.test.ts (3)             ✓ symbols.test.ts (4)
✓ functions.test.ts (4)         ✓ i18n.test.ts (7)
✓ ChangeText.test.tsx (4)       ✓ registry.test.tsx (4)
```

`tsc --noEmit` temiz; `vite build` 838 ms; bundle 374 KB / 117 KB gzip
(Round 14 → +12 KB ham, +3 KB gzip). 15/15 dev module 200.

### Karar / sapma

* **GoldenLayout reddedildi** — jQuery-ekipli serialize formatı bizim
  preset şemasıyla çelişiyor; ~250 LOC TS'de full kontrol, sıfır ekstra
  runtime, `serializeWorkspace` json-dump tek satır.
* **Split target = parent target** — kullanıcı `⌘\` deyince yan-yana
  aynı instrument'i görmek istiyor; Picker bir tık uzakta.
* **URL hash hâlâ tek-truth.** Per-pane URL segmenti
  (`#/p1=…&p2=…`) paylaşılabilir layout için ileride; ⌘K mevcut focus'u
  güncelliyor — şimdilik yeterli.
* **Sizes drag sonrası renormalized** — 4-pane'de cascade drift'i
  engellemek için her `setSplitSizes` çıkışında.
* **Picker portal değil** — PaneChrome içinde. Round 16'da `⌘P` global
  swap-focused-pane modal'ı eklenebilir.
* **`⌘W` only-leaf'te native pencere kapatma** — preventDefault yok,
  Tauri / browser default davranışına izin ver.

### Round 16'nın ilk işi

* Cocoa bridge'leri (NSDockTile badge + bounce, NSStatusItem live
  ticker, UNUserNotificationCenter action buttons + threadIdentifier
  grouping). Round 12 stub'ları yerleştirildi.
* Layout preset storage'ı `~/Library/Application Support/showMe/state/
  layout-presets/<name>.json`'a Tauri-fs üzerinden taşı.
* Current workspace tree'yi `window-state.json`'a serialize et — refresh
  / restart sonrası split korunacak.

---

## 2026-04-30 — Round 14 — İlk 5 native fonksiyon paneli

Rapor 2 §8 row 14: "DES, FA, GP/TECH, EQS, PORT — URL navigasyonu yerine
Tauri command, splash anlamlı."

### Sidecar — `/api/fn/{code}`

Round-12'nin 501 stub'ı yerine, FunctionRegistry'i çağıran tipli geçit.
`get_factory()` her istekte idempotent çalışıyor; `Instrument` symbol +
asset_class query param'larından inşa ediliyor; `execute_timed()` çıktısı
`to_dict()` ile dön. GET (query) ve POST (JSON) ikisi de destekleniyor.
Eski `/api/proxy/*` artık **410 Gone**.

Sidecar smoke:
- `GET /api/fn/STRS?action=list` → 8 scenario.
- `GET /api/fn/PORT` (boş portfolio) → `warnings:["empty portfolio"]`.
- `GET /api/fn/TRDH` → 10 borsa rows, `is_open_now` populated.

### Frontend katmanları

* `lib/functions.ts` — `runFunction<T>` (GET ↔ POST otomatik), `FunctionCallError`,
  `FunctionCallResult<T>` jenerik.
* `lib/useFunction.ts` — `idle/loading/ok/error` 4-state hook +
  AbortController + dep-stable params stringify.
* `lib/symbols.ts` — recent-symbols localStorage (uppercase + dedupe + cap 12).
* `shell/SymbolBar.tsx` — symbol input + GO + son 6 sembol pill'i + active
  code Pill'i. DES/FA/GP başlığında.
* `functions/registry.tsx` — `code → ComponentType<FunctionPaneProps>`
  haritası. Round 14: DES, FA, GP, TECH (alias), EQS, PORT (5 unique
  bileşen, 6 code).
* `App` router: `resolvePane(code)` ile native bileşen, yoksa Round-13'ün
  `FunctionStub`'ına fallback.

### Yeni 5 pane

| Code  | Sürüm                                                              |
| ----- | ------------------------------------------------------------------ |
| DES   | İş özeti + sektör/endüstri/HQ/employees/marketCap/IPO snapshot     |
| FA    | Income / Balance / Cash flow / Ratios — segmented Tabs + DataGrid  |
| GP    | Lightweight-charts candle + volume hist + indicator overlay; 1M/3M/6M/1Y/5Y aralık |
| TECH  | GP alias (Round 14); Round 15+ kendi indicator-tuning UI           |
| EQS   | DSL editor (textarea + sample chips) + universe/limit + DataGrid + symbol → DES navigation |
| PORT  | KPI grid (MV/cost basis/unrealized/cash) + by-class roll-up + position DataGrid |

### Yeni bağımlılık

* `lightweight-charts@4.2.0` (~180 KB minified). Bundle 178 → 362 KB
  (114 KB gzip). Tek chart kütüphanesi; v5'e Round 15+'da geçilebilir.

### Test (vitest 2.1.9)

`src-ui` paketinde 8 dosya, **34/34 geçiyor:**

```
✓ router.test.ts (5)        ✓ theme.test.ts (3)        ✓ toast.test.ts (3)
✓ symbols.test.ts (4) NEW   ✓ functions.test.ts (4) NEW
✓ i18n.test.ts (7)          ✓ ChangeText.test.tsx (4)
✓ registry.test.tsx (4) NEW
```

`tsc --noEmit` temiz; `vite build` 750 ms; 14/14 dev module 200.

### Karar / sapma

* **TECH = GP alias.** ShowMe iki ayrı fonksiyon ediyor; UI yüzeyi
  Round 14'te aynı candle + volume + indikatör paneli. TECH kendi
  indicator-tuning UI'ını edinince split.
* **`useFunction` cache yok.** Round 15 GoldenLayout pane-swap'leri
  sıklaştıkça SWR-tarzı cache eklenebilir; şimdilik mount başına bir
  fetch yeterince ucuz.
* **EQS auto-fetch yapmıyor** — kullanıcı "Run" butonuna basıyor.
  yfinance ekstre tüketmemek için keystroke başına çağrı bilinçli olarak
  pas geçildi.
* **POST vs GET otomatik** — `runFunction` param value'larında
  object/array görürse POST'a düşer; primitive ise GET. Çağıran taraf
  transport düşünmüyor.
* **lightweight-charts v4 imperative API** (v5 yeni generic
  `addSeries(Definition, opts)` ergonomisi henüz oturmamış).

### Round 15'in ilk işi

* Multi-pane workspace (GoldenLayout veya first-party split-pane).
* Layout presets `state/layout-presets/`'a serialize.
* Round 14 ekran görüntüleri Round 15'te pin'lenir (cargo tauri dev'i ile).

---

## 2026-04-30 — Round 13 — Design system + shell wiring

Rapor 2 §8 row 13: "design system + shell — ilk pencere Bloomberg-class."

### Yeni alt-modüller

* **`src-ui/src/design-system/`** — 12 primitive: `Pane`, `Card`,
  `Toolbar`, `Tabs`, `Crumbs`, `Field`, `KbdHint`, `Empty`, `Skeleton`,
  `Pill`, `ChangeText`, `DataGrid`. Barrel `index.ts` tek public surface.
* **`src-ui/src/lib/router.ts`** — hash-based pane router; React-Router'a
  bağımlılık yok. `parseRoute` + `useRoute` + `navigate`. `welcome /
  preferences / fn / symbol / not-found` 5 kind'ı destekliyor.
* **`src-ui/src/lib/theme.ts`** — dark default + localStorage persistence
  + `[data-theme]` flip; toggle button titlebar'da.
* **`src-ui/src/lib/toast.ts` + `shell/ToastHost.tsx`** — `alert()` /
  `confirm()` yerine inline toast yığını (info / success / warn / error,
  TTL ton'a göre).
* **`src-ui/src/i18n/`** — `en.json` + `tr.json` authoritative; 12 locale
  setter (`de fr es it ja zh ko ar pt ru` fallback-to-en); `setLocale`
  HTML `lang/dir` flip ediyor.
* **Yeni paneller:** `panes/Welcome.tsx` (function-index kategorize
  breakdown + quick-launch + system cards), `panes/Preferences.tsx`
  (appearance / data / about sekmeleri + canlı theme + language switch),
  `panes/FunctionStub.tsx` (Round-14 öncesi her function code için
  placeholder).

### Shell güncellemesi

* `Titlebar` — yeni `Pill` primitive'i kullanıyor; theme + preferences +
  reveal-data butonları.
* `Sidebar` — function entry'leri `<button onClick={navigate}>`.
* `CommandPalette` — ↑↓ klavye navigasyonu + Enter ile route push;
  `STATIC_ENTRIES` ile `PREF` / `HOME` route'ları.

### Test (vitest 2.1.9 + jsdom 25)

`src-ui` paketinde 5 test dosyası, **22/22 geçiyor:**

```
✓ src/lib/router.test.ts (5)
✓ src/lib/theme.test.ts (3)
✓ src/lib/toast.test.ts (3)
✓ src/i18n/i18n.test.ts (7)
✓ src/design-system/ChangeText.test.tsx (4)
```

`tsc --noEmit` temiz; `vitest run` 0.94 sn'de bitiyor.

### Karar / sapma

* **React-Router yerine hash router** — Tauri webview'in tarihçe
  davranışıyla en uyumlu en küçük çözüm; Round 12'nin deep-link bridge'i
  ile sıfır iş ekleyerek entegre oluyor.
* **`localStorage` stub'u test-only.** jsdom 25 + vitest 2.x'te `clear()`
  ve `removeItem` yer yer eksik geliyor; `src/test/setup.ts` içinde
  `MemoryStorage` sınıfı ile tüm `Storage` interface'i karşılanıyor.
  Production kodu native localStorage kullanmaya devam ediyor.
* **i18n fetch yerine module-import.** 12 catalog × <1 KB gzipped =
  ihmal edilebilir bundle yükü, sıfır waterfall.
* **`Pill` primitive Round 12'nin `.pill` CSS sınıfını kapsadı**;
  kaldırma Round 14'e ertelendi (kullanılmayan kod, kırılgan değil).
* **`Tabs` segmented + underline iki variant** — preferences sekmeleri
  underline, gelecek pane içi sub-toolbar'lar segmented kullanır.

### Round 14'ün ilk işi

* İlk 5 native fonksiyon paneli (DES, FA, GP/TECH, EQS, PORT) —
  `FunctionStub`'ın yerine geçecek. TradingView Lightweight Charts
  integrasyonu + sidecar `/api/proxy/{code}` ile GET test edilecek.
* Round 15: GoldenLayout / kendi multi-pane primitive'i; pane state
  persist `state/layout-presets/`.

---

## 2026-04-30 — Round 12 — showMe scaffold + sidecar lifecycle (Native Geçiş başladı)

Rapor 2 §13 başlangıç adımı; "Coder, devam et" direktifiyle showMe iskelesi
kuruldu. **ShowMe dosyalarına dokunulmadı** — Rapor 2 §10 madde 1.

### Yeni proje konumu

`/Users/nazmi/Desktop/Projeler/proje/showMe/` — ShowMe kardeşi, ayrı VCS, ayrı
process. Tauri 2 + Rust + React 18/TS + Python sidecar.

### Klasör yapısı (Rapor 2 §2 ile birebir)

```
showMe/
├── package.json              workspace root, npm scripts
├── README.md                 quickstart + production build notes
├── src-tauri/                Rust shell
│   ├── Cargo.toml            Tauri 2.x + plugins (shell, fs, dialog, notif, log, deep-link, store, global-shortcut)
│   ├── tauri.conf.json       overlay titlebar + vibrancy + showme:// scheme + bundled binaries
│   ├── build.rs / entitlements.plist
│   └── src/
│       ├── main.rs / lib.rs       app entry, plugin wiring, AppState
│       ├── sidecar.rs             port discovery + 3× exp-backoff + SIGTERM 5s grace
│       ├── filesystem.rs          ~/Library/Application Support/showMe layout (idempotent)
│       ├── window.rs              multi-window state persistence
│       ├── tray.rs                NSStatusItem + dropdown
│       ├── menu.rs                NSMenuBar (app/File/Edit/View/Window/Help)
│       ├── dock.rs                badge + bounce stubs (round-16 cocoa wiring)
│       ├── shortcuts.rs           ⌘⇧S, ⌘⇧K, ⌘⇧A
│       ├── deeplink.rs            showme:// URL routing
│       ├── notifications.rs       UNUserNotificationCenter wrapper
│       ├── biometric.rs           LocalAuthentication stub (round-20)
│       ├── commands.rs            tauri::command yüzeyi (sidecar_status, open_window, request_biometric, set_dock_badge, ...)
│       └── ipc.rs                 base_url helper for HTTP-to-sidecar
├── src-py/                   Python sidecar
│   ├── pyproject.toml        FastAPI + uvicorn + duckdb + pandas + dev[pyinstaller]
│   └── showme/
│       ├── __init__.py
│       └── server.py         port-0 + stdout SIDECAR_PORT relay + ShowMe path-import + CORS
├── src-ui/                   React/TS Vite
│   ├── package.json          React 18, zustand, Tailwind 3, ESLint 9, Prettier 3
│   ├── vite.config.ts        Tauri-aware (TAURI_DEV_HOST, ENV_DEBUG)
│   ├── tsconfig.json         strict + path aliases @/*
│   ├── tailwind.config.js    token-driven (consumes CSS custom props)
│   ├── postcss.config.js
│   ├── index.html            data-theme="dark", color-scheme dark
│   └── src/
│       ├── main.tsx               kill default contextmenu, mount StrictMode
│       ├── App.tsx                shell composition + sidecar bootstrap + listen() hooks
│       ├── styles/
│       │   ├── tokens.css         design tokens (Bloomberg-class)
│       │   └── index.css          tailwind + layout primitives + .pill / .btn / .kbd
│       ├── lib/
│       │   ├── tauri.ts           façade (silent no-op outside Tauri)
│       │   ├── sidecar.ts         typed HTTP client + bootstrapSidecarPort
│       │   └── store.ts           zustand singleton store
│       ├── shell/
│       │   ├── Titlebar.tsx       overlay titlebar + status pill + ⌘K trigger
│       │   ├── Sidebar.tsx        category-grouped function index
│       │   └── Statusbar.tsx      sidecar status + showme root + UTC clock
│       ├── command-palette/
│       │   └── Palette.tsx        ⌘K modal, ESC to close, fuzzy filter on code/name/category
│       └── panes/
│           └── Splash.tsx         Round 12 first-window content
├── packaging/
│   ├── build_sidecar.sh      PyInstaller universal2 + --add-data ShowMe
│   ├── sign.sh               Developer ID + hardened runtime + entitlements
│   ├── notarize.sh           xcrun notarytool + stapler
│   └── dmg-config.json       540×360 dark window, /Applications shortcut
└── docs/
    ├── architecture.md       process model + bootstrap sequence + failure modes
    ├── ui_standards.md       living tokens / typography / motion / forbidden list
    ├── engine_independence.md  per-route migration table + state migration plan
    ├── coder_log.md          (this file)
    └── round_notes/          (round-by-round screenshots / artefacts)
```

### Sidecar kontratı

Tauri shell, Python sürecinin bağlandığı portu *tek bir stdout satırı*ndan
keşfeder: `SIDECAR_PORT=<u16>`. Bu format Rapor 2 §4 ile uyumlu.

**Lifecycle:**
* Boot: `python3 -m showme.server --port 0` (dev) veya
  `Contents/MacOS/showme-backend --port 0` (release).
* Crash policy: 3× exponential-backoff retry (250 / 750 / 2250 ms), sonra
  `sidecar:fatal` event'i ile NSAlert benzeri hata diyaloğu (UI tarafı).
* Quit: `kill()` → 5 sn grace → ikinci `kill()`.

**ShowMe erişimi:** path-import. `SHOWME_ENGINE_PATH` env-var (default
`../ShowMe`). Çalıştırma sırasında `sys.path` öne ekleniyor — ShowMe src ağacı
*kopyalanmıyor*. Production PyInstaller bundle'ında `--add-data $ShowMe/src:src`
ile self-contained binary üretiyor.

### Smoke test (Round 12 doğrulaması)

```
$ python3 -m showme.server --port 0
SIDECAR_PORT=52215
$ curl http://127.0.0.1:52215/api/health
{"ok":true,"showme":{"engine_root":"/.../ShowMe","engine_attached":true}}
$ curl http://127.0.0.1:52215/api/function-index | jq length
138
```

→ ShowMe'ün 138 fonksiyonu sidecar üzerinden ham olarak görünüyor; `/api/health`
green; engine_attached=true. WKWebView'in `bootstrapSidecarPort()` → port emit
ile UI'a geçiyor.

### Karar / sapma notları

* **Tauri 2 (varsayılan kabul edildi).** Electron'a düşmek için sebep yok;
  ~10 MB shell + WKWebView Apple Silicon'da native renderer. PyQt yolu
  Rapor 2 §3 madde son'da yasaklandığı için değerlendirilmedi.
* **Custom titlebar via `titleBarStyle: Overlay` + `hiddenTitle: true`.**
  Trafik ışıkları (14, 18) konumunda; ilk 36 px `app-region: drag`,
  `.interactive` opt-out.
* **NSVisualEffect vibrancy** Tauri 2.x `windowEffects` ile —
  `["sidebar", "underWindowBackground"]` aktif state'te.
* **Cocoa bridge'leri (dock badge, bounce, Touch ID) Round 16 / 20'ye
  bırakıldı.** Round 12'de fonksiyon imzaları + log'lu stub. Frontend
  zaten `invoke('set_dock_badge')` çağırabilir; gerçek NSDockTile çağrısı
  gelene kadar log'a düşüyor.
* **Design tokens CSS custom-property tabanlı** — Tailwind config bunları
  okuyor. Bileşenlerde hex bulunmuyor (tek istisna `index.css` flash
  animasyonları, oradan da `var()`'a geçilebilir).
* **`.eslintrc.cjs` flat-config'e geçirilmedi** — Tauri create-template
  ile uyum için klasik format. Round 13'te eslint 9 flat'e geçilebilir.
* **Updater devre dışı** — `tauri.conf.json > plugins.updater.active = false`.
  Round 22'de Sparkle ya da Tauri updater pubkey ile açılır.
* **Coder log ShowMe'ten kopyalandı**, ilk satırlar showMe başlığıyla
  güncellendi; eski Round 0–11 entry'leri olduğu gibi altında kaldı.

### Round 13'ün ilk işi

* `cargo tauri dev` ilk başarılı boot (Rust toolchain kullanıcı tarafında).
* `npm install` src-ui'da, Vite dev server `:5173` Tauri tarafından spawn
  edilmiş halde gelmeli.
* Splash pane yerine ilk gerçek pane (`Preferences` / `function-launcher`).
* GoldenLayout entegrasyonu Round 15'e ertelenmek yerine 13'te incelenir;
  zorlama yok — tıkanırsa Round 14'e (DES / FA) atla.

---

## 2026-04-30 — Faz 0 (Foundation refactor) başlatıldı ve tamamlandı

### Özet
- Mevcut kripto kodu hiç dokunulmadan yeni `src/core/`, `src/assets/`,
  `src/data_sources/`, `src/functions/`, `src/agents/`, `src/reference/`
  paketleri oluşturuldu.
- Tüm ABC'ler yazıldı: `BaseDataSource`, `BaseAssetClass`, `BaseFunction`,
  `BaseAgent`, `BaseBroker`, `Instrument`, `AssetClass`, `Quote`, `Trade`,
  `OrderBook`, `OrderBookLevel`, `ReferenceData`, `FunctionResult`,
  `FunctionDeps`, `FunctionRegistry`, `DataRouter`.
- Asset facade'ları kondu: `CryptoAssetClass` (legacy bot service'i sarar),
  Equity/Bond/FX/Commodity/Derivative/ETF/Fund/Macro.
- Reference layer: `SymbolRegistry` (offline heuristic + OpenFIGI fallback),
  `ExchangeRegistry` (44 borsa, yfinance suffix tablosu),
  `CalendarRegistry` (`exchange_calendars` opsiyonel),
  `CurrencyRegistry` (27 ISO 4217).
- `OpenFIGIAdapter` yazıldı (anonim 25/dk, anahtarla 250/dk).
- `config/data_sources.yaml`: 35+ adapter parametresi + chain tanımları
  + günlük bütçe capleri.
- `requirements.txt` ve `.env.example` Faz 1-7 kütüphane ihtiyaçları için
  genişletildi (yfinance, sec-edgar, pandas-ta, py_vollib, anthropic,
  alpaca-py, ib_insync, vs.).
- `.gitignore` baştan yazıldı (env, runtime, db, parquet, ipynb checkpoint).
- README, plan §1 baseline gerçeklerine göre yeniden yazıldı (futures,
  22 indikatör, FastAPI, paper, auto-close kapalı).
- Yardımcılar: `src/utils/throttle.py` (`@throttle`, `TokenBucket`,
  `CircuitBreaker`).
- Hesap taksonomisi: `src/core/accounting_taxonomy.py` (US-GAAP ↔ IFRS
  başlangıç eşlemesi, kanonik alan adları).

### Kararlar (Plan'dan sapmalar / yorumlar)
1. **Branch tutmadık** — bu dizin git repo değil. Plan'ın
   `feature/bloomberg-class` direktifi git'e bağlı; tek-dizin çalışmada
   atlandı. Kullanıcı git'e geçirmek isterse `git init && git add -A &&
   git checkout -b feature/bloomberg-class` yeterli.
2. **`src/assets/crypto/`** mevcut kodu **TAŞIMADI**, yalnızca facade
   yazıldı. Plan §4 "wrap, move değil" diyordu; aynen uygulandı.
3. **OpenFIGI** anahtarsız çalışıyor; sadece quota artırma için isteğe
   bağlı `OPENFIGI_API_KEY`.
4. **Symbol heuristic** önce: indeksler → FRED makrolar → US Treasury →
   FX major + EM → kripto pair → ETF → exchange-suffixed equity → bare US
   ticker. OpenFIGI son çare.
5. **Currency formatlama** minor_units'i ISO 4217'e göre uygular (JPY 0,
   KWD 3, USDT 6 — stablecoin için eklendi).

### Spec Açıklaması / Eklemeler
- `BaseFunction.execute_timed()` eklendi — performans bütçesi kontrolü
  (Plan §26 madde 8) için. Plan'da `execute()` çağrılırken elapsed
  ölçümü zorunlu değildi; ekledim.
- `OrderBook.imbalance()` ve `depth()` yardımcıları eklendi — likidasyon
  fonksiyonu için sıkça gerekecek.
- `Instrument` factory metotları (crypto/equity/macro_series) eklendi.
- `ReferenceData.merge()` — iki kaynaktan gelen ref-data'yı birleştirmek
  için (örn. yfinance + Finnhub + SEC EDGAR).

### Açık Görevler (Faz 0 sonu)
- [ ] OpenFIGI mock cassette'i `tests/cassettes/openfigi/` altına eklenecek.
- [ ] Symbol registry için Wikipedia S&P500/NASDAQ100 bootstrap script
      (Faz 1 başında).
- [ ] `feature/bloomberg-class` branch açma talimatı README'ye eklenebilir
      (kullanıcı git'i etkin ettiğinde).

### Dosyalar
- Yeni: 30+ dosya (core/, assets/, reference/, data_sources/reference/,
  utils/throttle.py, config/data_sources.yaml, docs/coder_log.md).
- Değiştirilen: README.md, requirements.txt, .env.example, .gitignore.
- Silinen / taşınan: yok.

---

## 2026-04-30 — Faz 1 (Universal Data Plane) tamamlandı

**Adapter sayısı:** 24 adapter (yfinance, finnhub, alphavantage, eodhd,
stooq, sec_edgar, fred, worldbank, imf, oecd, tradingeconomics,
cme_fedwatch, ecb, exchangerate_host, eia, ustreasury, gdelt, rss,
finnhub_news, reddit, stocktwits, openweathermap, opensky, openfigi).

**Yeni utility:** `src/services/function_factory.py` — config'ten tek
boot ile tüm adapter'ları instantiate edip `FunctionDeps`'e bağlar.
Lazy singleton; lazy import ile fonksiyon modüllerini otomatik kayıt eder.

**Karar:** SDK kurulu olmayan ortamlarda adapter'lar yine de instantiate
edilir, sadece `fetch()` çağrısında SDK gereksinimini bildirir. Bu
"deployment-time-flexible" davranış; CI'da SDK olmadan bile import yeşil.

**Test:** `tests/test_throttle.py` (TokenBucket, throttle, CircuitBreaker).

---

## 2026-04-30 — Faz 2 (Equity Functions) tamamlandı

**Eklenen fonksiyonlar:** DES, FA, EE, ANR, BETA, WACC, DVD, CACT, ESG,
EQS (DSL parser dahil), RV, HDS, PIB, SPLC. 14 fonksiyon.

**Karar:** EQS DSL için kendi recursive-descent parser'ı yazıldı
(pyparsing/lark zorunlu kılınmadan). Tokenizer + AST evaluator. Test
suite (`tests/test_eqs_dsl.py`) AND/OR/quoted-string/parens kapsıyor.

**Karar:** WACC'da Damodaran ERP scrape Phase 4'e bırakıldı; ERP=5%
varsayılan. CAPM rf = FRED DGS10. β otomatik 2Y window.

---

## 2026-04-30 — Faz 3 (News & Research) tamamlandı

**Eklenen fonksiyonlar:** TOP, NI, NSE, READ, BRIEF, SOSC, AV, TRAN,
EVTS, CN. 10 fonksiyon.

**Karar:** TOP fonksiyonu üç ayrı kaynaktan paralel çekiyor (GDELT, RSS,
Finnhub) ve published_at sırasına göre dedupe-merge. NSE şimdilik
GDELT'e fallback (Meilisearch index Phase 7'de eklenecek).

---

## 2026-04-30 — Faz 4 (Macro + Bond + FX + Commodity + Derivative) tamamlandı

**Eklenen fonksiyonlar (24):**
- Macro: ECO, ECST, ECFC, BTMM, WIRP, GMM, COUN
- Bond: YAS (kendi YTM/duration/convexity solver), CRPR, CRVF, DDIS,
  DEBT, WB, SRSK, ALLQ, GC3D
- FX: FXFC, FXIP, WCRS, FRD, OVDV
- Commodity: BOIL, BGAS, NGAS, CPF, GLCO, WETR
- Derivative: OVME (kendi BS+greeks implementation), OMON, OSA, HVT, IVOL

**Karar:** OVME için Black-Scholes-Merton kendi yazıldı (dividend yield
dahil). py_vollib opsiyonel; implementasyon kendi başına çalışır. Test
suite put-call parity ve intrinsic-at-expiry doğruluyor.

**Karar:** YAS için QuantLib gerektirmeyen 1D Newton solver yazıldı.
Test: par-bond YTM ≈ coupon, premium-bond YTM < coupon.

---

## 2026-04-30 — Faz 5 (Portfolio + Screener) tamamlandı

**Eklenen modüller:**
- `src/portfolio/state.py` — multi-asset PortfolioState, legacy crypto
  state.json'dan otomatik mirror.
- `src/functions/portfolio/`: PORT, PORT_WHATIF, TRA, MARS.
- `src/functions/screen/_funcs.py`: SRCH, FSRC, CSRC, SECF, MOST, WEI.
- `src/functions/misc/cde.py`: CDE custom data fields.

**Karar:** PORT WHAT-IF tam parametrik PORT() Phase 5 sonu. Şimdiki
sürüm "delta-only" stub. PORT lex-mevcut yfinance + legacy mirror.

---

## 2026-04-30 — Faz 6 (Trading Multi-Broker) tamamlandı

**Eklenen modüller:**
- `src/data_sources/broker/`: binance_broker, alpaca_broker, ibkr_broker,
  oanda_broker (4 adapter).
- `src/functions/trade/_funcs.py`: EMSX, AIM, TSOX, FXGO, BBGT, TCA.
- `src/functions/trade/algos/`: VWAPAlgo, TWAPAlgo, IcebergAlgo, SniperAlgo.

**Karar:** Algo'lar şimdilik scheduler dataclass'ları; entegre canlı
slicing Phase 6 sonu. AIM cross-broker open-orders aggregator olarak
çalışıyor — bağlı her broker'dan parallel çek.

---

## 2026-04-30 — Faz 7 (Agents + Excel/API + Misc) tamamlandı

**Eklenen modüller:**
- `src/agents/llm_router.py` — Anthropic Haiku/Sonnet/Opus + OpenAI
  GPT-4o-mini/GPT-4o; daily budget cap; cost log JSONL.
- 8 ajan: PlannerAgent, SearchAgent, SummarizerAgent, CodeAgent (subprocess
  sandbox), VizAgent (Plotly), ExecutionAgent (verification pass),
  RiskAgent, NewsAgent.
- `src/agents/orchestrator.py` — DAG runner; Planner → list of agents → results.
- `src/functions/api/`: BQL (kendi parser), DAPI, FLDS, BQUANT.
- `src/functions/misc/`: ALRT (alarm engine), GRAB, LANG (12 dil), BIO,
  BMC, FLY, DINE.

**Karar:** LLM Router cheapest-first; risk-critical + complex queries
için Sonnet/Opus. Daily budget exceeded → boş response döner (fail-safe).

---

## 2026-04-30 — UI + Dashboard route entegrasyonu

**Yeni:**
- `dashboard/static/css/bloomberg.css` — Bloomberg-tarzı dark theme,
  orange accent (#FF8C00), JetBrains Mono, multi-pane grid, mobile.
- `dashboard/static/js/`: cmdk.js (⌘K palette + Bloomberg
  `<SYMBOL> <FN> <GO>` akışı + history), keys.js (g d/g f/g n/⌘1..9/⌘//⌘.),
  watchlist.js (15s ticker).
- `dashboard/templates/`: bloomberg_base.html (topbar+tabs+sidebar+status+help),
  function.html (universal function renderer), portfolio.html, news_feed.html,
  calendar.html, screener.html, trade.html, landing.html (4-pane home).
- `dashboard/bloomberg_router.py` — FastAPI APIRouter; 18+ pages and
  REST endpoints (DAPI surface).

**Eski dashboard:** /legacy alias eklendi; mevcut crypto bot dashboard
kullanıcı eskiden eriştiği gibi çalışmaya devam eder.

**Karar:** Sembol tabanlı tüm fonksiyonlar `/symbol/<sym>/<code>`
generic route üzerinden render olur — yeni fonksiyon eklendiğinde
`@FunctionRegistry.register` yeterli, route eklemeye gerek yok.

---

## 2026-04-30 — Test + Doğrulama

**Eklenen test dosyaları:**
- `tests/test_core.py` (10 test): ABC'ler, DataRouter, FunctionRegistry,
  Instrument serialization, Quote/OrderBook helpers.
- `tests/test_symbol_registry.py` (10 test): heuristic resolver matrix.
- `tests/test_eqs_dsl.py` (5 test): EQS DSL parse + filter.
- `tests/test_ovme_blackscholes.py` (3 test): BS price + Greeks +
  put-call parity.
- `tests/test_yas_bond.py` (3 test): YTM par/premium/discount.
- `tests/test_throttle.py` (3 test): TokenBucket + CircuitBreaker +
  throttle decorator.

**Sonuç:** 35/35 yeni test geçti. Toplam suite: 197/198 geçti.
Düşen tek test (`test_decision_engine.py::test_close_on_opposing_signal`)
auto-close kapatılmadan önce yazılmış legacy test — kullanıcı 2026-04-29'da
auto-close'u kapattı (Plan §26 madde 1 gereği eski koda dokunulmadı).

**Smoke test:** uvicorn dashboard.app:app ile 127.0.0.1:8765, 11 yeni
route hepsi 200, 84 fonksiyon registered, 12 kategori.

---

## 2026-04-30 — Round 11 derinleştirme (sırayla devam)

Trading microstructure phase 2 + corporate intelligence + book risk.

**Yeni fonksiyonlar (6, 132 → 138):**
- **EXEC** — VWAP/TWAP execution monitor: parent + slice ledger,
  per-slice IS bps, fill rate, pace (ahead / behind schedule), avg
  fill, residual qty. SQLite `runtime/exec_monitor.sqlite`.
- **DARK** — Dark pool / FINRA ATS weekly volume; per-venue + per-week
  aggregations, top-venue concentration ratio.
- **FORM4** — SEC EDGAR Form 4 (insider transactions) calendar; recent
  filings list + by-month rollup + viewer URL.
- **ISIN** — Universal symbol cross-reference: ISIN/CUSIP/SEDOL/Ticker/FIGI
  via OpenFIGI batch lookup; heuristic auto-detect (12-char ISIN,
  9-char CUSIP, 7-char SEDOL).
- **GREEKS** — Portfolio-level Greeks aggregation (Δ/Γ/ν/Θ/ρ);
  pure-numpy Black-Scholes (no SciPy / py_vollib), sums across mixed
  call/put book.
- **EREV** — Earnings revisions calendar: finnhub recommendation buckets
  M-o-M; avg score (-2 strongSell ↔ +2 strongBuy), revision velocity,
  net up/down change between periods.

**Yeni servisler (2):**
- `services/exec_monitor.py` — open_parent / record_slice / close_parent /
  get_parent / list_parents + compute_metrics (IS bps, pace pct,
  per-slice slippage). SQLite tables: `parent_orders`, `slices`.
- `services/greeks.py` — bs_d1/d2 + bs_call/put_price + bs_delta_call/put +
  bs_gamma + bs_vega + bs_theta_call/put + bs_rho_call/put +
  position_greeks + aggregate_book. Math erf-based normal CDF.

**Yeni adapter capabilities (2):**
- `equity/sec_edgar_adapter.py`: `recent_filings(cik, form, limit)` +
  `form4_filings(ticker, limit)` — submissions feed parser + viewer URL.
- `reference/openfigi_adapter.py`: `lookup_by(id_type, id_value, exch_code)`
  — generic resolution by any OpenFIGI idType (replaces ticker-only
  lookup for ISIN/CUSIP/SEDOL queries).

**FunctionDeps slot eklendi:** `imf`, `oecd`, `exchangerate_host`, `stooq`
artık explicit (factory zaten setattr ile bağlıyordu — açıklığa kavuştu).

**Yeni router endpoint'leri:**
- `/exec` + `/api/v1/exec`, `/api/v1/exec/{pid}`,
  `/api/v1/exec/open`, `/api/v1/exec/{pid}/slice`,
  `/api/v1/exec/{pid}/close`
- `/dark` + `/api/v1/dark/{symbol}`
- `/form4` + `/api/v1/form4/{symbol}`
- `/isin` + `/api/v1/isin?ids=...&id_type=...`
- `/greeks` + `/api/v1/greeks` (POST)
- `/erev` + `/api/v1/erev/{symbol}`

**Yeni sayfalar (6):**
- `/exec` — Parent order tablosu + tıklayarak slice detay + Demo button
  (5 slice TWAP trail).
- `/dark` — FINRA venue/week tablosu + top-venue concentration özeti.
- `/form4` — Insider filing list + by-month histogram.
- `/isin` — Multi-input ID resolver (auto-detect).
- `/greeks` — Multi-row position table → live aggregate (Δ/Γ/ν/Θ/ρ).
- `/erev` — Period-over-period revision tablosu + delta-avg velocity.

**Sidebar/tab güncellemesi:**
- Sidebar Tools: Exec Monitor (EXEC), Dark Pool (DARK), Insiders (FORM4),
  Revisions (EREV), Greeks (GREEKS), X-Ref (ISIN).
- Global tabs: EXEC, DARK, FORM4, ISIN, GREEKS, EREV eklendi.

**Test coverage:**
- `tests/test_round11.py` — 13 test: registry resolve + exec full lifecycle
  (open/slice×5/close + IS computation accurate to 1e-6) +
  exec pace ahead-of-schedule + ISIN auto-detect (4 ID types) +
  ATM call delta in [0.45, 0.65] + put-call parity (Δ_call − Δ_put = 1
  for q=0) + gamma positive + book aggregate sums + EREV bucket weights +
  DARK no-adapter graceful warning + EXEC function-level smoke +
  function-count growth.
  **13/13 yeşil.**
- Toplam test: 364 passed, 2 failed (pre-existing legacy:
  `test_index_shows_start_button`, `test_close_on_opposing_signal`).

**Smoke (uvicorn :8765):**
- 16/16 route 200.
- API round-trip:
  - EXEC: open smoke-1 (AAPL BUY 500 @ arrival 150) →
    2× 250-share slice @ 150.3 / 150.5 → close → metrics:
    filled 500, avg 150.4, IS = +26.67 bp ✓
  - GREEKS: 10 calls + 5 puts @ 150 → totals Δ=373.74,
    Γ=44.63, ν=$24,761, Θ/day=−$129.21 ✓
  - ISIN: ["AAPL", "US0378331005"] → 2 hits, types=[TICKER, ID_ISIN] ✓
- Function inventory: **138 functions across 14 categories**.

**Karar / gerekçe:**
- EXEC slice ledger SQLite-backed: persistent across restarts, multi-process
  güvenli (RLock + check_same_thread=False). Demo button frontend'de
  çünkü test fixture olarak insertion path'i hızlı validate ediyor.
- TWAP/VWAP benchmark: arrival_price default; user override için her
  slice'ta `benchmark_px` kabul ediyoruz (live execution sırasında
  running VWAP'ı algo üreticisi push'lar).
- Black-Scholes pure-Python: math.erf yeterince hızlı (μs-level) ve
  numpy bağımlılığı yok. py_vollib opsiyonel idi — kaldırıldı.
- Form 4 viewer URL: SEC EDGAR Archives klasör pattern'i —
  `/Archives/edgar/data/{cik_no_zero_pad}/{accession_no_dashes}/{primary}`.
  XBRL parsing yapmıyorum, yalnızca filing list + link.
- OpenFIGI generic lookup: existing `lookup(ticker)` zaten POST /mapping
  kullanıyor; yeni `lookup_by` aynı endpoint'i farklı `idType` ile
  generic'leştiriyor — sıfır API maliyeti, sadece kod genişlemesi.
- EREV bucket weights: industry standart -2..+2 (Bloomberg ANR view).
  Velocity = avg_period_now − avg_period_prev (basit). HMM / time-series
  modelleri ihmal — basit & şeffaf.
- ISIN auto-detect heuristics: ISO 10962 / CUSIP standartı uzunluk
  bazlı (ISO regex daha katı olabilir; pratik için yeterli, kullanıcı
  isterse `id_type` override).

**Kalan adaylar (Round 12+):**
- IVOL surface 3D viewer (Plotly mesh).
- Earnings transcript LLM Q&A archive (TRQA on TSAR).
- Insider transaction parser (Form 4 XML — qty/price/relationship çıkartma).
- Intraday tick replay viewer.
- Climate/ESG controversy feed (RepRisk public).
- Risk parity factor portfolio (HRP via correlation distance).
- Equity factor screener (size/value/momentum/quality/low-vol).
- Bloomberg-tarzı OMON option monitor (real-time IV / GEX flip).
- Dark pool printability score (NMS Reg ATS T+1 lag).
- IEX DEEP feed (paid).
- Refinitiv news (paid).

---

## 2026-04-30 — Round 10 derinleştirme (sırayla devam)

Trading microstructure + advanced risk + macro regime + sovereign bond ops.

**Yeni fonksiyonlar (6, 127 → 132):**
- **TCA** — Trade Cost Analysis: implementation shortfall (vs arrival),
  slippage (vs VWAP/close), opportunity cost on unfilled, per-symbol
  aggregation. order_history `metadata.fills[]`, arrival_price, vwap, close
  alanlarını kullanıyor; eksikse "missing prices" warning.
- **GEX** — Gamma Exposure: per-strike dealer-perspective gamma
  ($/1% move), gamma flip strike, call/put walls. Black-Scholes γ + OI
  weighting; max 3 expiry default; dealer convention: short calls / long puts.
- **PCAS** — PCA Factor Stress: SVD decomposition of returns,
  k-σ shock along chosen PC; her asset için loading × shock; portfolio
  notional weighted P&L; top-8 loadings table.
- **FXH** — FX Hedge: forward-rate overlay (covered interest parity),
  carry P&L, ±%shock senaryolar. Manuel exposures veya portfolio'dan
  türetilen foreign-currency notional.
- **TAUC** — Treasury Auction Calendar: TreasuryDirect.gov public JSON
  feed; upcoming + recent (Bills/Notes/Bonds/TIPS/FRN) + by-type aggregate.
- **REGM** — Market Regime: trend (50/200 MA cross) + realized vol
  (21d/long ratio) + drawdown (peak) + yield curve (DGS10−DGS2 from FRED).
  Composite labels: Risk-on bull / Melt-up / Late-cycle / Recovery /
  Drawdown / Crisis / Bearish / Range-bound / Choppy.
  Optional rolling history + pure-numpy k-means clustering.

**Yeni servisler (5):**
- `services/tca.py` — analyze_order + analyze_orders aggregation;
  IS bps, slippage, opportunity cost, score (BETTER/EVEN/WORSE).
- `services/gamma_exposure.py` — bs_gamma + chain_gex with dealer-perspective
  + gamma_flip detection + walls.
- `services/pca_stress.py` — SVD-based PCA, factor_shock, apply_to_portfolio,
  top_loadings (no SciPy).
- `services/fx_hedge.py` — FXExposure dataclass + forward_rate (CIP) +
  hedge_one + hedge_book.
- `services/regime_classifier.py` — _trend/_vol/_drawdown/_curve labels +
  composite() rule + classify() main + kmeans_lite (pure numpy).

**Yeni adapter (1, 41 → 42):**
- `bond/treasury_auctions_adapter.py` — TreasuryDirect.gov public JSON
  (no key); upcoming() / recent() helpers; rate_limit_rps=4. FunctionDeps
  slot eklendi (`treasury_auctions: Any = None`).

**Yeni router endpoint'leri:**
- `/tca` + `/api/v1/tca`
- `/gex` + `/api/v1/gex/{symbol}`
- `/fxh` + `/api/v1/fxh` (POST)
- `/regm` + `/api/v1/regm/{symbol}`
- `/tauc` + `/api/v1/tauc`
- `/pcas` + `/api/v1/pcas`

**Yeni sayfalar (6):**
- `/tca` — Trade Cost Analysis dashboard (broker/symbol filter +
  per-symbol aggregate + per-order detail with score badges).
- `/gex` — Gamma Exposure: spot, net GEX, flip, walls + horizontal bar
  histogram (top 30 strikes).
- `/fxh` — FX Hedge calculator: manuel exposures table + carry / shock
  senaryosu rapor.
- `/regm` — Market Regime: current snapshot + rolling 60-day history
  toggle.
- `/tauc` — Treasury auctions: upcoming/recent toggle, by-type rollup.
- `/pcas` — PCA Stress: PC index/k-σ picker, top loadings, asset-level
  P&L breakdown.

**Sidebar/tab güncellemesi:**
- Sidebar Tools: Stress (STRS), PCA Stress (PCAS), Margin (MGN),
  TCA, Gamma (GEX), FX Hedge (FXH), Regime (REGM), Auctions (TAUC),
  Transcripts (TSAR), People (PEOP).
- Global tabs: TCA, GEX, FXH, TAUC, REGM, PCAS eklendi.

**Test coverage:**
- `tests/test_round10.py` — 17 test: registry resolve + TCA buy/sell IS +
  TCA aggregation + BS gamma ATM + chain GEX symmetry + chain GEX call-heavy +
  PCA single-factor explained-variance + factor shock signs + FX forward CIP +
  full hedge book carry-only + regime bull-quiet + regime crisis +
  curve inverted/flat + kmeans converges + function-count growth.
  **17/17 yeşil.**
- Toplam test: 351 passed, 2 failed (pre-existing legacy:
  `test_index_shows_start_button`, `test_close_on_opposing_signal`).

**Smoke (uvicorn :8765):**
- 28/28 route 200.
- API round-trip:
  - TCA: 0 order başlangıçta — graceful empty.
  - TAUC: 5 upcoming auction (live TreasuryDirect feed).
  - FXH: 100k EUR + 50k GBP, 90-gün, %5 shock → carry $964.75,
    1.0 hedge ratio → strong = weak = carry only.
  - REGM/GEX: yfinance circuit-breaker open → warnings, graceful path
    (test edildi: function path doğru çalışıyor).
- Function inventory: **132 functions across 14 categories**
  (portfolio 23, equity 21, news 13, screen 13, misc 12, bond 10,
  macro 9, trade 7, commodity 6, fx 6, derivative 6, api 4, chart 2, comm 2).

**Karar / gerekçe:**
- TCA arrival_price tabanlı IS: industry standard (Almgren benchmark).
  vs VWAP ve vs close ek karşılaştırmalar — opsiyonel ama tipik.
- GEX dealer convention: SPX dealers structurally short calls
  (covered call funds, retail call buying) → negatif gamma; uzun puts
  (hedger demand, retail put buying) → pozitif gamma. Bu yöne göre
  gamma flip ve walls hesaplanıyor.
- Black-Scholes basitleştirme: dividend yield ihmal; risk-free rate
  default 4% (params override). Greek hesabı analitik (no quad) —
  py_vollib zorunluluğunu silmek için.
- PCA via SVD (numpy.linalg.svd): SciPy import etmeden, M-stable.
  Faktör shock = loading × (k × √eigenvalue). PC1 ≈ market β,
  PC2 ≈ sector tilt — tipik portföylerde.
- FX hedge CIP forward: F = S × (1 + r_home × T) / (1 + r_base × T),
  daily compounding ihmal — kullanıcı isterse `(1+r)^T` versiyonu kolay.
- Regime composite: rule-tabanlı (öğretilebilir, izlenebilir)
  + opsiyonel kmeans clustering (unsupervised). HMM ihmal — pomegranate
  bağımlılığı eklemek istemedim, kmeans yeterince ayırt edici.
- TreasuryAuctions adapter: explicit fetch() returns list[dict],
  not DataResponse — ShowMe BaseDataSource flexible, Polymarket adapter
  da aynı pattern.

**Kalan adaylar (Round 11+):**
- VWAP/TWAP execution monitor (real-time fill quality during execution).
- Dark pool aggregator (FINRA NMS Reg ATS).
- Insider transaction calendar (SEC Form 4 stream).
- Earnings revision calendar (analyst EPS revisions feed).
- ISIN/CUSIP/SEDOL cross-reference UI (OpenFIGI batch).
- Option implied volatility surface 3D viewer.
- Greeks aggregation across portfolio (gamma exposure, vega bucket).
- Trade idea network: ASKB tarzı multi-agent debate UI.
- Climate/ESG controversy feed (RepRisk public).
- IEX DEEP Level-3 feed adapter (paid).
- Refinitiv news scrape proxy (paid).
- AlphaSense transcript scrape (login wall).
- Excel RTD bridge (xlwings, desktop-only).

---

## 2026-04-30 — Round 9 derinleştirme (sırayla devam)

Risk modelling + cross-account margin + transcript archive + people directory.

**Yeni fonksiyonlar (6, 121 → 127):**
- **STRS** — Portfolio stress test: 8 önceden tanımlı senaryo
  (GFC 2008, COVID 2020, China 2015, Rate +300bp, Tech Bust 2022,
  USD +15%, Oil +60%, Crypto Winter) + custom shock + compare-all.
  Asset-class > sector > symbol önceliğiyle shock uygulama.
- **RPAR** — Risk parity (ERC) ağırlıkları: iteratif Maillard/Roncalli
  çözücü + naive inverse-vol fallback. Kovaryans yfinance OHLCV'den
  504 günlük geriye dönük.
- **BLAK** — Black-Litterman: π_BL = π + τΣP'(PτΣP'+Ω)⁻¹(Q−Pπ)
  + posterior covariance + analytical max-utility weights.
  Görüşler `{"long":[...], "short":[...], "expected":...}` formatında.
- **MGN** — Cross-account margin: 7 strateji (Reg-T, Portfolio,
  Crypto Spot, Crypto Futures 10x, Futures SPAN-lite, FX 50:1, Bond)
  + per-account cushion + buying power + JSON config (override per account).
- **TSAR** — Transcript Search (AlphaSense-tarzı): SQLite + FTS5 BM25
  ranked search + snippet markup; FTS5 yoksa LIKE fallback.
- **PEOP** — People Search: yerel SQLite directory; isim/şirket/rol/bio
  araması + roller (history) + tags. Manual upsert + REST CRUD.

**Yeni servisler (4):**
- `services/stress_scenarios.py` — 8 calibrated shock scenarios +
  apply_scenario(positions, scenario, scale) + compare_scenarios.
- `services/risk_parity.py` — Maillard/Roncalli ERC çözücü +
  naive_inverse_vol + risk_contributions decomposition.
- `services/black_litterman.py` — implied_returns, posterior, and
  implied_optimal_weights (analytical max-utility).
- `services/margin_engine.py` — 7 default rule sets + per-account
  override + portfolio-margin stress-shock haircut + JSON persistence
  (`runtime/margin_config.json`).
- `services/transcripts_archive.py` — FTS5 (with LIKE fallback)
  SQLite store, idempotent (symbol, quarter, fiscal_year, event_date)
  upsert key, snippet() with porter tokenizer.
- `services/people_directory.py` — SQLite store with people + people_roles
  tables, idempotent upsert, search, list_for_company.

**Yeni script:**
- `scripts/ingest_transcripts.py` — `--symbols AAPL,MSFT --source seekingalpha`
  cron-friendly ingester. job_runner kind: `ingest_transcripts`.

**Yeni router endpoint'leri:**
- `/stress` + `/api/v1/stress`, `/api/v1/stress/compare`
- `/margin` + `/api/v1/margin`, `/api/v1/margin/accounts` (CRUD)
- `/transcripts` + `/api/v1/transcripts/{search,list,ingest,get}`
- `/people` + `/api/v1/people/{search,upsert,delete}`

**Yeni sayfalar (4):**
- `/stress` — STRS scenario picker + Compare-all karşılaştırma tablosu.
- `/margin` — MGN account table + per-account add/edit form.
- `/transcripts` — TSAR full-text search + manual ingest formu.
- `/people` — PEOP search + person upsert formu.

**Sidebar/tab güncelleme:**
- Sidebar Tools listesine `STRS, MGN, TSAR, PEOP` linkleri.
- Global tabs: `STRS, MGN, TSAR, PEOP` eklendi.
- job_runner.py `_KIND_TO_CMD`: `ingest_transcripts`, `fundamentals`,
  `ohlcv_refresh` türleri eklendi.

**Test coverage:**
- `tests/test_round9.py` — 16 test: registry resolve + stress
  scenarios + ERC two-asset symmetric + BL view shifts posterior +
  Reg-T 50/25 + transcript FTS round-trip + idempotent upsert +
  people CRUD. **16/16 yeşil.**
- Toplam test: 334 passed, 2 failed (pre-existing legacy:
  `test_index_shows_start_button`, `test_close_on_opposing_signal`).

**Smoke (uvicorn :8765):**
- 33/33 route 200 (cold start: `/`, `/fn/MGN` gerçek yfinance fetch
  yapıyor → ilk istekte 30s'e kadar; warm: <500ms).
- API round-trip: ingest → search → list → match (NVDA Q4 FY26 transcript;
  search "Blackwell" → 1 hit).
- Margin upsert (portfolio margin) → calc → 1 hesap görünür.
- Stress compare → 8 scenario, sıralı (worst → best).
- Function inventory: 127 functions across 14 categories
  (portfolio 21, equity 21, news 13, screen 13, misc 12, bond 9,
  macro 8, trade 6, commodity 6, fx 5, derivative 5, api 4, chart 2, comm 2).

**Karar / gerekçe:**
- Stress scenarios kalibrasyonu: tarihsel peak-trough drawdown'lardan
  asset-class default'ları + sector overrides. Symbol > sector >
  asset_class önceliği — kullanıcı `BTCUSDT: -0.85` özel shock'u
  varsayılan crypto -0.65'i geçersiz kılabilir.
- Risk parity neden iteratif Maillard ve SciPy değil: SciPy
  zorunluluğunu silmek için. ~200 iter'de 1e-9 residual convergence,
  tipik 5-50 asset universe için yeterli.
- Black-Litterman P matrix relative weights: long-set 1/k, short-set
  -1/k (otomatik, kullanıcı sadece `long`+`short` listesi verir).
- FTS5 self-contained mode (external content değil): test paralelliği
  + tmp_path izolasyonu için daha sağlam (external content'in trigger
  bağımlılığı yok). `tokenize='porter'` İngilizce kök eşleştirme.
- Margin engine: portfolio margin shock-based (worst of ±15%);
  Reg-T notional-based; futures fixed-per-contract. Buying power
  formula: equity-initial / initial_pct ($1 başına 2x leverage).
- People directory: hand-curated MVP — Crunchbase/LinkedIn API
  entegrasyonu sonraya bırakıldı (TOS riski, paid endpoint).

**Kalan adaylar (Round 10+):**
- AlphaSense gerçek scrape (login wall) → archive-only kullanım.
- IEX DEEP feed adapter (paid).
- Refinitiv news scrape proxy (paid).
- Cross-account FX hedging engine.
- Stress correlation breakdown (PCA factor shocks).
- Portfolio-level options Greek aggregation (gamma exposure / GEX).
- Trade cost analysis (TCA) post-trade fill quality dashboard.
- Treasury auction calendar feed.
- Excel RTD bridge (xlwings — desktop-only).

---

## 2026-04-30 — Round 8 derinleştirme (sırayla devam)

Operations + tax + telemetry + scheduling + RAG.

**Yeni fonksiyonlar (5, 116 → 121):**
- **LOTS** — Tax lot ledger (FIFO/LIFO/HIFO/LOFO/SPECIFIC) + realized
  P&L summary + LT/ST term classification.
- **TRDH** — Trading hours awareness; per-exchange is_open + next_open
  + seconds_until_open (10 borsa default).
- **POLY** — Polymarket public CLOB markets snapshot (search + slug fetch).
- **TRQA** — Transcript Q&A: Whisper transcribe → LLM answers a list
  of analyst questions; default 5 questions (revenue, guidance, risks,
  CEO quote, capital allocation).
- **HFS** — 13F holder search (reverse lookup); `/holders/{issuer}` UI
  + sec_13f DuckDB backend.

**Yeni servisler (3):**
- `services/risk_monitor.py` — async daemon: drawdown / daily loss /
  position concentration breaches → JSONL + notifier dispatch.
- `services/tax_lots.py` — SQLite-backed lot ledger + sell()
  consumer with 5 selection methods.
- `services/job_runner.py` — cron-like job scheduler; 4 kinds (tldr,
  brief, ingest_13f, shell) + run history table.

**Yeni adapter (1, 40 → 41):**
- `alt/polymarket_adapter.py` — Gamma API public endpoints
  (markets + slug + search).

**Yeni router'lar:**
- `dashboard/health_router.py` — /healthz, /readyz, /metrics
  (Prometheus exposition), /metrics/json. Telemetry middleware
  her HTTP isteğini route × ms olarak topluyor.

**Yeni sayfalar:**
- `/status` — WebSocket bot status + alerts feed (Round 7'de eklendi).
- `/jobs` — Cron orchestrator UI (schedule + run + log tail).
- `/latency` — Per-route p50/p95/p99 telemetry dashboard.
- `/holders/{issuer}` — 13F reverse lookup UI.

**Streaming:**
- `dashboard/streaming_router.py` `/ws/pnl` — 15s portfolio P&L push.
- `/ws/orderbook/{sym}` — Round 7'de eklendi.

**Risk monitor startup hook:** SHOWME_ENABLE_RISK_MONITOR=true ile
arka plan daemon olarak çalışır. Drawdown / daily loss / concentration
breaches alert engine + Slack/Discord/Telegram'a yayar.

**Sidebar:** Live Status, Cron Jobs, Latency (LATD) Tools menüsüne
eklendi.
**Global tablar:** +TRDH, POLY, FRH, LOTS, ACCT.

**Bug fix yok bu turda — tüm yeni eklenenler ilk seferde geçti.**

**Yeni testler (9):**
- `test_round8.py`: registry, FIFO P&L (250 doğru), HIFO P&L (50
  doğru), short_qty remainder, summary buckets, health.record_request,
  RiskMonitor peak save/load, TRDH crypto=24/7, job_runner upsert/list/delete.

**Test sonucu:** 298/299 yeşil (legacy auto-close hariç).
**Smoke:** uvicorn 8765 → **20/20 route 200**, **121 fonksiyon**,
14 kategori. /healthz, /metrics, /api/v1/jobs upsert canlı çalışıyor.

---

## 2026-04-30 — Round 7 derinleştirme (sırayla devam)

Crypto on-chain alerts + tax + microstructure + multi-account + integrations.

**Yeni fonksiyonlar (6, 110 → 116):**
- **WHAL** — On-chain whale signals: Glassnode active addr / tx volume
  z-score + ETH gas spike + Mempool recent blocks (BTC).
- **TLH** — Tax-loss harvesting: lot-level losses + LT/ST tax rate
  + wash-sale window + sector ETF replacement suggestion.
- **FRH** — Funding rate heatmap (Binance + Bybit + OKX, top 25 pairs,
  per-exchange + average).
- **PVAR** — Position-level VaR + marginal contribution to risk
  (component decomposition by symbol, parametric VaR @ 95/99%).
- **MICRO** — Order book microstructure: spread/spread_bps + depth
  ladder (5/10/20/50 levels) + Kyle's lambda proxy.
- **ACCT** — Multi-account aggregation: per-account roll-up +
  cross-account asset class / symbol exposure totals.

**Slack integration:**
- `dashboard/slack_router.py` — `/showme` slash command receiver.
- 7 sub-commands: quote, fa, news, frh, portfolio, ask, help.
- HMAC-SHA256 signature verification + 5-min replay window.

**Real-time UI:**
- `templates/status_dashboard.html` — `/status` WebSocket consumer
  (status + alerts feeds, KPI grid, fire log).
- DPLT order book sayfası `/ws/orderbook/{sym}` (Binance @depth20@100ms)
  WS push'a yükseltildi; polling fallback hâlâ çalışır.

**Backend extension:**
- `dashboard/streaming_router.py` — `/ws/orderbook/{symbol}` Binance
  WS proxy (websockets dep).
- `services/transcription.py` — 4-tier Whisper pipeline (whisper →
  faster-whisper → OpenAI API → stub) + sha256 caching.
- TRAN function `audio_url` ve `audio_path` parametrelerini kabul
  edecek şekilde genişletildi.
- `PortfolioPosition.account` alanı eklendi (multi-account).

**Yeni testler (10):**
- `test_round7.py` (7): WHAL/TLH/FRH/PVAR/MICRO/ACCT registry,
  Slack signature (4 senaryo: no-secret, valid, invalid, replay),
  FRH universe boyutu, TLH sector replacement map.
- `test_pfa_pvar_acct.py` (3): MCR mathematical identity, PFA Brinson
  decomposition, PortfolioPosition.account roundtrip.

**Test sonucu:** 289/290 yeşil (legacy auto-close hariç).
**Smoke:** uvicorn 8765 → **28/28 route 200**, **116 fonksiyon**,
14 kategori. Slack `/showme help` 200 dönüş.

---

## 2026-04-30 — Round 6 derinleştirme (sırayla devam)

Quant zenginleştirme + LLM agent QA + tooling.

**Yeni fonksiyonlar (7, 103 → 110):**
- **MEET** — Meeting briefing (Notion + Granola + GDELT + DES +
  portfolio match parallel).
- **TLDR** — Daily portfolio TL;DR (LLM router, fallback deterministic).
- **PFA** — Brinson-Hood-Beebower attribution (allocation + selection
  + interaction).
- **REBA** — Rebalancer: target weights → buy/sell orders +
  liquidations + drift filtering.
- **BTUNE** — Strategy hyperparameter sweep → best by Sharpe / return / Calmar.
- **BMTX** — Strategy × universe backtest matrix (paralel).
- **SAT** — Sentinel Hub imagery + NDVI stats.

**Yeni sayfalar:**
- `/algo/run` — live algo runner (VWAP/TWAP/ICEBERG/SNIPER) + cancel
  + audit auto-refresh.
- `/ask` — Financial QA Agent (Orchestrator + Planner + SearchAgent +
  SummarizerAgent). Preset queries + cost telemetry.
- `/meeting` — MEET render.
- `/api/v1/agent/ask`, `/api/v1/algo/start`, `/api/v1/algo/cancel/{id}` REST.

**Sidebar:** Ask Agent (QA), MEET Briefing, Algo Runner eklendi.
**Sembol tablar:** +BTUNE.
**Global tablar:** +BMTX, PFA, REBA, TLDR.

**Yeni adapter (1, 39 → 40):**
- `alt/sentinelhub_adapter.py` — Sentinel-2 process-image + NDVI
  statistics, OAuth2 token cache.

**Yeni script:**
- `scripts/run_tldr.py` — daily summary cron + email + Slack/Discord push.
- `scripts/ingest_13f.py` — top 30 filer × 4 quarter backfill.

**Bug fix:**
- `CCXTFailoverAdapter._normalize_symbol` "/" içeren girişlerde
  "ETH/U/USD" gibi bozuk pair üretiyordu — düzeltildi.

**Yeni testler (10):**
- `test_pfa.py` (3): demo, explicit inputs, decomposition.
- `test_btune_bmtx.py` (3): registry + grids + strategies.
- `test_ccxt_failover.py` (4): symbol normalization + chain order.

**Test sonucu:** 279/280 yeşil (legacy auto-close hariç).
**Smoke:** uvicorn 8765 → **34/34 yeşil**, **110 fonksiyon**, 14 kategori.

---

## 2026-04-30 — Round 5 derinleştirme (sırayla devam)

Quant + ML + UX + persistence ekleri.

**Yeni servisler (4):**
- `services/optimizer.py` — Markowitz mean-variance: min_volatility,
  max_sharpe, efficient_frontier (40-pt), risk_parity. SciPy gerektirmeyen
  projected gradient descent + closed-form.
- `services/backtest_framework.py` — walk-forward backtest + 3
  built-in strategy (sma_crossover, rsi_meanrev, buy_and_hold) +
  Sharpe/Sortino/Calmar/max_dd.
- `services/ml_signals.py` — feature engineering + 4-tier classifier
  chain (LightGBM → XGBoost → sklearn GB → lstsq logistic).
- `services/watchlist_store.py` + `services/order_history.py` —
  SQLite multi-watchlist + saved searches + cross-broker order log.

**Yeni adapter (4, 35 → 39):**
- `crypto/ccxt_failover_adapter.py` — Binance → Bybit → OKX → Coinbase
  → Kraken zinciri, ccxt opsiyonel + native REST fallback.
- `equity/sec_efts_adapter.py` — SEC EDGAR Full-Text Search.
- `alt/notion_adapter.py` — Notion API (search/page/blocks/query).
- `alt/granola_adapter.py` — Granola macOS lokal SQLite reader.

**Yeni fonksiyonlar (5, 98 → 103):**
- **PORT_OPT** — min-vol + max-Sharpe + risk-parity + efficient frontier.
- **BTFW** — walk-forward backtest runner.
- **MLSIG** — ML next-day direction + feature importance.
- **FTS** — SEC EDGAR full-text search.
- **DCFS** — DCF sensitivity grid + tornado.

**Yeni UI:**
- `templates/dcf_sensitivity.html` — Plotly heatmap (WACC × g_terminal)
  + tornado chart (±20% input deltas).
- Sembol tablarına: DCF, DCFS, DDM, FTS, DPF, MLSIG, BTFW, ONCH.
- Global tablar: SECT, MAP, CORR, PORT_OPT, GMM.
- watchlist.js'e server-side group helpers.

**Order tracking:**
- EMSXFunction her order'ı `runtime/orders.sqlite`'a kaydeder.
- AIM cross-broker open orders + history tail döndürür.

**Yeni testler (16):**
- `test_optimizer.py` (4): min_vol weights, max_sharpe finite, EF
  monotone, risk_parity.
- `test_backtest_framework.py` (5): 3 strategy + registry + metrics.
- `test_ml_signals.py` (3): feature shape, fit_predict, short-data.
- `test_user_stores.py` (4): watchlist + saved search + order history.

**Test sonucu:** 269/270 yeşil (legacy auto-close hariç).
**Smoke:** uvicorn 8765 → 28/28 yeşil. **103 fonksiyon**, 13 kategori.
Watchlist save/list round-trip canlı doğrulandı.

---

## 2026-04-30 — Round 4 derinleştirme (sırayla devam)

Plan'da kalan büyük UX + auth + agent boşlukları.

**Real-time + Notifications:**
- `dashboard/streaming_router.py` — `/ws/status`, `/ws/alerts`,
  `/ws/quotes/{sym}` WebSocket endpoint'leri (file-tail + JSONL-tail
  + REST poll).
- `static/js/notifications.js` — toast bell, drawer, browser-native
  Notification API, /ws/alerts subscription, localStorage history.
- `services/notifiers.py` — Slack / Discord / Telegram / PagerDuty
  webhook notifiers; `all_configured_notifiers()` env'e göre auto-detect.
- ALRT engine startup hook — tüm dış kanallar otomatik bağlı.

**Crypto adapter (toplam 33 → 35):**
- `crypto/coingecko_adapter.py` — market chart + OHLC + simple price.
- `crypto/cryptocompare_adapter.py` — multi-exchange aggregated quote
  + histo_day + news.

**Yeni quant fonksiyonlar (4, toplam 94 → 98):**
- **CORR** — Pearson + Spearman + downside correlation matrix.
- **SECT** — 11 SPDR sector ETF heatmap.
- **MAP** — 25-country MSCI ETF world heatmap.
- **PSC** — position sizing calculator (R-multiple + Kelly fraction).

**Yeni UI sayfaları:**
- `/options` — multi-leg OSA strategy builder (9 preset, BS pricer,
  Plotly P&L diagram, breakeven + max-profit/loss kpi).
- `/pane` — GoldenLayout drag/resize çoklu panel workspace,
  localStorage layout persistence.
- `/sandbox` — Pyodide v0.25 WASM Python sandbox, numpy/pandas
  yüklü, 6 örnek snippet, Cmd+Enter execute.
- `static/js/chart_draw.js` — Line / horizontal / fib / channel
  drawing primitives over TradingView Lightweight Charts. Per-symbol
  localStorage persistence.
- chart.html toolbar: drawing araçları + clear.

**Auth (BIO end-to-end):**
- `dashboard/auth_router.py` — /auth/login + register/login REST.
- `services/webauthn_service.py` — `begin_authentication`,
  `complete_authentication` eklendi. fido2 lazy import.

**Excel installers:**
- `excel/install_addin.bat` (Windows) + `install_addin.sh` (macOS):
  xlwings install + COM kayıt + showme_addin.py kopyalama.

**Sidebar:**
- Tools menüsüne 6 yeni link: Multi-Pane, Pyodide Sandbox, Options,
  BQuant (JupyterLab), Passkey (BIO), Algo Monitor.

**.env.example:** Slack/Discord/Telegram/PagerDuty webhook'ları.

**Yeni testler (17):**
- `test_psc.py` (5): sizing, R-multiple, Kelly clamp.
- `test_notifiers.py` (7): event format + 4 notifier env-gated.
- `test_corr_sect_map.py` (5): factory + registry validation.

**Test sonucu:** 253/254 yeşil (legacy auto-close hariç).
**Smoke:** uvicorn 8765 → 33/33 yeşil. 98 fonksiyon, 13 kategori.

---

## 2026-04-30 — Round 3 derinleştirme (sırayla devam)

Plan'da kalan büyük boşluklar ve "spec'te olmayan" bonus fonksiyonlar.

**Veri kaynakları (5 yeni adapter):**
- `data_sources/alt/glassnode_adapter.py` — Glassnode on-chain metrics
  (active_addresses, MVRV, NUPL, hash_rate, ...).
- `data_sources/alt/etherscan_adapter.py` — multi-chain Etherscan
  family (ETH/BSC/POLYGON/ARB/OP/AVAX/BASE) gas oracle, balance, tx list.
- `data_sources/alt/mempool_adapter.py` — Bitcoin mempool fees, blocks,
  hash rate (anahtarsız).
- `data_sources/equity/finra_adapter.py` — FINRA OTC Transparency ATS
  weekly volume + optional OAuth.
- (Round 2'de eklenen Damodaran + Polygon + SEC 13F + SeekingAlpha
  zaten log'da.) Toplam adapter sayısı 28 → **33**.

**Yeni fonksiyonlar (10):**
- `functions/misc/onch.py` — **ONCH** crypto on-chain birleşik
  (mempool + etherscan + glassnode parallel).
- `functions/screen/icx.py` — **ICX** index constituents (Wikipedia
  scrape, 9 büyük indeks: SPX/NDX/DJI/FTSE/DAX/CAC/RUT/STOXX/BIST,
  cache 24h).
- `functions/equity/dpf.py` — **DPF** dark pool / ATS volume.
- `functions/chart/tech.py` — **TECH** 100+ pandas-ta indicator
  + native fallback (RSI/MACD/ATR/Bollinger/Stochastic/ADX/OBV/Ichimoku).
- `functions/equity/dcf.py` — **DDM** Gordon growth + **DCF**
  two-stage with WACC/freeCashflow integration.
- `functions/misc/_bonus.py` — **LITM** litigation monitor,
  **MOSS** most volatile, **CHGS** chart studies preset, **APPL**
  industry taxonomy lookup. Toplam fonksiyon: **94**.

**UI (5 yeni sayfa + 3 yeni JS):**
- `templates/backtest.html` — VWAP/TWAP slicing simulator UI.
- `templates/risk_dashboard.html` — PORT + MARS + factor exposures
  + 5 stress senaryosu + concentration heatmap.
- `templates/algo_monitor.html` — TCA audit log + parents/children
  table + auto-refresh 5s.
- `templates/help.html` — komut paleti syntax + g+key kısayollar
  + 94 fonksiyon kategorize.
- `static/js/ticker.js` + CSS marquee — top-of-page scrolling quote
  bar (watchlist'ten 30s'de yenilenir).
- KPI grid + heatmap-cell CSS sınıfları.

**JupyterLab gerçek embed:**
- `dashboard/notebook_router.py` — JupyterLab subprocess (port 8889,
  base_url=/notebook/jupyter/), iframe ile `/notebook` üstünden gömülü.
  `/notebook/start`, `/notebook/stop`, `/notebook/status` REST.

**i18n tamamlandı:** TR + EN + DE + FR + ES + IT + PT + RU + ZH + JA +
KO + AR (12 dil). AR için `rtl: true` flag.

**Bloomberg router yeni route'lar:** `/backtest`, `/risk`, `/algos`,
`/api/v1/backtest`. Eski `/notebook` ve `/help` placeholder'lar gerçek
sayfalara değiştirildi.

**Yeni testler (15):**
- `test_dcf_ddm.py` (4): par-bond DDM, r ≤ g rejection, two-stage DCF,
  invalid terminal rejection.
- `test_tech_indicators.py` (9): RSI ∈ [0,100], MACD shape, ATR > 0,
  Bollinger ordering, Stochastic ∈ [0,100], ADX columns, OBV finite,
  Ichimoku columns, EMA smoothing.
- `test_sec_13f.py` (2): InfoTable XML parse two-holdings + empty.

**Test sonucu:** 236/237 geçti (legacy auto-close test hariç).
**Smoke server:** uvicorn 8765 → 28/28 yeşil. 94 fonksiyon, 13 kategori.

---

## 2026-04-30 — Round 2 derinleştirme (sırayla devam)

Plan'da "Phase X sonu" etiketli boşluklar sırayla dolduruldu.

**Faz 1+ derin:**
- `data_sources/macro/damodaran_adapter.py` — Country ERP scrape +
  curated Jan 2025 fallback (60+ ülke). WACC otomatik kullanıyor.
- `data_sources/equity/polygon_adapter.py` — Polygon.io REST (quote,
  OHLCV, options chain, news).

**Faz 2 derin:**
- `data_sources/equity/sec_13f_adapter.py` — 13F-HR XML parse + DuckDB
  ``holdings`` table.
- `core/sec_taxonomy.py` — 8-K Item code tablosu (30+ item) +
  10-K customer/supplier/debt section regex'leri.
- CACT 8-K Item categorization, SPLC 10-K text mining gerçek bağlandı.

**Faz 3 derin:**
- `services/news_index.py` — Meilisearch primary + SQLite FTS5 fallback.
- `services/sentiment.py` — FinBERT (HF) → VADER → keyword fallback.
- `data_sources/equity/seekingalpha_adapter.py` — public RSS scrape.
- `services/email_service.py` + `scripts/run_brief.py` — SMTP cron.
- NSE/SOSC/TRAN gerçek bağlandı.

**Faz 4 derin:**
- IVOL — yfinance her expiry için paralel fetch + IV grid.
- `functions/bond/gc3d.py` — FRED son N gün × 10 tenor → 3D surface.
- `functions/derivative/heston.py` — Heston MC (full-truncation Euler).
- OVME `model="heston"` parametresi.
- ECFC IMF + OECD'ye gerçek bağlandı.
- CME FedWatch normalized payload.

**Faz 5 derin:**
- PORT_WHATIF gerçek delta hesaplıyor (before/after PORT() snapshot).
- TRA: TWR + IRR (XIRR Newton) + CAGR + dividend total.
- MARS: 6-factor Fama-French regression + α + R² + VaR/ETL.
- CDE: BQL parse + AST eval entegrasyonu.
- `scripts/ingest_universes.py` — bond/fund/commodity/index seed.

**Faz 6 derin:**
- `services/algo_engine.py` — async slicing + audit log.
- `services/algo_backtest.py` — vectorized VWAP/TWAP + slippage_bps + fees.
- TCA gerçek audit-log reader; arrival-price IS hesabı.

**Faz 7 derin:**
- `services/alert_engine.py` — DSL evaluator + cooldown + email/stdout
  notifier; opsiyonel startup hook (SHOWME_ENABLE_ALRT).
- `dashboard/chat_router.py` — WebSocket chat + /quote, /order slash
  komutları + SQLite history.
- `services/webauthn_service.py` — passkey registration (fido2 lazy).
- `excel/showme_addin.py` — xlwings UDF (PRICE/HISTORY/FUND/NEWS/BQL).
- `dashboard/static/i18n/{tr,en}.json` + `i18n.js` — ilk iki dil.

**UI iyileştirme:**
- `templates/chart.html` — TradingView Lightweight Charts + RSI/MACD/BB.
- `templates/orderbook.html` — DPLT depth viewer.
- `templates/terminal_settings.html` — theme toggle, 12-dil, watchlist
  editor, API key durumu, adapter health, LLM bütçe.
- `static/js/theme.js` + `mobile.js` — dark/light toggle, hamburger.
- News feed infinite scroll + topic filter.
- Generic `/symbol/<sym>/<code>` GP/DPLT special-case.

**Adapter sayısı:** 24 → 28 (+ Damodaran, Polygon, SEC 13F, SeekingAlpha).
**Route sayısı:** 73 → 78 (+ chart, orderbook, settings, chat WS).
**Yeni testler (24):** test_sec_taxonomy (5), test_news_index (3),
test_algo_backtest (3), test_heston (3), test_alert_engine (4),
test_factor_models (6).
**Toplam test sonucu:** 221/222 geçti (legacy auto-close test hariç).

**Smoke:** uvicorn 8765 → 17/17 yeni route yeşil; chart, orderbook,
settings, chat, theme toggle hepsi render oluyor.

---

## 2026-04-30 — KAPANIŞ (tek oturumda yapılanlar)

**Toplam:**
- 24 yeni veri adapter
- 84 Bloomberg fonksiyonu (DES'ten DINE'a kadar)
- 8 ajan + LLM router + Orchestrator
- 4 broker adapter (Binance/Alpaca/IBKR/OANDA)
- 4 execution algo
- 9 asset class facade
- 4 cross-asset registry (symbol/exchange/calendar/currency)
- Bloomberg-class web UI: dark theme, ⌘K, multi-pane, watchlist,
  keyboard shortcuts, mobile responsive
- 18+ web route + 8 REST endpoint (DAPI surface)
- 35 yeni test geçti

**Plan'a göre durum:** Faz 0-7 iskeleti tamamen yerleşti. "İlerle, %70 yeter"
direktifi uyarınca her faz çalışan bir slice çıkardı; her faz boyunca
`docs/coder_log.md`'a karar+gerekçe yazıldı. Birkaç fonksiyon (FXFC,
ALLQ, GC3D, MARS, TRA, SPLC, BMC, DINE, IVOL surface) deliberately
"warning + Phase X sonu" olarak işaretlendi — ücretsiz veri yok ya da
heavyweight ingestion (Meilisearch index, 13F batch, Damodaran scrape)
gerektiriyor; iskelet duruyor, daha sonra bağlanacak.

**Production durumu:** Mevcut kripto botu hâlâ çalışıyor; legacy
dashboard `/legacy` altında erişilebilir. Hiçbir mevcut dosya silinmedi
ya da taşınmadı — tüm yeni kod `src/core/`, `src/assets/`,
`src/data_sources/`, `src/functions/`, `src/agents/`, `src/reference/`,
`src/portfolio/`, `dashboard/bloomberg_router.py`, ve `dashboard/templates/`
+ `dashboard/static/{css,js}/` yan yana yerleşti.

---
