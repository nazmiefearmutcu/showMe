# showMe Bot Sistemi — Konsolide Audit Raporu

**Tarih:** 2026-05-23
**Kapsam:** Bot oluşturma ekranı (BOT/BDA/STRA/TMPL panes) + API sistemi (`/api/bots/*`, `/api/strategies/*`, `/api/templates/*`) + Runtime engine (scheduler/evaluate/dispatch) + Supervisor/PERF entegrasyonu
**Yöntem:** 4 paralel agent ile bağımsız domain audit; her agent kendi pytest/vitest çalıştırdı, kod inceledi, kenar durum aradı.
**Test durumu:** Pytest 88/88 + 38/38 + 64/64, Vitest 75/75 + 43/43 — **HEPSI GREEN**. Bu bug'ların **hiçbiri** mevcut testler tarafından yakalanmıyor.

---

## YÖNETİCİ ÖZETİ

| Kategori | CRITICAL | HIGH | MEDIUM | LOW | Toplam |
|----------|----------|------|--------|-----|--------|
| API Contract (D/E/G route'ları) | 2 | 5 | 5 | 3 | 15 |
| Bot Engine Runtime | 5 | 6 | 5 | 6 | ~22 |
| UI BOT/BDA/STRA/TMPL | 5 | 12 | 10 | 10 | ~37 |
| Supervisor + Integration | 2 | 4 | 5 | 4 | 15 |
| **TOPLAM** | **14** | **27** | **25** | **23** | **~89** |

**En kritik ortak bulgular (4 audit'in birden tespit ettiği):**

1. **Cascade delete tamamen bozuk** — credential silinince live bot'lar orphan kalır, signal_log "broker unavailable" ile dolar, asyncio task zombileşir. Strategy silinince bot'lar ölü stratejiye bağlı kalır. Bot silme sırasında `_locks` map sızıntı yapar.
2. **Sizing math tutarsız** — `_resolve_quantity` (runner.py:31-72) negatif/aşırı büyük değerleri kabul eder + `_REFERENCE_EQUITY_USD = 10_000.0` hardcoded; `compute_trades` (performance.py:54-66) tüm sizing_kind'ları `fixed_quote` formülü ile hesaplar → `fixed_base` ve `risk_pct` stratejilerin PnL'leri **60000x off** olabilir.
3. **`evaluate()` state-amnesia** — her tick'te 200 bar üzerinde state machine `flat`'tan başlar; bot'un gerçek pozisyon durumunu bilmez. Rolling window'da tarihsel olaylar tetiklenmeye devam eder. Dedup zayıf.
4. **`signal_log` cap=100 + FIFO** — uzun süre çalışan bot'larda orphan exit pairing'i kaydırır; PERF metrics geri-dönüşsüz yanlışlanır. Round-trip trade history kaybı.
5. **Broker instance leak** — her tick'te `factory.get_broker(...)` yeni `CcxtBroker(...)` instance üretir, eski `aiohttp` connector'lar `aclose()` çağrılmadan dangling kalır.

---

## TIER 1 — CRITICAL (live mode'da gerçek para kaybı / silent corruption riski)

### C-API-1: `_resolve_quantity` negatif ve aşırı büyük sizing değerlerini kabul ediyor
- **Dosya:** `backend/showme/bots/runner.py:31-72` + `backend/showme/strategies/spec.py` (Position)
- **Repro:** `POST /api/strategies` body `{"position": {"sizing_kind": "fixed_quote", "sizing_value": -100}}` → 200 OK. Bind bot → enable → live tick → `qty = -1.0` → `broker.submit_order(quantity=-1.0, ...)` — yön ters çevrilmiş emir.
- **`risk_pct` özel durum:** `sizing_value=200` (yani "%200 risk") → 2× over-leverage. `_REFERENCE_EQUITY_USD = 10_000.0` hardcoded → kullanıcı `risk_pct=10` demek "hesabımın %10'u" sanır ama gerçekte `$1,000` fixed.
- **Etki:** Live mode'da ters yönlü veya devasa emir. Production hesaplarında kabul edilemez.

### C-API-2: Bollinger Bands template parametre adı drift — `std_dev` (template) vs `num_std` (compute)
- **Dosya:** `backend/showme/templates/catalog/templates.yml:138` ↔ `backend/showme/strategies/compute.py:75-91`
- **Repro:** Template `bb-squeeze-breakout` `params: {period: 20, std_dev: 2.0}` ile gelir. Compute engine `num_std` arar; `std_dev`'i sessizce yok sayar. Default `num_std=2.0` tesadüfen 2.0 ile eşleştiği için BUG görünmez ama kullanıcı `std_dev: 3.0` yapsa BBM 2σ bandı vermeye devam eder.
- **Etki:** Volatility template'leri kullanan tüm strategy'ler sessizce yanlış indicator değerleri kullanır.

### C-API-3: PUT `/api/bots/{id}` ile `signal_log` enjeksiyonu mümkün
- **Dosya:** `backend/showme/server_routes/bots.py:256-262`
- **Repro:** PUT body içine 200 fake `signal_log` entry koy → 200 OK, Pydantic cap 100'e indirir ama **100 forged entry persist eder**.
- **Etki:** PnL/equity-curve/leaderboard verisi tamponlanır. Auth token ele geçirilirse (`ps -E -p <pid>` exposed per [showMe S08]) tüm performans verisi forge edilebilir. Buggy UI optimistic update bile yapsa korupsyon mümkün.

### C-INT-1: Credential DELETE → bot orphan, live task zombieleşir
- **Dosya:** `backend/showme/server_routes/exchange.py:84-91`
- **Repro:** Live bot oluştur+enable → CONN'dan credential sil → 200. BotStore'da `credential_id` string kalır. Her tick `factory.get_broker(...)` → `KeyError` → `SignalEntry(action="skipped", error="broker unavailable")`. signal_log dolar, bot durdurulmaz, asyncio task çalışmaya devam eder.
- **`_INVALIDATION_HOOKS`** mekanizması var ama BotRunner.disable çağıran hook yok — sadece portfolio_aggregate kayıtlı.
- **Etki:** Kullanıcı CONN'dan credential silince live bot'larının ne olduğunu bilmez; UI hâlâ "enabled" gösterir.

### C-INT-2: Strategy DELETE referans kontrolü yok
- **Dosya:** `backend/showme/server_routes/strategies.py:123-132`
- **Repro:** Stratejiye bağlı bot var → DELETE → 200. Bot tick: `UnknownStrategy` → silent skip. PERF route lookup'ı `try/except UnknownStrategy: pass` ile yutar.
- **Etki:** Kullanıcı PERF'te bot adını/PnL'sini görür ama altındaki strateji yok. Win rate ölçüsü manasız.

### C-RUNTIME-1: Tick frequency `timeframe`'den decoupled — drift birikir + ccxt rate-limit patlatma riski
- **Dosya:** `backend/showme/bots/record.py:44` + `runner.py:217`
- **Repro:** `tick_interval_seconds=5` + `timeframe="1d"` → günde **17,280 tick** aynı bar üzerinde. 100 bot × 1d-TF × 5s tick → saniyede 20 ccxt çağrısı.
- **Daha ters senaryo:** 1m TF + 3600s tick → ara 60 bar atlanır (sadece son bar dikkate alındığı için).
- **Etki:** Ya rate-limit ban, ya signal kaybı.

### C-RUNTIME-2: `evaluate()` state-amnesia — her tick `flat`'tan başlar
- **Dosya:** `backend/showme/strategies/evaluate.py:113-160`
- **Repro:** Live bot, broker'da long açık. Bir sonraki tick `evaluate()` 200-bar pencerede `in_position=False`'tan koşulları yeniden değerlendirir. Pencere kaydıkça `crosses_*` koşullarının "ilk-kez" bilgisi değişir.
- **Etki:** Aynı pozisyon için ikinci `entry` emri gönderme riski; veya açık pozisyon için `exit` görüntülenmemesi. `compute_trades` kopyalanmış entry'leri FIFO eşlediği için PnL şişer.
- **Düzeltme:** `evaluate_last_bar(spec, df, in_position)` tek-bar state-aware evaluator.

### C-RUNTIME-3: Broker instance leak — her tick yeni `CcxtBroker(...)` instance
- **Dosya:** `backend/showme/brokers/factory.py:62-74` + `runner.py:254`
- **Repro:** Her tick `factory.get_broker(...)` yeni `ccxt.async_support.binance(...)` üretir. Her instance ayrı `aiohttp` connector. `_LIVE[target] = broker` üzerine yazar ama eski broker'ın `aclose()` çağrılmaz.
- **Etki:** 100 bot × 60s tick × 24h = **144,000 dangling aiohttp connector**. FD exhaustion riski. Sidecar uzun süre çalışınca network performansı düşer.

### C-RUNTIME-4: `_dispatch_live_order` exit-fallback partial fill + close_position eksikliği
- **Dosya:** `backend/showme/bots/runner.py:369-388`
- **Repro:** Broker `close_position` implementsiz adapter ise (Alpaca paper, custom) exit `strategy.sizing_value` ile karşı yön emri açar — gerçek pozisyon miktarı DEĞİL. Partial fill durumunda `Order.filled_quantity` kontrolü yok.
- **Etki:** Net exposure ters yönde açılabilir, real-money loss.

### C-RUNTIME-5: `start_all` concurrent invocation race
- **Dosya:** `backend/showme/bots/runner.py:123-152`
- **Repro:** `start_all` iki kez paralel çağrılırsa: `is_running` False döner, iki çağrı `_spawn` yapar, ikinci `_tasks[bid] = task` öncekini referans-dışı bırakır ama eski task cancel edilmez → aynı bot için 2 tick döngüsü.
- **Etki:** Live mode'da çift emir.

### C-UI-1: Strategy/Credential silindiğinde dropdown stale ID'yi sessizce tutuyor (orphan reference)
- **Dosya:** `ui/src/functions/BOT.tsx:166-200`
- **Repro:** Bot edit ekranı açık + STRA'dan stratejiyi sil → BOT'ta `draft.strategy_id` hâlâ silinen id. Native `<select>` bilinmeyen value için DOM hiçbir option seçmez (ilk option gibi görünür). `missingStrategy = !draft?.strategy_id` truthy → inline error ÇIKMAZ → Kaydet'e basılabilir.
- **Etki:** Sessiz veri bozulması; backend 4xx ile reddetse de UI'da kafa karışıklığı.

### C-UI-2: Symbol input whitespace + format validation yok
- **Dosya:** `ui/src/functions/BOT.tsx:210`
- **Repro:** `"  btc/usdt  "` yapıştır → state `"  BTC/USDT  "`. `"   "` whitespace-only kabul edilir (`missingSymbol = !draft?.symbol` truthy). `"BTC-USDT"`, `"BTCUSDT"`, `"BTC"` hepsi geçer.
- **Etki:** Backend 422 ile reddeder; UI'da cryptic "422 Unprocessable Entity" mesajı.

### C-UI-3: `tick_interval_seconds` clamp yok — `||` fallback ile silent reset
- **Dosya:** `ui/src/functions/BOT.tsx:228-231`
- **Repro:** `parseInt("0") || 60` → `60` (kullanıcı 0 girdiğini görür, state 60). `parseInt("") || 60` → `60`. `parseInt("-5") || 60` → `-5` (truthy negatif).
- **Etki:** Form input ile state arasında silent drift.

### C-UI-4: `originalMode` capture sadece `draft?.id` change'inde — re-capture stale
- **Dosya:** `ui/src/functions/BOT.tsx:84-101`
- **Repro:** Bot edit → shadow→live save → ekran kapatmadan tekrar live'a almaya çalış → `originalMode` hâlâ "shadow" (id değişmedi) → confirm dialog tekrar açılır.

### C-UI-5: Bot listesi polling yok — multi-client / BDA cross-create'te stale
- **Dosya:** `ui/src/functions/BOT.tsx:84-88`
- **Repro:** BDA pane'inden `Strateji öner + kaydet` ile yeni strategy yarat → BOT pane açıksa `loadStrategies()` `if (strategies.length === 0)` koşulu fail → yeni stratejiyi yüklemez. Aynı şekilde başka client'tan eklenen bot görünmez.

---

## TIER 2 — HIGH (silent data corruption / UX trap / yarış koşulu)

### API katmanı
- **H-API-1:** `/api/bots/{id}/enable` broker registry kontrolü yapmıyor → bot enabled görünür ama her tick `skipped` üretir.
- **H-API-2:** `_locks` map disable/delete sonrası temizlenmiyor — memory leak + stale `is_running`.
- **H-API-3:** Strategy file rename → ghost record on save (filesystem-FS mismatch).
- **H-API-4:** `/api/bots/feed?limit=-1` 200 empty, `/api/strategies/{id}/preview?limit=-1` 422 — tutarsız.
- **H-API-5:** `templates_instantiate` `symbol=["BTC","ETH"]` → `["['BTC', 'ETH']"]` (str repr in list).

### Runtime
- **H-RT-1:** `_dispatch_live_order` `IOC` time-in-force partial-fill korumasız → `order.filled_quantity` okumaz.
- **H-RT-2:** `disable()` task cancel BEFORE lock release → DELETE UX 5-30s asılı kalabilir.
- **H-RT-3:** `bots_feed` + `bots/performance` her bot için ayrı disk-IO N+1, no caching.
- **H-RT-4:** `evaluate` 200 bar ALL events üretip `events[-1]` alıyor — wasted CPU + last-bar fırsatları kaçırılıyor (`bar_index ≠ len(df)-1` filtresine takılır).
- **H-RT-5:** Credential trade-perm runtime'da revoke edilirse runner'a etki yok — silent skipped sinyal yağar (BUG #12'yi hızlandırır).
- **H-RT-6:** Bot vs Strategy timeframe drift (Bot 1m, Strategy 4h aynı endpoint kabul ediyor).

### Supervisor + PERF
- **H-SUP-1:** PERF "En kötü" KPI gizleniyor — `worst < 0` predicate'i tüm-pozitif portföylerde gösterilmiyor.
- **H-SUP-2:** BOTS "Sinyaller" sütunu feed-limit içindeki sayım, **per-bot gerçek sayı değil**. 5 bot × 100 sinyal, limit=50 → tabloda toplam 50 sayılıyor ortalama 10/bot.
- **H-SUP-3:** `compute_trades` `(exit-entry)*sizing/entry` formülü **tüm sizing_kind'lar için aynı** → `fixed_base` PnL **60000x off** (2 BTC pozisyon $4000 PnL → 0.0666 USD raporlanır).
- **H-SUP-4:** Enable + credential PATCH TOCTOU race.

### UI
- **H-UI-1:** Etkinleştir input `confirmLabel` state save sonrası temizlenmiyor → farklı credential için pre-filled hesap adı.
- **H-UI-2:** Enable/disable mid-flight guard yok → button spam → trade-permission API multi-call.
- **H-UI-3:** `<select value="30m">` UI listesinde yoksa Chrome ilk option'u (1m) gösterir → kullanıcı Save'e basınca `"1m"` persist.
- **H-UI-4:** STRA alias collision uyarısı yok — 2 RSI "rsi_1" alias → rule'lar belirsiz.
- **H-UI-5:** TMPL instantiate → modal kapanmıyor + strategy list refresh yok.
- **H-UI-6:** BDA `+ kaydet` cross-store invalidation hook yok — yeni strategy STRA/BOT'ta görünmez.
- **H-UI-7:** BDA `explainStrategy` ile `generate` aynı `loading` flag'i paylaşıyor — concurrent kullanım engelli.
- **H-UI-8:** STRA `r.right` literal: prefix unutulabilir, validation yok.
- **H-UI-9:** STRA Preview butonu `disabled={!draft.id || dirty}` — mesaj yok, "neden disable?" sorusu.
- **H-UI-10:** `+ Yeni bot` form'una başlayıp başka bota tıklarsa form silinir — dirty uyarısı yok.
- **H-UI-11:** Strategy edit + bot tıklama race (`openExisting` mid-flight başka bota geçiş → last-response-wins).

---

## TIER 3 — MEDIUM (UX bozukluğu / edge-case / tooling boşluğu)

### API + Runtime
- `validate_against_catalog` route layer'da var ama `evaluate()` runtime'da tekrar çağrılmıyor → manuel JSON tampering = silent NaN-bot.
- `compute_trades` `entry.price <= 0` skip ama matching exit pop edilmiyor → PnL pairing kayar.
- Template `recommended_timeframe` warning yok (15m AAPL vwap-pullback geçer).
- Whitespace-only symbol kabul ediliyor.
- OBV ilk-bar tutarsız başlangıç (0 vs volume[0]).
- RSI divide-by-zero `.replace(0, NaN)` → rule `rsi > 70` her zaman False.
- `equals_approximately` tolerance=NaN/Inf accepted.
- `signal_log` cap=100 → trade history kaybı, PERF deterministic değil.
- BotStore.save her save'de read+write disk round-trip (race window).

### UI
- BOT signal_log sadece son 20 entry, pagination yok.
- 2 farklı credential'da aynı sembol bot'lar listede ayırt edilemez (bot.id gizli).
- TMPL modal Escape/backdrop dismiss yok.
- BOT `Sil` butonu enable/disable mid-flight guard yok.
- BDA `result.notes` unordered.
- BOT `<input>` label binding tarz olarak görsel-only (htmlFor pattern yok).
- Strategy-store `remove` `loading` flag flip etmiyor (asimetri).
- Bot listesi 100+ entry için key prop'lar ve memo audit edilmemiş.

### Supervisor
- BOTS feed `signals_today` local TZ bucket vs tabloda UTC ISO `.slice(0,19)` → "5 bugünkü sinyal" derken hepsi düne ait görünür.
- PERF equity_curve `starting_equity=10_000` hardcoded — live bot için PORT pane'den farklı sayı.
- PERF tie-breaker `trade_count` desc + `round(total_pnl, 4)` → floating-point noise sıralamayı deterministic değil yapar.
- BOTS feed 10s polling + PERF 15s — yeni signal asimetrik görünüm.

---

## TIER 4 — LOW (cosmetic / future-proofing / dokümante limitasyon)

- Symbol newline/control char accepted (log injection).
- `_REFERENCE_EQUITY_USD = 10_000.0` magic number, API response'unda dokümante değil.
- Preview seed ilk 8 byte'tan türetiliyor (collision teorik).
- Template `_CATALOG` module-level cache invalidation yok.
- `compute_trades` short-only-not-implemented (dokümante limit).
- Transaction cost / slippage hesabı yok.
- `signal_log` cap=100, **`closed_trades_log`** ayrı tutulmuyor.
- `bots_feed` `bar_time` (pandas-repr boşluk) vs `timestamp` (ISO T) → string sort drift.
- `<input>` `min={5} max={3600}` sadece browser hint.
- Multi-currency (EUR/GBP/TRY) `_STABLE_TO_USD` listesinde yok → portfolio underreport.
- BOT pane `+ Yeni bot` sticky değil → 50+ bot'ta scroll-out.
- Error message rendering `String(e)` → Pydantic detail kaybolur.
- STRA Position editor UI'da yok (sizing_kind/value/stop_loss/take_profit) — backend default ile gider.
- STRA `Rule.tolerance` field UI'da yok → `equals_approximately` kullanılamaz.
- STRA alias rename → rule.left/right referansları cascade update etmiyor.
- BDA spec JSON edit yok (readonly).
- TMPL Oluştur sonrası modal açık kalır (H-UI-5 bağlı).
- `<StatusPill rec={draft as BotRecord}>` type cast risk.

---

## SİSTEMİK TEMALAR (4 audit'in birden tespit ettiği)

### Tema 1 — "Cascade delete" mimari boşluğu
- Credential delete → bot orphan (CONN tarafı `_INVALIDATION_HOOKS` çağırıyor ama BotRunner hook'u yok)
- Strategy delete → bot ölü-strateji ile (route layer FK check yok)
- Bot delete → `_locks` ve `_LIVE` map'lerinde leak
- **Önerilen çözüm:** Tek bir `_RESOURCE_INVALIDATION_REGISTRY` + her sub-system kendi cascade hook'unu register etmeli. Veya delete endpoint'leri `?force=true` query parametresi alıp bağımlıları sayıp 409 dönmeli.

### Tema 2 — Sizing math iki yerde duplicate
- `runner._resolve_quantity` (runner.py:31-72) → tüm sizing_kind'ları handle ediyor
- `performance.compute_trades` (performance.py:54-66) → sadece `fixed_quote` formülü kullanıyor
- **Önerilen çözüm:** Tek bir `sizing.py` modülü, hem runner hem performance import etsin.

### Tema 3 — `evaluate()` stateless yapısı
- Lookahead-free olması iyi, ama bot'un gerçek pozisyon durumunu bilmemesi rolling window'da bug üretir.
- Her tick 200 bar'ın tamamını re-evaluate etmek hem CPU israfı hem doğruluk problemi.
- **Önerilen çözüm:** `evaluate_last_bar(spec, df, *, in_position)` tek-bar state-aware API; mevcut `evaluate()`'ı backtesting için sakla.

### Tema 4 — Signal log cap'ten kaynaklı veri kaybı
- 100-entry FIFO trade pairing'i kaydırır
- PERF metrics geri-dönüşsüz yanlışlanır
- **Önerilen çözüm:** `closed_trades_log` ayrı persistence (FIFO değil, append-only); `signal_log` debug için 100 cap kalabilir.

### Tema 5 — Cross-pane / cross-store senkronizasyon yok
- BDA + TMPL strategy yaratır ama BOT/STRA dropdown'ları invalidate etmez
- BOTS feed polling 10s, PERF polling 15s — race
- Bot enable durumu UI'da `enabled` flag, runtime task health UI'da yok
- **Önerilen çözüm:** StreamHub'a `bot.signal`, `strategy.created`, `credential.changed` channel'ları ekle; UI store'lar SSE üzerinden invalidate etsin.

### Tema 6 — Validation katmanları tutarsız
- API'da Pydantic var ama `min_length=1` whitespace-only kabul ediyor
- UI'da `missingSymbol` `truthy` kontrolü whitespace-only'i kabul
- Sembol formatı (`BASE/QUOTE`) hiç check edilmiyor
- Tick interval `||` fallback ile silent drift
- **Önerilen çözüm:** Tek bir `validators.ts` (UI) + `validators.py` (backend); paylaşılan regex katalog.

---

## TEST KAPSAMA ANALİZİ

**Mevcut:** 88 + 38 + 64 + 75 + 43 ≈ **300+ test, tümü green**.

**Bu audit'in bulduğu bug'lardan kaçı testle yakalanmıyor:** **89/89** (yani %100).

Bunun nedeni: mevcut testler "happy path" + Pydantic shape + birkaç koruma testi. Şu kategorilerde **sıfır kapsama**:
- Cascade delete davranışı (credential→bot, strategy→bot)
- Concurrent invocation race'leri (`start_all`, `enable`/`disable`)
- Long-running bot signal_log overflow + PnL pairing drift
- Sizing math switch (`fixed_base`, `risk_pct`)
- Mode değişimi sequencing (shadow→live→shadow→live)
- Cross-store sync (BDA→STRA→BOT)
- Form value silent coercion (`<select>` unknown enum, `parseInt("") || 60`)
- Time zone tutarlılığı (KPI bucket vs display)
- Broker instance lifecycle (per-tick leak)
- `evaluate()` rolling window over-firing

---

## ÖNERİLEN MÜDAHALE SIRASI

### Faz 1 — Live mode safety (bu hafta)
1. **C-API-1:** Sizing validation + risk_pct gerçek equity'ye bağla
2. **H-SUP-3:** `compute_trades` sizing_kind switch ekle (performance.py)
3. **C-INT-1 + C-INT-2:** Cascade delete (credential + strategy → bot disable)
4. **C-RUNTIME-4 + H-RT-1:** `close_position` zorunlu, partial fill kontrolü
5. **C-RUNTIME-5:** `start_all` race lock

### Faz 2 — Runtime sağlık (bu ay)
6. **C-RUNTIME-2 + H-RT-4:** `evaluate_last_bar` state-aware tek-bar evaluator
7. **C-RUNTIME-3:** Broker instance cache + `aclose()` lifecycle
8. **C-RUNTIME-1:** `tick_interval_seconds`'ı timeframe'den türet
9. **C-API-3:** PUT body sanitize (`signal_log`, `last_processed_event` drop)
10. **Signal log split:** `closed_trades_log` ayrı persistence

### Faz 3 — UI parite (önümüzdeki sprint)
11. **C-UI-1 + C-UI-2 + C-UI-3:** Validation katmanı (regex, trim, clamp)
12. **C-UI-5 + H-UI-6:** Cross-store invalidation hook
13. **H-UI-5:** TMPL instantiate modal close + refresh
14. **H-UI-2:** Enable/disable loading guard
15. **H-UI-11:** `openExisting` AbortController

### Faz 4 — Observability (gerektikçe)
16. **H-SUP-1 + H-SUP-2:** PERF best/worst semantik + per-bot signal_count
17. **H-RT-3:** Bot store cache + invalidation
18. **Theme 5:** StreamHub'a bot channel'ları
19. **C-API-2:** Template param contract drift fix
20. **MEDIUM batch:** Tier 3 toplu temizlik

---

## SIDECAR DURUMU (testler sırasında)

- Tüm test'ler şu komutla çalışmış:
  - `cd backend && python -m pytest tests/test_bots*.py tests/test_strategies*.py tests/test_templates*.py tests/test_evaluate*.py tests/test_compute*.py tests/test_performance*.py tests/test_portfolio_aggregate*.py -v`
  - `cd ui && npm run test -- --run BOT BDA STRA TMPL BOTS PERF CONN PORT INDX`
- Sonuç: TÜMÜ GREEN. Audit-only, hiçbir kod değişmedi.

---

## SONUÇ

**Bot sistemi**, mevcut test gridiyle "Çalışıyor görünüyor" sinyali veriyor ama **89 bug'dan hiçbiri test'lerle yakalanmıyor**. Tüm bug'lar manuel inceleme + cross-domain pattern recognition ile bulundu. Sistemin güçlü tarafları (FK validation, auth, atomic file writes, S4-S8 hardening) belli alanlarda iyi; ama **cascade delete, sizing math tutarlılığı, evaluate state machine, signal_log persistence ve cross-pane sync** mimari seviyede yeniden ele alınmalı.

Üretim öncesi en az **Faz 1 (5 bug)** kapatılmadan live mode'u kullanıcılara açmayı önermiyorum — özellikle C-API-1 (negative sizing) ve H-SUP-3 (PnL math) gerçek para etkisi olan bug'lar.

---

**Audit metodu:** 4 paralel `general-purpose` agent, her biri ~12-15 dakika boyunca kod okudu + pytest/vitest çalıştırdı + kenar durum aradı. Toplam 4 ayrı bakış açısının örtüştüğü temalar yukarıdaki "Sistemik Temalar" bölümünde.

