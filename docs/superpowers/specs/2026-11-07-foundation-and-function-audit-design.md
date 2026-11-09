# Temel Onarım + 141 Fonksiyon Doğruluk Denetimi — tasarım

Tarih: 2026-11-07 · Dal: `fix/foundation-audit` (`codex/vcap-investments` ucundan)
Kapsam: Alt proje A (Temel) + B (Canlı denetim). C/D/E/F ayrı spec'lerle gelir.
Karar: Hibrit denetim — otomatik doğruluk kapısı (B1) + ajan derin incelemesi
ve çürütücü doğrulama (B2).
Platform: **yalnızca Windows** (macOS dosyaları silinmez, bakımı yapılmaz).
Veri politikası: **ücretsiz, anahtar opsiyonel** — her fonksiyon anahtarsız
ücretsiz kaynakla gerçek veri vermeli; ücretsiz anahtar (FRED vb.) girilirse
daha iyi kaynağa geçer; anahtar yoksa açıkça söyler, asla sahte veri göstermez.

## 0. Bağlam ve hedef

showMe'nin hedefi Bloomberg Terminal kalitesinde, 141 fonksiyonlu bir masaüstü
terminal. Bugünkü durum:

- Temiz bir Windows kurulumunda backend paketi toplanamıyor: `binance` modülü
  `showme/engine/api/binance_client.py` içinde koşulsuz import ediliyor ama
  `backend/pyproject.toml`'da yok. Sonuç: `engine.data.market_data`,
  `engine.trading.execution_engine`, `engine.services.bot_service` ve 4 test
  modülü import hatası veriyor. `pytest.mark.timeout` kullanılıyor ama
  `pytest-timeout` dev bağımlılığında yok.
- `package.json` e2e script'leri POSIX ortam değişkeni sözdizimi
  (`PLAYWRIGHT_E2E_MODE=smoke npx ...`) kullanıyor — Windows'ta çalışmaz.
- Sidecar, port meşgulken ham Winsock 10048 hatasıyla çıkıyor.
- 2026-05-03 manuel denetimi (`docs/showme_manual_function_audit_2026-05-03.md`):
  fonksiyonların çoğu `DEGRADED`; yardım metinleri şablon; sabit örnek değerler
  (PSC hesap 10,000 / entry 100, REBA örnek emirleri, GREEKS strike 105 spot 100);
  girdi kontrolleri eksik (YAS tahvil, BMTX strateji/evren); varlık uyumsuzluğu
  (YAS varsayılanı hisse, TSOX'ta US10Y `EQUITY`); TECH "No price data".
- Mevcut `scripts/showme_function_audit.py` `provider_unavailable`/`empty`'yi
  WARN saydığı için bu tabloyu "geçti" olarak raporlayabiliyor.

Bu spec'in hedefi: (A) ortam gürültüsünü sıfırlamak, (B) 141 fonksiyonun
gerçek durumunu ölçen, tekrarlanabilir bir kapı ve öncelikli bir hata listesi
üretmek. **A dışındaki hiçbir fonksiyon davranışı bu aşamada değişmez.**

## 1. A — Temel

1. **Bağımlılık bütünlüğü.**
   - `binance_client.py`: `binance` import'u lazy/opsiyonel. Paket yoksa modül
     yine import edilir; `BinanceClient` kurulumu açık bir
     `provider_unavailable` sebebiyle başarısız olur. `market_data`,
     `execution_engine`, `bot_service` paketsiz import edilebilir.
   - Kodun import ettiği ama `pyproject.toml`'da olmayan tüm üçüncü taraf
     paketler taranır (AST tabanlı import taraması vs. kurulu dağıtımlar).
     Her biri ya `dependencies`'e eklenir ya da aynı lazy desenle opsiyonel
     yapılır. Karar ölçütü: paketsiz bir fonksiyonun anahtarsız yolu hâlâ
     çalışıyorsa opsiyonel; çekirdek yol ise zorunlu.
   - `pytest-timeout` → `dev` grubuna.
2. **Backend testleri yeşil.** Windows'ta `npm run test:backend` 0 hata.
   Yalnızca gerçekten platforma özgü testler (POSIX `resource`, sembolik link,
   `/Applications` yolu vb.) gerekçeli `skipif(sys.platform == "win32")` alır;
   diğer her hata kökünden düzeltilir. Atlanan her test
   `docs/audit/windows-skips.md`'ye gerekçesiyle yazılır; bilinçli opsiyonel
   bırakılan paketler `docs/audit/optional-deps.md`'ye.
3. **UI.** `npm --workspace ui run test`, `tsc --noEmit`, `npm run lint` temiz.
4. **Sidecar.** `--port 0` ile açılış; `/api/health` `ok: true` ve
   `/api/function-index` ≥141 kayıt. Port meşgulse tek satırlık anlaşılır
   hata (`port 8765 kullanımda (PID n) — --port 0 deneyin`) ve sıfırdan farklı
   çıkış kodu.
5. **e2e smoke.** `test:e2e:smoke*` script'leri `cross-env` ile Windows'ta
   çalışır; smoke projesi Windows'ta geçer.

**Bitti tanımı:** Windows'ta `npm run test:backend`, `npm --workspace ui run test`,
UI typecheck ve `npm run test:e2e:smoke` yeşil; sidecar açılış kontrolü geçer.
Her düzeltme ayrı commit.

## 2. B1 — Otomatik doğruluk kapısı

Mevcut `scripts/showme_function_audit.py`'ye geriye uyumlu bir `--strict`
modu eklenir. Varsayılan davranış değişmez.

### 2.1 Kontroller

| # | Kontrol | Kural | Çevrimdışı? |
|---|---|---|---|
| T1 | Sözleşme | Mevcut: geçerli durum, sebep, `nextAction`, yasaklı ifadeler | hayır |
| T2 | Kaynak | `ok` yanıtında ≥1 gerçek kaynak + as-of zaman damgası; `NONE`, `PAPER_TICKET` ve benzeri uydurma kaynaklar geçersiz; veri yaşı beklenen güncelleme sıklığının (fonksiyon başına tablo: intraday/günlük/haftalık/aylık/çeyreklik) 3 katını aşmaz | hayır |
| T3 | Girdi duyarlılığı | Fonksiyon iki farklı birincil girdiyle (ör. AAPL/MSFT, US/DE, EURUSD/USDJPY) çalıştırılır; sayısal yük (satır/seri/kart sayıları dahil, gürültü toleransı 1e-9) birebir aynıysa `suspect_static` | hayır |
| T4 | Örnek değer izi | Yanıtta ve fonksiyon modülünde (AST: çıktıya akan sayısal literal'ler) bilinen örnek değerler: hesap 10000, entry 100, strike 105 / spot 100, quantity 0, hisse istenmişken BTC/ETH/SOL varsayılan evreni, `smoke-1` id'leri. Örnek değer ve izin listeleri (gerçek sabitler: 252 işlem günü, 365, bps=1e-4 …) `contracts/truth_audit.json`'dadır | **evet** (AST) + hayır (yanıt) |
| T5 | Varlık uyumu | Katalogdaki `asset_classes` ile fonksiyonun varsayılan girdisinin sınıfı uyumlu; yanıttaki varlık sınıfı istenenle aynı | **evet** (katalog) + hayır (yanıt) |
| T6 | Yardım metni | Şablon kalıplar yasak ("Run the function", "inspect/rerun", "N position(s) function" …); metin en az bir girdi adı ve yöntem/kaynak anahtar kelimesi içerir; pane'in kapsam etiketi katalogdaki `scope` ile aynı | **evet** |
| T7 | Sayısal tutarlılık | NaN/±inf yok; volatilite ≥0; ağırlık toplamı 1±1e-6 (ağırlık dönen fonksiyonlarda); olasılıklar [0,1]; getiriler makul aralıkta (günlük |r|<1); tarihler gelecekte değil (takvim fonksiyonları hariç) | hayır |
| T8 | Gecikme | Soğuk p95 ≤ 12 s, sıcak p95 ≤ 3 s (fonksiyon başına override tablosu: BRIEF, SPLC, ICX vb.); zaman aşımı = KIRMIZI | hayır |

### 2.2 Notlama

- **YEŞİL**: `ok` + T1–T8 geçer.
- **SARI**: (a) anahtar isteyen daha iyi kaynak tanımlı değil ama anahtarsız
  yolla gerçek veri geliyor, ya da (b) `provider_unavailable`/`empty` dürüstçe
  raporlanıyor **ve** bu fonksiyon için bilinen anahtarsız alternatif yok.
  "Bilinen alternatif" kaydı: `contracts/keyless_alternatives.json`
  (`{code: [{provider, url, covers}]}`). İlk turda boş başlar; B2 ve C
  doldurdukça ilgili `provider_unavailable` fonksiyonları SARI'dan KIRMIZI'ya
  döner.
- **KIRMIZI**: T1–T8'den herhangi biri başarısız; `calc_error`/`input_error`;
  zaman aşımı; anahtarsız alternatifi bilinen bir fonksiyonda
  `provider_unavailable`.
- **network_flake**: istek düzeyinde ağ hatası tek tekrarla da sürerse; KIRMIZI
  sayılmaz, ayrı sütunda raporlanır.

### 2.3 Çıktılar ve kalıcı kapı

- `artifacts/showme-truth-audit/<UTC zaman>/`: `ledger.json`, `summary.md`,
  fonksiyon başına `request.json` / `response.json`. (`artifacts/` gitignore'da
  kalır; özet `docs/audit/`'e kopyalanır.)
- **Çevrimdışı kapı** — `backend/tests/test_function_truth_gate.py`: T4 (AST),
  T5 (katalog), T6 (yardım metni) normal pytest paketinde koşar. Taban çizgisi
  `tests/_truth_baseline.json`: fonksiyon başına KIRMIZI kontrol listesi.
  Yeni bir KIRMIZI ya da baseline'da olmayan fonksiyonda KIRMIZI → test FAIL.
  Azalma serbest; baseline `--update-baseline` ile yalnızca aşağı çekilir.
- **Canlı kapı** — aynı dosyada `@pytest.mark.live` (T2/T3/T7/T8);
  varsayılan paket dışında, `pytest -m live` ile.
- **B1'in kendi testleri** — `backend/tests/test_truth_audit_checks.py`: her
  T-kontrolü için sabit sahte yanıt fixture'larıyla en az bir doğru-pozitif ve
  bir doğru-negatif.

## 3. B2 — Ajan derin incelemesi + çürütücü doğrulama

### 3.1 Birimler

14 kategori ~16 inceleme birimine bölünür (portföy ~26 fonksiyon → 3 parça;
haber/istihbarat → 2 parça; diğerleri tek). Birim listesi B1'in canlı
kataloğundan üretilir.

### 3.2 İnceleyici görevi (fonksiyon başına)

1. Fonksiyonu, veri adaptörlerini ve UI pane'ini okur.
2. Referans metodolojiyi belirler (Bloomberg karşılığı ne yapar; kanonik
   formül — ör. PFA Brinson-Fachler, RPAR Maillard/Spinu ERC, OVME
   Black-Scholes-Merton, PVAR parametrik VaR/ES). Gerekirse web araştırması;
   kaynak URL'si zorunlu.
3. Sidecar'da gerçekçi girdilerle çalıştırır; en az bir sayıyı aynı ham
   veriden bağımsız (numpy) hesaplayıp karşılaştırır.
4. Pane'de parametrelerin girdi olarak açılıp açılmadığını ve yardım metnini
   kontrol eder.
5. Veri zayıf/yoksa ücretsiz, anahtarsız alternatif kaynak araştırır.

Bulgu şeması: `code`, `severity` (P0 bozuk/sahte · P1 yanlış hesap · P2 eksik
girdi/özellik · P3 yardım/UX), `evidence` (`file:line` + istek/yanıt özeti),
`reference_url`, `proposed_fix`, `keyless_source`.

### 3.3 Doğrulama

- Her P0/P1 → bir çürütücü ajan; görevi bulguyu çürütmek, emin değilse
  "çürütüldü" der.
- İnceleyici ile çürütücü çelişirse → hakem (Opus) karar verir.
- P2/P3 → tek inceleyici; yalnızca tekrarlar elenir.
- Her birimin sonunda **eksiklik denetçisi**: "neyi kontrol etmedik?" — çıkan
  boşluklar o birim için yeni tur.

### 3.4 Model ve ölçek

- İnceleyici, çürütücü, eksiklik denetçisi: **Haiku 5.5** (`model: "haiku"`).
  Hiçbir aşamada Sonnet yok (global CLAUDE.md kuralı). Opus yalnızca çelişen
  P0/P1 hakemliğinde.
- Toplam ~40–60 ajan; oturumun workflow başına ~10 ajan yönergesine uymak için
  birimler 5–6 workflow'a bölünür. Her workflow sonucu okunup liste
  güncellendikten sonra sıradaki başlatılır.
- Sonuç dönmeyen ajan → fonksiyon "incelenmedi" olarak listede görünür
  (sessiz kesinti yok).

## 4. Birleşik hata listesi

`docs/audit/function-ledger.json` + `docs/audit/function-ledger.md`.

- Her fonksiyon için: B1 notu + kontrol sonuçları, B2 bulguları (doğrulanmış),
  önerilen anahtarsız kaynak, tahmini onarım büyüklüğü (S/M/L).
- Sıralama: önce P0 ve KIRMIZI, sonra **çekirdeklik** (günlük kullanılan
  çekirdek set ilk: GP, HP, FA, DES, TOP, CN, WATCH, ECO, PORT, OMON, CRVF,
  WIRP, MAP), sonra P1 → P3.
- Kategori başına "D için önerilen sıra" bölümü. D'nin her kategorisi bu
  listeden kendi kısa spec'ini alır.

## 5. Sıralama

1. ✅ MEET yarım işi `codex/vcap-investments`'a ayrı commit (`1f0524c`, 2 kırık
   test belgeli); `fix/foundation-audit` bu uçtan açıldı.
2. A — her düzeltme ayrı commit; dört komut yeşil olunca B'ye geçilir.
3. B1 — kapı + B1 testleri + canlı tarama; ilk liste ve baseline commit.
4. B2 — birim grupları sırayla workflow; her workflow sonrası liste güncellenir.
5. Birleşik liste → kullanıcıyla D'nin ilk kategorisi seçilir.

## 6. Hata yönetimi

- İstek başına zaman aşımı (T8 bütçesinin 2 katı, üst sınır 30 s).
- Sidecar çökerse tarama aracı onu `--port 0` ile yeniden başlatır ve kaldığı
  fonksiyondan devam eder (ilerleme `ledger.partial.json`'a yazılır).
- Ağ hatası tek tekrar → sürerse `network_flake`.
- Ajan `null` → "incelenmedi".

## 7. Test

- A: bölüm 1'deki dört komut + sidecar açılış kontrolü.
- B1: `test_truth_audit_checks.py` (kontrol başına doğru-pozitif/negatif) +
  `test_function_truth_gate.py` (baseline ratchet).
- B2: bulgular kod değil; doğruluğu çürütücü/hakem katmanı ve kanıt alanıyla
  güvenceye alınır.

## 8. Kapsam dışı

D (fonksiyon onarımı), C (veri kaynağı katmanı yeniden yapımı), E (arayüz
cilası), F (sürüm/paketleme). MEET'in 2 kırık testi bu spec'in değil, MEET
işinin konusudur; A'nın "backend yeşil" ölçütünü bloklarsa ayrı karar için
kullanıcıya sorulur.
