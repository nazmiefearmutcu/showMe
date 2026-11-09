# Temel Onarım + Fonksiyon Doğruluk Denetimi — Uygulama Planı

> Ajan çalışanlar için: görevleri sırayla uygula; her görevin sonunda diff'i bağımsız bir
> inceleyici (Haiku 5.5, asla Sonnet) gözden geçirir, önemli bulgular düzeltilip ilgili
> kontroller yeniden koşulur. Son görevde tüm değişikliğe bütünsel bağımsız inceleme yapılır.

**Hedef:** Windows'ta ortam gürültüsünü sıfırlamak (A) ve 141 fonksiyonun gerçek durumunu ölçen
tekrarlanabilir bir kapı + öncelikli, doğrulanmış bir hata listesi üretmek (B).
**Mimari:** A — mevcut kodda nokta düzeltmeler (lazy import, bağımlılık bildirimi, test/platform
düzeltmeleri, sidecar port hatası, `cross-env`). B1 — saf kontrol fonksiyonları
`backend/showme/audit/truth.py`'de; veri tabloları `contracts/truth_audit.json`'da;
orkestrasyon mevcut `scripts/showme_function_audit.py`'nin `--strict` modunda; çevrimdışı kapı
pytest'te. B2 — Workflow ile kategori birimleri üzerinde Haiku-önce inceleme + çürütme + hakem.
**Teknoloji:** Python 3.11+ (venv'de 3.13), pytest, FastAPI sidecar; React/Vite, vitest, tsc,
eslint, Playwright; uv.
**Spec:** docs/superpowers/specs/2026-11-07-foundation-and-function-audit-design.md

## Genel kısıtlar
- Yalnızca Windows hedef; macOS dosyaları silinmez.
- **Port 8765'e dokunma** — kullanıcının çalışan gateway'i (PID 3356) orada. Sidecar her zaman
  `--port 0` (veya boş bir port) ile.
- Python komutları: `backend/.venv/Scripts/python.exe -m pytest -o addopts='' ...`
  (varsayılan `addopts` coverage ekler, yavaşlatır).
- Uzun komutlar (tam backend paketi, e2e, canlı tarama) arka planda çalışır.
- `1f0524c` (MEET WIP) commit'i yeniden yazılmaz; MEET'in 2 kırık testi için karar kullanıcıya
  sorulur (Görev 2).
- A dışında fonksiyon davranışı değişmez. B yalnızca ölçer ve raporlar.
- Varsayılan test paketinde ağ erişimi yok; canlı kontroller `-m live`.
- Yeni çalışma zamanı bağımlılığı yalnızca Görev 1'deki gerekçeli liste; başka ekleme yok.
- Her kök neden ayrı commit; commit mesajları Co-Authored-By satırıyla biter. Push yok.
- Alt ajanlar: önce Haiku 5.5 (`model: "haiku"`), Sonnet asla; Opus yalnızca çelişen P0/P1
  hakemliği.

## İnceleme odağı
1. Lazy/opsiyonel import'lar bir hatayı sessizce yutmamalı: paket yoksa sebep açık
   `provider_unavailable` olarak yüzeye çıkmalı.
2. `skipif(win32)` yalnızca gerçekten platforma özgü testlere; her biri gerekçeli ve listelenmiş.
3. Truth kontrolleri hem doğru-pozitif hem doğru-negatif testli; izin listeleri gerçek sabitleri
   (252, 365, 1e-4 …) yanlışlıkla KIRMIZI yapmamalı.
4. Ratchet yalnızca aşağı yönlü; baseline'ı yukarı çekmenin yolu olmamalı.
5. B2 bulguları kanıtsız (file:line + istek/yanıt) listeye giremez; P0/P1'ler çürütücüden geçmiş
   olmalı.

---

## Görev 1 (A1): Bağımlılık bütünlüğü
Dosyalar: `backend/showme/engine/api/binance_client.py`, `backend/pyproject.toml`,
`backend/uv.lock`, yeni `backend/tests/test_optional_imports.py`.

Ön tarama sonucu (2026-11-07, venv'de bulunmayan import'lar): tek koşulsuz üst-düzey import
`binance` (`binance_client.py:10-11`). Diğerleri try-korumalı veya fonksiyon içi:
`scipy` (port.py, pvar.py — `norm` için), `exchange_calendars` (calendar_registry),
`openpyxl` (damodaran_adapter — fonksiyon içi, **korumasız**), `sklearn`/`lightgbm`/`xgboost`
(ml_signals), `plotly`, `nltk`, `fido2`, `openai`, `anthropic`, `meilisearch`, `onnxruntime`,
`whisper`/`faster_whisper`, `alpaca`, `ib_insync`, `veryfinder`.

- [ ] Başarısız test yaz: `sys.modules["binance"] = None` ile `engine.api.binance_client`,
      `engine.data.market_data`, `engine.trading.execution_engine`,
      `engine.services.bot_service` import edilebilmeli; `BinanceClient(...)` kurulumu sebebi
      "python-binance not installed" içeren tipli bir hata vermeli.
- [ ] Testi koş, başarısızlığı gör.
- [ ] `binance` import'unu lazy yap (modül düzeyinde `None` sentinel + kurulumda kontrol);
      `BinanceAPIException`/`BinanceRequestException` kullanan `except` blokları paket yokken de
      geçerli kalmalı (yerel yedek istisna sınıfları).
- [ ] Bağımlılık kararları — her biri için çağrı noktasının anahtarsız çekirdek yolda olup
      olmadığını doğrula, sonra:
      - `dependencies`'e ekle (aday): `scipy`, `openpyxl`, `exchange-calendars`, `scikit-learn`
        — yalnızca anahtarsız bir fonksiyon yolu bunlara ihtiyaç duyuyorsa; ihtiyaç yoksa
        opsiyonel bırak ve gerekçeyi yaz.
      - Opsiyonel kalır: `python-binance`, `openai`, `anthropic`, `veryfinder`, `plotly`,
        `lightgbm`, `xgboost`, `meilisearch`, `onnxruntime`, `nltk`, `openai-whisper`,
        `faster-whisper`, `fido2`, `alpaca-py`, `ib_insync` (anahtar/broker/ağır model).
      - `damodaran_adapter` içindeki korumasız `openpyxl` import'u: paket opsiyonel kalırsa
        açık `provider_unavailable` sebebine çevir.
      - `dev` grubuna `pytest-timeout`.
- [ ] `uv lock` + `uv sync --extra dev`; Windows/Python 3.13 wheel'leri kuruldu mu doğrula.
- [ ] Import taramasını tekrar koş; kalan eksikler yalnızca bilinçli opsiyonel liste olmalı.
      Listeyi gerekçeleriyle `docs/audit/optional-deps.md`'ye yaz.
- [ ] Hedefli testler + `ruff check` sahip olunan dosyalarda; commit.

## Görev 2 (A2): Backend paketi Windows'ta yeşil
Dosyalar: başarısız testlere göre belirlenir; yeni `docs/audit/windows-skips.md`.

- [ ] Tam paketi arka planda koş:
      `pytest -q -o addopts='' --continue-on-collection-errors -p no:cacheprovider`
      → başarısızlık listesini dosyaya yaz.
- [ ] Her başarısızlığı kök nedene göre grupla: (a) gerçek hata → kökten düzelt,
      (b) gerçekten platforma özgü (POSIX `resource`, symlink, `/Applications`, `fork` …) →
      gerekçeli `skipif(sys.platform == "win32")`, (c) ağa bağımlı test varsayılan pakette →
      `live` işaretine taşı.
- [ ] **MEET kararı:** `test_meet_country_gates.py`'deki 2 kırık test için kullanıcıya sor
      (bu görevde düzelt / MEET işine bırak ve geçici `xfail(strict=True)` ile belgele).
      Cevap gelmeden MEET dosyalarına dokunma.
- [ ] Her kök neden için: başarısız testi gör → düzelt → hedefli test → commit.
- [ ] `docs/audit/windows-skips.md`: her skip, dosya:test, gerekçe.
- [ ] Bitti: tam paket 0 fail, 0 collection error.

## Görev 3 (A3): UI test, typecheck, lint
Dosyalar: başarısızlıklara göre `ui/src/**`.

- [ ] `npm --workspace ui run test`, `npm --workspace ui run typecheck`,
      `npm --workspace ui run lint` koş; çıktıları kaydet.
- [ ] Her başarısızlığı kök nedenden düzelt (davranış değiştiren düzeltme gerekiyorsa önce test).
      Lint uyarılarını kural kapatarak değil kodu düzelterek gider.
- [ ] Üçü de temiz; commit(ler).

## Görev 4 (A4): Sidecar açılış ve port hatası
Dosyalar: `backend/showme/server.py`, yeni `backend/tests/test_server_port_in_use.py`,
yeni `scripts/sidecar_smoke.py`.

- [ ] Başarısız test yaz: bir soketi rastgele porta bağla, `showme.server`'ı o portla
      alt süreç olarak başlat → sıfırdan farklı çıkış kodu ve stderr'de portu, (bulunabiliyorsa)
      PID'i ve `--port 0` önerisini içeren tek satır; ham Winsock metni yerine.
- [ ] Uygula: uvicorn başlamadan önce bind ön kontrolü (Windows'ta `SO_EXCLUSIVEADDRUSE`),
      PID'i `psutil` yoksa `netstat -ano` ile en iyi çabayla bul.
- [ ] `scripts/sidecar_smoke.py`: `--port 0` ile başlat, `SIDECAR_PORT=` satırını oku,
      `/api/health` `ok: true` ve `/api/function-index` ≥141 kayıt doğrula, kapat; B1 bu yardımcıyı
      yeniden kullanır.
- [ ] Testler + smoke script yeşil; commit.

## Görev 5 (A5): e2e smoke Windows'ta
Dosyalar: kök `package.json`, `package-lock.json`, gerekirse `tests/e2e/**`.

- [ ] `cross-env`'i kök devDependency olarak ekle; `PLAYWRIGHT_E2E_MODE=…`/`SHOWME_E2E_SKIP_BUILD=…`
      kullanan script'leri `cross-env` ile yeniden yaz.
- [ ] Playwright tarayıcıları kurulu mu kontrol et; değilse kullanıcıya indirme boyutunu söyleyip
      onay al (`npx playwright install chromium`).
- [ ] `npm run test:e2e:smoke` arka planda koş; başarısızlıkları kök nedenden düzelt.
- [ ] Commit.

### Kontrol noktası A
Dört komut (`npm run test:backend`, `npm --workspace ui run test`, UI typecheck,
`npm run test:e2e:smoke`) + `scripts/sidecar_smoke.py` yeşil. Kullanıcıya kısa rapor; B'ye geç.

---

## Görev 6 (B1a): Saf truth kontrolleri + testleri
Dosyalar: yeni `backend/showme/audit/__init__.py`, `backend/showme/audit/truth.py`,
yeni `contracts/truth_audit.json`, yeni `contracts/keyless_alternatives.json` (`{}`),
yeni `backend/tests/test_truth_audit_checks.py`, `backend/tests/fixtures/truth/*.json`.

- [ ] `contracts/truth_audit.json` şeması: `cadence` (kod → intraday/daily/weekly/monthly/quarterly),
      `latency_overrides` (kod → {cold_s, warm_s}), `placeholder_values` (değer listesi + bağlam),
      `literal_allowlist` (252, 365, 360, 1e-4, 100 yüzde dönüşümü bağlamında …),
      `template_help_patterns` (regex listesi), `input_pairs` (varlık sınıfı → iki girdi).
- [ ] Her T-kontrolü için önce fixture + test (en az bir doğru-pozitif, bir doğru-negatif):
      T1 sözleşme, T2 kaynak/tazelik, T3 iki yanıt eşitliği, T4 yanıt izi + AST literal taraması,
      T5 katalog/yanıt varlık uyumu, T6 yardım metni + kapsam etiketi, T7 sayısal tutarlılık,
      T8 gecikme.
- [ ] Testleri koş, başarısızlığı gör; `truth.py`'de her kontrolü saf fonksiyon olarak uygula
      (`check_tN(...) -> list[Finding]`), notlayıcı `grade(findings, status, keyless_known)`
      → GREEN/AMBER/RED/NETWORK_FLAKE.
- [ ] Testler + ruff; commit.

## Görev 7 (B1b): `--strict` orkestrasyonu
Dosyalar: `scripts/showme_function_audit.py`, `scripts/audit_functions.py` (girdi çiftleri),
yeni `backend/tests/test_truth_audit_runner.py`.

- [ ] Başarısız test: istek fonksiyonu enjekte edilebilir runner; sahte yanıtlarla (a) T3 için
      iki istek atıldığını, (b) ağ hatasında tek tekrar → `network_flake`, (c) çökme sonrası
      `ledger.partial.json`'dan kaldığı yerden devam, (d) çıktı dizin yapısını doğrula.
- [ ] Uygula: `--strict` bayrağı; varsayılan mod bayt-bayt aynı davranır. Çıktı
      `artifacts/showme-truth-audit/<UTC>/` (`ledger.json`, `summary.md`, kod başına
      request/response). Sidecar'ı `scripts/sidecar_smoke.py` yardımcılarıyla başlatıp ölürse
      yeniden başlat.
- [ ] Mevcut audit testleri + yeni testler yeşil; commit.

## Görev 8 (B1c): Çevrimdışı kapı + ratchet
Dosyalar: yeni `backend/tests/test_function_truth_gate.py`, yeni `tests/_truth_baseline.json`,
`backend/pyproject.toml` (`markers = ["live: ağ gerektirir"]`).

- [ ] Kapı testi: manifest/katalogdan (sidecar'sız) T4-AST, T5-katalog, T6 koşar; sonuçları
      baseline ile karşılaştırır; yeni KIRMIZI → FAIL (diff ile). Baseline yoksa yazar ve geçer
      (mevcut fakery testindeki desen).
- [ ] `--update-baseline` yalnızca azaltmaya izin verir; artışta reddeder (testle kanıtla).
- [ ] Canlı kapı: aynı dosyada `@pytest.mark.live` testleri sidecar_smoke ile başlatıp T2/T3/T7/T8.
- [ ] Varsayılan paket hâlâ ağsız ve yeşil; commit (baseline dahil).

## Görev 9 (B1d): Canlı tarama ve ilk liste
Dosyalar: yeni `docs/audit/truth-audit-summary.md`, `tests/_truth_baseline.json` (gerekirse).

- [ ] `python scripts/showme_function_audit.py --strict` arka planda, sidecar `--port 0`.
- [ ] Sonuçları oku; kontrol yanlış-pozitiflerini (izin listesi eksikleri vb.) Görev 6 testleriyle
      birlikte düzelt ve yeniden koş — ama fonksiyon kodunu değiştirme.
- [ ] `docs/audit/truth-audit-summary.md`: YEŞİL/SARI/KIRMIZI/flake sayıları, kategori kırılımı,
      en kötü 20, kontrol başına KIRMIZI dağılımı.
- [ ] Commit. Kullanıcıya sayıları ve en kötü 20'yi kısa raporla.

---

## Görev 10 (B2): Ajan derin incelemesi
Dosyalar: yeni `docs/audit/b2/<birim>.json` (her workflow sonucu), workflow script'leri
oturum dizininde.

- [ ] Birim listesini canlı katalogdan üret (~16 birim; portföy 3, haber 2 parça).
- [ ] Workflow şablonu (birim başına pipeline): inceleyici (haiku, şema: findings[]) →
      her P0/P1 için çürütücü (haiku, "emin değilsen refuted=true") → çelişkide hakem
      (Opus, model override yok) → birim sonunda eksiklik denetçisi (haiku) → boşluk varsa
      ek tur (en fazla 1).
- [ ] İnceleyici talimatı spec §3.2'deki 5 adım; ajanlar dosya düzenlemez, yalnızca okur,
      sidecar'a HTTP atar ve scratch'te numpy ile sağlama yapar. Referans URL ve kanıt zorunlu.
- [ ] 5–6 workflow (her biri ~10 ajan) sırayla; her biri sonrası `docs/audit/b2/` güncellenir,
      dönmeyen ajanlar "incelenmedi" olarak loglanır.
- [ ] Commit (birim sonuçları).

## Görev 11: Birleşik liste, bütünsel inceleme, teslim
Dosyalar: yeni `docs/audit/function-ledger.json`, `docs/audit/function-ledger.md`,
`contracts/keyless_alternatives.json`, `tests/_truth_baseline.json`.

- [ ] B1 + B2'yi birleştir: fonksiyon başına not, kontroller, doğrulanmış bulgular, anahtarsız
      kaynak önerisi, S/M/L tahmini. Sıralama: P0/KIRMIZI → çekirdeklik (GP, HP, FA, DES, TOP, CN,
      WATCH, ECO, PORT, OMON, CRVF, WIRP, MAP) → P1 → P3.
- [ ] Yalnızca doğrulanmış anahtarsız kaynakları `keyless_alternatives.json`'a yaz; çevrimdışı
      kapıyı yeniden koş, baseline'ı gerekirse yalnızca aşağı güncelle.
- [ ] Kategori başına "D için önerilen sıra".
- [ ] Tüm dal diff'ine bağımsız bütünsel inceleme (Haiku inceleyici; çelişkili önemli bulguda
      Opus); önemli bulguları düzelt, etkilenen kontrolleri yeniden koş.
- [ ] Spec'e "Tamamlanma" bölümü: commit'ler, test sayıları, bilinen sınırlar.
- [ ] Kullanıcıya rapor + D için ilk kategoriyi sor.
