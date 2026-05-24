# showMe Bot Sistemi — Kapsamlı Audit Raporu

**Tarih:** 2026-05-23  
**Kapsam:** Bot oluşturma ekranı (BOT/BOTS/STRA/TMPL/BDA panelleri) + API sistemi (`/api/bots/*`, `/api/strategies/*`, `/api/templates/*`, `/api/assistant/*`) + bot runner/store/record/performance + canlı integration  
**Yöntem:** 3 paralel agent (Backend statik + UI statik + Canlı integration) + pytest/vitest baseline + kullanıcı bildirimi (Welcome dashboard)

---

## Executive Summary

| Metrik | Değer |
|---|---|
| **Toplam bulgu** | **136+** (Backend 64 + UI 52 + Canlı 20) + Welcome 4 + Headline kaldırma 1 |
| **Critical (showstopper)** | 18 |
| **High** | 51 |
| **Medium** | 45 |
| **Low** | 25 |
| **Test coverage gaps** | 37 |
| **Mevcut test baseline** | 47 pytest + 36 vitest **HEPSİ YEŞİL** (yanıltıcı — sözleşmeyi doğruluyor, sözleşme hatalı) |

**Ana tespit:** Mevcut test suite'inin %100 yeşil olması bir bug'ın olmadığını DEĞİL, **testlerin yanlış davranışı pekiştirdiğini** gösteriyor. Live trading hazardları, race condition'lar, contract drift, ve Welcome dashboard'daki hardcoded fixture'lar test edilmiyor.

---

## TOP 10 SHOWSTOPPER — Canlı Para Riski + Crash + Data Corruption

> Bu 10 madde live trade'e geçmeden ÖNCE fix edilmeli. Sıralama risk × kolaylık skoruna göre.

### 🔴 S1 — Live Exit'te BUY emri fire ediliyor (long pozisyon EXIT = 2x exposure)
- **Dosya:** `backend/showme/bots/runner.py:175-188`
- **Bug:** `side = OrderSide.BUY if last_event.kind == "entry" else OrderSide.SELL` — ama exit için pozisyonu kapatmak gerekirken yeni bir SELL submit ediliyor (fresh order, mevcut pozisyon quantity'si yok). Long bot exit'inde de yeni short açılıyor.
- **Impact:** Live mode'da çift exposure (long pozisyon + yeni short → broker reddetmediyse 2x leverage).
- **Repro:** Long bot, entry fire eder, exit kuralı tetiklenir → emir defterinde yeni BUY (kod yorumu "Position-side reversal for exit" bug'ı itiraf ediyor).

### 🔴 S2 — `sizing_value` quantity olarak gönderiliyor (kind ne olursa olsun)
- **Dosya:** `backend/showme/bots/runner.py:180, 184`
- **Bug:** Spec `sizing_kind ∈ {fixed_quote, fixed_base, risk_pct}` (spec.py:59) ama runner her zaman `quantity=spec.position.sizing_value`. Kullanıcı "100 USDT" demek istese, broker'a "100 BTC al" gidiyor.
- **Impact:** BTC @ $60k'da 600x over-leverage. Broker balance kontrolü tek savunma.
- **Repro:** Bot create `position.sizing_kind=fixed_quote, sizing_value=100`, mode=live, enable → tick'te `submit_order(quantity=100)` çağrılır.

### 🔴 S3 — `_is_ccxt` prefix prod'da HIÇ match etmiyor (canlı bot'lar sessizce çalışmıyor)
- **Dosya:** `backend/showme/bots/ohlcv.py:22-23`
- **Bug:** Kontrol `name.startswith("ccxt:")`. Ama prod factory broker'ı `binance:cred-id` formatında üretir (`backend/showme/server_routes/broker.py` factory). Test fixture `ccxt:binance:c1` kullanıyor — test geçiyor ama prod'da hiçbir tick OHLCV alamıyor.
- **Impact:** Production'da hiçbir bot canlı trade etmez; sessiz `BotRunnerError`.
- **Repro:** Real credential register et → bot create → enable → log'da `unknown broker` veya OHLCV fetch fail.

### 🔴 S4 — Sidecar restart'ta `trade` permission re-check yok
- **Dosya:** `backend/showme/bots/lifespan.py` → `start_all`
- **Bug:** Boot'ta tüm `enabled=True` bot'lar yeniden başlatılır; ancak credential'ın `trade` permission'ı route layer'da kontrol edilir (bots.py:206-227), runner internal path'i bypass eder. Permission revoke edilmiş credential ile bot canlı trade etmeye devam eder.
- **Impact:** Persistent live-mode escape. Kullanıcı "credential'ı disable ettim" sanırken trade devam eder.
- **Repro:** Bot enable et (live), credential trade permission'ı revoke et, sidecar restart, bot yeniden başlar.

### 🔴 S5 — Bot oluşturmada Foreign Key validation YOK
- **Endpoint:** `POST /api/bots` (`backend/showme/server_routes/bots.py:46-50`)
- **Bug:** `strategy_id`, `credential_id`, `exchange_id` herhangi bir non-empty string olabilir. Backend pydantic'i sadece tipini kontrol ediyor, var olduğunu değil. Curl ile `"strategy_id":"does-not-exist-xxx"` gönderilince 200 OK.
- **Impact:** Permanent kırık bot'lar store'a yazılır; UI'da gözükür, leaderboard'da yer kaplar, tick'lerde `unknown broker` log noise üretir.
- **Repro:** `curl -X POST .../api/bots -d '{"strategy_id":"zzzz",...}' → 200 OK`.

### 🔴 S6 — JSON store atomik değil (crash = bot kayboluyor)
- **Dosya:** `backend/showme/bots/store.py:106` + `strategies/store.py:97`
- **Bug:** `p.write_text(rec.to_json())` — temp file + rename + fsync yok. Crash mid-write → 0 byte dosya → list()'te `JSONDecodeError` swallow ediliyor (line 69) → bot kayboluyor.
- **Impact:** macOS sleep, OOM, SIGKILL → veri kaybı, kullanıcıya hiçbir uyarı yok.
- **Repro:** Sidecar'ı `save` çağrısı sırasında `kill -9` → bot kayıp.

### 🔴 S7 — Path traversal: `bot_id` URL paramı dosya yoluna sızıyor
- **Dosya:** `backend/showme/bots/store.py:56-57` + `strategies/store.py:51`
- **Bug:** `_path = self._dir / f"{bot_id}.json"`. URL'den gelen `bot_id` validasyonsuz. `DELETE /api/bots/../../etc/passwd` → sidecar UID'inin yazabildiği dosya silinebilir.
- **Impact:** Yerel ayrıcalık yükseltme (local kötü niyetli süreç dosya sistemine müdahale eder).
- **Repro:** `curl -X DELETE ".../api/bots/..%2F..%2F<target>"` (path encoding).

### 🔴 S8 — Tick + CRUD race: signal log clobber ediliyor
- **Dosya:** `backend/showme/bots/runner.py:104-204` ↔ `server_routes/bots.py:153-185`
- **Bug:** Tick `store.get` → evaluate → `store.save(rec.append_signal(...))`. Eş zamanlı `PUT /api/bots/{id}` ise `existing` okur → mutate → write. Last-writer-wins. Tick'in eklediği signal silinir, `last_processed_event` reset olur, sonraki tick aynı event'i tekrar fire eder.
- **Impact:** Aynı entry/exit duplicate fire — order book'ta çift emir.
- **Repro:** Bot enabled, eş zamanlı PUT (UI'dan symbol değiştir) — race konumlanırsa duplicate signal.

### 🔴 S9 — `/api/strategies/{id}/preview?limit=-5` → 500
- **Dosya:** `backend/showme/server_routes/strategies.py:119`
- **Bug:** `np.random.default_rng().normal(0,1,limit)` negatif `limit` ile `ValueError: negative dimensions are not allowed`. FastAPI 500 + raw stack trace.
- **Impact:** STRA pane preview butonu (kullanıcı `&lt;input type="number" min={5}&gt;` bypass eder veya curl test eder) → sidecar internal error spam.
- **Repro:** `curl -X POST ".../api/strategies/{id}/preview?limit=-5" → 500`.
- **Fix:** `limit: int = Query(200, ge=1, le=10_000)`.

### 🔴 S10 — `/api/assistant/strategy-from-text` non-string text → 500
- **Dosya:** `backend/showme/server_routes/assistant.py:20`
- **Bug:** `text = (payload or {}).get("text") or ""; if not text.strip()` — `text=42` (int) → `int.strip()` → AttributeError → 500.
- **Impact:** BDA panel API contract'ı bypass edilirse crash. JSON'da yanlış tip → sidecar 500.
- **Repro:** `curl -d '{"text": 42}' → 500`.
- **Fix:** `if not isinstance(text, str): raise HTTPException(400, "text must be string")`.

---

## Bölüm 1 — Backend Bot Sistemi (Agent A — 64 bulgu)

### 1.1 Critical (11 ek)

Yukarıdaki S1–S8'e ek olarak:

- `runner.py:50-51` — `enable()` race: bot enable'ı tick mid-flight'da → stale `rec` save'i, signal_log'u backward yaratıyor.
- `runner.py:38-39` — `enable()` `is_running()` kontrolü async-safe değil; iki rapid `enable` aynı bot için iki task spawn edebilir (double-tick).
- `runner.py:66, 77` — `except (asyncio.CancelledError, Exception)` cancel propagation'ı bozuyor; shutdown'da task ölmüş gibi görünüp aslında zombie.
- `runner.py:81-102` — Crashed `_run_loop` restart edilmiyor; `enabled=True` disk'te kalıyor, UI bot "running" zanneder.
- `runner.py:96 → spec.py:94` — Strategy JSON bozuksa `UnknownStrategy` değil ham `JSONDecodeError` propagate ediyor → tick kill.
- `lifespan.py:14-19` — `get_runner()` thread-safe değil; ilk caller race'iyle iki runner instance.
- `bots.py:178` — Live-mode gate bypass: `existing.mode == "live"` ise yeni credential PUT'ı re-check edilmez. Yeniden bağlanan trade-perm-yok credential canlı çalışır.

### 1.2 High (28 — özet)

| # | Dosya:Line | Bug | Impact |
|---|---|---|---|
| H-1 | runner.py:175-188 | BUY-on-exit (S1) | 2x exposure |
| H-2 | runner.py:180,184 | sizing_value as qty (S2) | 600x over-leverage |
| H-3 | runner.py:159-162 | `bar_index != len(df)-1` → erken event'ler silently drop | Signal kaybı |
| H-4 | runner.py:166-169 | `(bar_time, kind)` dedup pandas Timestamp string'ine bağlı; pandas upgrade'de bozulur | Çift fire |
| H-5 | runner.py:142-148 | Skipped/error event'ler `kind="entry"` olarak yazılıyor → feed'i kirletiyor | Yanıltıcı UI |
| H-6 | bots.py:178 | Live mode gate bypass (S4 ile alakalı) | Trade-perm-yok credential live |
| H-7 | bots.py:206-227 | Enable gate confirm_account_label sadece transition'da; existing live'a re-enable check yok | Bypass |
| H-8 | bots.py:46-47 | `enabled` field strip yok; sadece set False | Defansif değil |
| H-9 | bots.py:84-114 | Performance N×StrategyStore.fresh() — dir mkdir her loop | Disk thrash |
| H-10 | bots.py:55-82 | `bots_feed` event loop blocker; sync `store.get` her bot için | UI poll = sidecar freeze |
| H-11 | performance.py:53 | `entry_price<=0` continue ama `open_entries.pop` rollback yok → FIFO desync | Yanlış PnL |
| H-12 | performance.py:56 | PnL `sizing_value` quote zannediyor; runner base zannediyor (S2 ile bağlantılı) | Engineler arası tutarsız |
| H-13 | evaluate.py:130 | `Position.side="short"` ignore — entry/exit kind sequence yanlış; short bot long açar | Dead code mis-trade |
| H-14 | evaluate.py:62 | `equals_approximately` `right=0` → NaN → every bar True | False positive flood |
| H-15 | spec.py:96-118 | Validator gap: `tolerance<0` accepted; `NaN` tolerance accepted | Sessiz hep-False |
| H-16 | compute.py:54-57 | `_compute_bollinger_bands` sadece midline; upper/lower yok | bb-squeeze template her zaman False |
| H-17 | compute.py:46-51 | `_compute_macd` sadece MACD line; signal histogram yok | Template params ignore |
| H-18 | compute.py:144-145 | PSAR `low[i-2]` fallback ilk 2 barda yanlış | İlk 30 bar inaccurate |
| H-19 | templates.py:23,32 | YAML load fail silent → `/api/templates` empty list → UI "no templates" | Hata gizleniyor |
| H-20 | templates.py:63 | `dict(entry.spec_template)` shallow copy; nested list mutate cache'i kirletebilir | Fragile |
| H-21 | assistant.py:35 | `save=True` `validate_against_catalog` bypass | Geçersiz spec persist |
| H-22 | parser.py:36-40 | `_find_indicator` dict iteration order'a bağlı | Brittle |
| H-23 | parser.py:131-138 | "30 altında" hem entry hem exit'e atanabilir | Ambiguous |
| H-24 | parser.py:183-194 | EMA `period*3` long; 200 → 600 (200 bar'da all-NaN) | Strategy hiç fire etmez |
| H-25 | strategies.py:117-126 | Preview synthetic random walk volatility=1; high-threshold strategy events:[] döner | "broken" sanılır |
| H-26 | bots.py:25-34 | `_credential_perm` her exception swallow → "no trade perm" yanıltıcı 400 | Yanlış teşhis |
| H-27 | bots.py:153-185 | `update_bot` pydantic error → leaks internal raw message | UI'da çirkin |
| H-28 | strategies/store.py:75 | Empty `updated_at` reverse sort'ta last → yeni strateji görünmez | UX |

### 1.3 Medium (16) ve Low (9)

Detaylar için Agent A çıktısına bakın. Öne çıkanlar:

- **M-21 (S3):** `_is_ccxt` prefix prod'da match etmiyor — tüm canlı bot stack'i sessiz kırık.
- **M-19:** `max_drawdown` mutlak PnL biriminde, UI % bekliyor → kontrat drift.
- **L-2:** `BotMeta.to_dict()` annotation tutarsız (kozmetik).
- Detaylı liste 25 madde — dosyada eksiksiz.

---

## Bölüm 2 — UI Bot Panelleri (Agent B — 52 bulgu)

### 2.1 Critical (5)

- `BOT.tsx:216-220` — **Sil butonu confirmation YOK.** Tek tıklama → bot siliniyor. Live + enabled bot bile.
- `BOT.tsx:191-209` + `bot-store.ts:113-141` — Empty strategy/credential save eden gate yok; backend 400 dönüyor, UI ham pydantic mesajı gösteriyor.
- `BOT.tsx:127-194` — **shadow→live save'de `confirm_account_label` gönderilmiyor.** Backend rejects 400; kullanıcı "form bozuk" sanır. confirmLabel sadece `enable()`'a wired, `save()`'e değil.
- `bot-store.ts:113-141` — **Concurrent save guard yok.** Rapid double-click Kaydet → duplicate bot.
- `TMPL.tsx:112-119` — **Modal orphan:** Oluştur fire eder, Kapat instantiate request in-flight iken kapatılabilir → strategy persist edildi ama UI feedback kayıp.

### 2.2 High (17 — özet)

| # | Dosya:Line | Bug |
|---|---|---|
| H-1 | BOT.tsx:144-148 | Credential deselect'te stale `exchange_id` kalıyor |
| H-2 | bot-store.ts:143-186 | `remove/enable/disable` `error: null` reset yapmıyor |
| H-3 | bot-store.ts:143-156 | `remove()` loading state yok → çoklu DELETE → 404 |
| H-4 | BDA.tsx:44-50 | "Strateji öner + kaydet" sonrası strategies dropdown refresh yok |
| H-5 | bots-supervision-store.ts:53-69 | `records`/`signals` array guard yok → null body crash |
| H-6 | BOTS.tsx:62-69 | "Son sinyal" stale (poll desync) — staleness indicator yok |
| H-7 | bots-supervision-store.ts:35-43 | `signals_today` UTC kullanıyor — İstanbul (UTC+3) için günler boyu off-by-one |
| H-8 | BOTS.tsx:153-157 | 10s poll tab visibility ignore; Yenile debouncing yok |
| H-9 | BOT.tsx:43 / BOTS.tsx:127 | `key={i}` positional — feed re-sort'ta DOM identity bozulur |
| H-10 | BOT.tsx:170-174 | `tick_interval_seconds` `||60` fallback — "0" girince sessizce 60'a snap |
| H-11 | STRA.tsx:96-100 | `catalogEntries[0]?.id ?? "rsi"` — katalog yüklenmeden default reference |
| H-12 | STRA.tsx:101-120 | Alias collision detect yok → React duplicate key warning |
| H-13 | STRA.tsx:210-214 | Rule `right` free-text, validation yok, autocomplete yok |
| H-14 | bot-store.ts:122,131 | PUT body'de `signal_log` ve `last_processed_event` strip edilmiyor → runner state overwrite |
| H-15 | BDA.tsx (selectedStrategy lifecycle) | Açıklamada eski state takılı kalır |
| H-16 | BOT.tsx:225 | Signal log count loaded draft'tan; live bot yeni signal eklediğinde refresh yok |
| H-17 | BOTS.tsx:155-156 | Concurrent loadAll race; last-write-wins by request ordering |

### 2.3 Medium (21) ve Low (12)

Öne çıkanlar:

- **M-1:** TMPL modal focus management yok (autofocus, focus trap, Escape, focus return).
- **M-9:** BDA low-confidence parse "Edit in STRA" CTA yok.
- **M-13:** STRA `remove()` confirmation yok — orphan bot referansları (S5 ile bağlantılı).
- **M-15:** TMPL `recommended_symbols.join(", ")` null guard yok — `.join` throw → pane crash.
- **L-2:** `TIMEFRAMES` tuple type mismatch (compile-time yakalanmıyor).

---

## Bölüm 3 — Canlı Runtime (Agent C — 20 bulgu + 60 endpoint matrix)

### 3.1 Critical (2 ek)

- S9 (`/preview?limit=-5` → 500), S10 (`assistant text=42` → 500) — Yukarıda detaylı.

### 3.2 High (6 ek)

- **C-H1:** Sil no confirmation (UI doğrulanmış via `window.confirm` stub — hiç çağrılmıyor).
- **C-H2:** Backend 4xx detail UI'da strip ediliyor — kullanıcı sadece `"/api/bots: 400 Bad Request"` görür, `detail` field'ı (credential_id eksik vb.) gizlenir.
- **C-H3:** **No FK validation on POST /api/bots** (S5).
- **C-H4:** **DELETE /api/strategies cascade yok** — orphan bot kalır, UI dropdown sessizce reset eder ve PUT'la `strategy_id=""` save eder.
- **C-H5:** PUT bot empty `strategy_id`/`credential_id` accepted — `min_length` yok.
- **C-H6:** **Spec drift:** Brief `/evaluate` der, actual `/preview`. Brief `/strategy/from-text` der, actual `/strategy-from-text` (hyphen). Anyone reading docs hits 404.

### 3.3 Medium (8) ve Low (4)

Öne çıkanlar:

- **C-M1:** `mode="yolo"` sessizce `"shadow"`'a normalize ediliyor (200 OK, no warning).
- **C-M2:** Template instantiate'de `symbol: 12345` (int) → `["12345"]` string'e coerce.
- **C-M3:** `indicators[]` array upper bound yok — 1000 indicator persist 20ms (DoS surface).
- **C-M4:** Extra fields (örn. `capital: 1000`) silently dropped — kontrat drift (gelecekte plan vardı mı belli değil).
- **C-M5:** BOT pane "SHADOW" badge mode + enabled karıştırıyor — disabled-live bot da "OFF" gösterir.
- **C-M7:** Cold boot `/api/function-index 6000ms timeout` warning'leri token loader yetişene kadar ~30 satır spam.

### 3.4 Endpoint Matrix Özeti

- **60 endpoint çağrısı / 58 pass / 2 fail (5xx).**
- 19 UI smoke step / 18 pass / 1 fail (Sil no-confirm) + 1 papercut (400 detail strip).
- Pre-mevcut state: 5 strategies + 0 bots; audit sonu ~30+ test artifact `~/Library/Application Support/showMe/`.
- Sidecar boot 0.5s; UI vite 5173. Auth middleware enforced (401 expected paths).

Detaylı tablo Agent C output'unda — 60 satır curl + status + time + verdict.

---

## Bölüm 4 — Welcome Dashboard (Kullanıcı Bildirimi)

### 4.1 Sentiment Panel — Tamamen Hardcoded

- **`Welcome.tsx:467`:** `<strong>Cautiously Bullish</strong>` literal text
- **`Welcome.tsx:468`:** `<span>+32%</span>` literal yüzde
- **`Welcome.tsx:461`:** `aria-label="Sentiment cautiously bullish"` literal a11y
- **`index.css:6842`:** `transform: rotate(-58deg)` gauge needle CSS-katı

**Mevcut altyapı (kullanılmıyor):** showMe'de zaten XSEN plug-in var:
- `/api/x/symbol_chip?symbol=X` → `{bullish, mentions}`
- `/api/x/analyze` → `XSentiment`
- `/api/x/instant_events` → `InstantEvent[]`

**Fix:** Welcome'a sentiment store ekleyip watchlist aggregate'i için bu endpoint'leri tüketmek. Needle pozisyonu için inline `style={{ transform: `rotate(${-90 + score*180}deg)` }}`.

### 4.2 Diğer Hardcoded Paneller

- `Welcome.tsx:244` — `BRIEF_ITEMS` (Today's Brief / AI Narrative tüm satırları sabit)
- `Welcome.tsx:334` — `MOVERS` (Today's Movers gainers/losers sabit)

Bu paneller mock data — diğer panel'ler (`watchRows`, `positions`, news `top`) gerçek API kullanırken bu üçü kasıtsız fixture sızıntısı.

### 4.3 Tamamlanan Fix — "MARKETS ARE QUIET. CONVICTION IS NOT." Headline Kaldırıldı

- `Welcome.tsx:390-392` (h2) silindi
- `Welcome.tsx:384` `aria-labelledby="terminal-home-heading"` temizlendi (dangling reference önlendi)
- Preview ile canlı doğrulandı: eyebrow korundu, layout etkilenmedi, console temiz
- **Native rebuild pending** — `feedback_native_rebuild` der ki `.app` rebuild gerek; aggregate fix batch'ine bırakıldı

---

## Bölüm 5 — Mevcut Test Coverage Gaps (37)

### Backend (20)

1. Tick + CRUD concurrent yarış yok
2. Atomic-write / crash resilience yok
3. `bar_index != len(df)-1` negative case yok
4. Live-mode credential swap bypass test edilmiyor
5. **`_is_ccxt` prefix mismatch** — test fixture broker name'i prod ile uyuşmuyor
6. `Position.side="short"` zero coverage
7. `compute.py` indikatör output'ları unit-test'siz
8. `_compute_bollinger_bands` upper/lower kayıp olduğu test edilmiyor
9. `compute_trades` FIFO leak (`entry_price<=0`) yok
10. `bots_feed` empty `bar_time` sort'u test edilmiyor
11. Path traversal `bot_id`/`strategy_id` yok
12. `kind="exit"` runner.tick path'i hiç exercise edilmiyor (BUY-on-exit bug görünmez)
13. `sizing_value` semantik cross-validate yok
14. `lifespan.startup → start_all` trade-perm check skip'i invisible
15. `update_bot` `signal_log` field intact preserve test'i sadece negative branch
16. Templates route bad YAML end-to-end yok
17. Assistant `save=True` invalid spec persist test'i yok
18. `equals_approximately` `right=0` False assert yok
19. `BotRunner` non-tick exception recovery yok
20. NL parser mixed-case (`RsI`) handling yok

### UI (17)

21. Rapid double-Kaydet yok
22. Shadow→Live save kontrat testi yok
23. Sil confirmation testi yok
24. Empty strategy/credential validation gate yok
25. Credential `— seç —` deselect stale exchange_id yok
26. Stale error persistence assert yok
27. `loadAll()` interval race yok
28. Orphan strategy remove → bot etkisi yok
29. TMPL modal focus management yok
30. BDA save sonrası dropdown refresh yok
31. `signals_today` UTC/local off-by-one yok
32. Malformed backend payload guard yok
33. `performance-store` zero coverage
34. STRA Preview button gating yok
35. STRA "+ Kural ekle" indicator-less rule degeneracy yok
36. SignalEntry `error && order_id` ikisi set olunca rendering yok
37. SignalLog key collision yok

---

## Bölüm 6 — Önerilen Fix Sırası (Prioritized)

> Aşağıda her satır 1 PR scope'unu hedefler. Sıra: live trade risk → data corruption → UX → cosmetic.

### Faz 1 — Live trade hazardlarını mühürle (S1–S5, ~1 gün)
1. **S2** sizing_value kind awareness — `runner.py` quantity hesabı `sizing_kind`'e göre.
2. **S1** BUY-on-exit fix — exit'te `close_position()` veya correct side+qty.
3. **S3** `_is_ccxt` prefix prod'a hizala — factory output formatına göre kontrol.
4. **S4** `start_all` trade-perm re-check ekle.
5. **S5** `POST /api/bots` strategy/credential/exchange FK validation.

### Faz 2 — Data corruption hattını kapat (S6–S8, ~0.5 gün)
6. **S6** Atomic JSON write (`tmp + os.replace + fsync`) — bot ve strategy store.
7. **S7** `bot_id`/`strategy_id` regex (UUID/hex) — path traversal block.
8. **S8** Per-bot asyncio.Lock — tick read-modify-write atomik.

### Faz 3 — Endpoint hardening (S9–S10 + C-H6, ~0.5 gün)
9. **S9** Preview `limit` `ge=1, le=10_000`.
10. **S10** Assistant `text` type guard.
11. **C-H6** Route alias'ları ekle (`/evaluate` → `/preview` redirect; `/strategy/from-text` → `/strategy-from-text` redirect) veya brief'i fix et.

### Faz 4 — UI critical (Agent B C-1..C-5, ~0.5 gün)
12. **B-C1** Sil + STRA Sil window.confirm.
13. **B-C2** Kaydet client-side gate (strategy_id && credential_id && symbol).
14. **B-C3** Save flow'una confirmLabel wiring.
15. **B-C4** Concurrent save guard (`loading` disable button).
16. **B-C5** TMPL modal Kapat disabled-while-creating.

### Faz 5 — Welcome dashboard (~1 gün)
17. Sentiment panel'i `/api/x/analyze` (aggregate) veya `/api/x/symbol_chip` (per-watchlist) ile bind et.
18. Gauge needle dynamic `transform`.
19. `BRIEF_ITEMS` ve `MOVERS` — gerçek data source seç (yfinance daily movers? AI brief endpoint?) veya pane'i "demo data" badge'iyle işaretle.

### Faz 6 — Contract drift + UX papercut (~0.5 gün)
20. UI 4xx `detail` field surface (BOT pane error rendering).
21. PUT bot empty strategy/credential block (backend `min_length=1`).
22. DELETE strategy cascade — refuse 409 if bots reference it (öneri).
23. `signals_today` local-date.
24. BOT pane SHADOW badge — mode + enabled ayır.
25. Function-index timeout spam — token-wait sync'le.

### Faz 7 — Coverage gap kapama (~1 gün)
26. 37 gap'in en az 20'sini regression test olarak ekle.
27. Concurrent CRUD + tick async test fixture'ı kur.
28. Native build + .app deploy (`feedback_native_rebuild`).

---

## Ek — Test Baseline Sonucu

```
Backend: 47 passed in 1.63s  (test_bot_runner, test_bot_store, test_bot_record, 
                               test_bots_feed, test_bots_route, test_performance, 
                               test_assistant_route)
UI:      36 passed in 1.29s  (BOT, BOTS, STRA, TMPL, BDA + bot-store + bots-supervision-store)
```

**Uyarı:** TMPL.test.tsx > "Oluştur button calls instantiate" — 2× `act(...)` warning (TMPLPane line 8:41). State update test bitimi sonrası fire ediyor (instantiate response promise). Test pass ediyor ama leak göstergesi.

---

**Rapor sonu.** Toplam bulgu: 136 + Welcome 4 + Headline 1 = **141**. Mevcut test'ler 83/83 yeşil. Live trading'e kesinlikle hazır değil; Faz 1-3 minimum.
