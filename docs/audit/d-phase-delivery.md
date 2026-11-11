# D fazı — teslim raporu (fix/foundation-audit)

Tarih: 2026-11-08 · Dal: `fix/foundation-audit` (push edilmedi) · Hedef: her fonksiyon
Bloomberg-terminal kalitesinde, **asla sahte veri yok**, dürüst durum etiketleri.

## Özet

| Ölçü | Başlangıç | Teslim |
|---|---:|---:|
| Doğrulanmış düzeltilmiş bulgu (dalga kayıtları) | — | **626** (557 + 69 takip turunda) |
| Gerçek olmadığı doğrulanan bulgu | — | 28 |
| Dalga sonrası elle kapatılan bulgu | — | 40+ (aşağıda) |
| Açık kalan gerçek kısıt (artık) | — | 13 (aşağıda, gerekçeli) |
| Statik doğruluk denetimi bulgu sayısı (ratchet) | 522 | **411** |
| Çevrimdışı dürüstlük (T10) kırmızı bulgu (ratchet) | 37 | **0** (142 fonksiyon) |
| Canlı strict denetim KIRMIZI | 9 (B1, farklı kural seti) | 11 → bkz. aşağı (10'u "girdi gerekli") |

Düzeltme dalgaları: P0 (10 grup), P1-A (14), P2/P3-A (15), B1 (21), C1 (52), C2 (6), C3 (16),
her grup için Haiku TDD uygulayıcı → çekişmeli inceleme → düzeltme → oturum modeli eskalasyonu.

## Kök neden düzeltmeleri (birden çok fonksiyonu etkileyen)

1. **`/api/fn` yönlendirici politikası (e09939e6).** Her çağrı ajan profilinden (limit 6,
   120 gün, 3M, eş sembol listesi, haber sorgusu, 3 sn zaman aşımı) başlıyor ve fonksiyonun
   kendi varsayılanlarını eziyordu. Artık genel pencere/boyut/metin/eş anahtarları yalnızca
   çağıran gönderirse ya da kod bazında tanımlıysa geçer; enjekte edilenler `routeDefaults`
   olarak ayrı raporlanır, `inputEcho` yalnızca çağıranın girdisini gösterir. Ajanın kendi
   sonda parametreleri 142 fonksiyonun hepsinde birebir aynı kaldı (doğrulandı).
   Kapanan: GMM#1/#5, SECF#2, BQL#3/#4, READ#1, FXH#4, PCAS#1, ICX#3, CSRC#4, FSRC#2,
   DCFS#3/#4, DDM#4, BTFW#1, BTUNE#2, ISIN#7, OVME#1.
2. **Sentetik veri üreteçleri kaldırıldı (veri politikası).**
   - CORR: `live=false` Gauss fiyat yolları üretip korelasyon matrisi yayınlıyordu → artık
     açık `input_error`; üreteç silindi; paneldeki Ref anahtarı kaldırıldı (56a58eef).
   - WETR: "seasonal model" bir sinüs eğrisiydi → `reference`/`modeled` artık `input_error`;
     üreteç silindi; Modeled sekmesi kaldırıldı (a0013728).
   - TRA: canlı akış başarısız olunca şablon fiyat geçmişine düşüyordu → artık
     `provider_unavailable`/`input_error`; `_template_history` silindi (da881bd3).
3. **Sağlayıcı zaman politikası.** Borsa saati olmayan kote reddedilir; `previousClose` asla
   son fiyat sayılmaz; NGAS önceki kapanış kontrolü ABD Doğu işlem gününe göre (460983d7).
4. **Zarf/durum sınıflandırması.** `_status_family`, model > referans > sentetik >
   provider_unavailable > canlı merdiveni, hata vetosu; varsayılan sembol uyarısı (XCON-5).
5. **Boş hata metni taraması.** `except` içindeki `{e}` alanları `str(e) or type(e).__name__`
   (toplam ~250 alan; zaman aşımı gibi metinsiz hatalar artık boş görünmez).
6. **Güvenli bağlantılar (SEC-8).** `safeHref()`: yalnızca http(s) adresleri bağlantı olur
   (XSEN, FTS, INSTANT, DES, PEOP, GP, ANR, TSAR).

## Dalga sonrası elle kapatılanlar (örnekler)

WIRP beklenen hareket (aralık orta noktası), WB referans uyarısı, SRSK anahtarsız FRED +
aynı ay hizalaması, CORR `sqrt(252)` bandı (XCON-7), WACC banka metni (WACC#3), BTFW örneklem
tabanı, STRS tanımsız varlık sınıfı, FXFC ECB günlük kur etiketi, BGAS EIA etiketi,
ACCT okunamayan nakit, DCFS Ke etiketi + merkezli ızgara, DDM manifest varsayılanları,
ANR trend penceresi, ICX sektör seçici, GMM tüm evren kartları, DAPI kapatma rotası belgeleri,
GREEKS boş defter, RV oran sütunları, TRA bölünme uzlaşması, TSAR konuşmacı etiketi,
ACCT/TRA ölü yapılandırma, CSRC hermetik test.

## Açık kalan kısıtlar (artık, gerekçeli)

| Kod | Durum | Neden kod değişikliği ile kapanmıyor |
|---|---|---|
| EQS#2/#3 | Kısmi, açıkça bildiriliyor | 500 sembollük soğuk evrende beta/sektör alanları Yahoo REFDATA hız sınırına (2/sn) takılıyor; kapsama `_coverage_warnings` ile gösteriliyor, sahte değer yok. |
| MOSS#1 | Kısmi, açıkça bildiriliyor | 46 sembollük varsayılan tarama 11–12 sn bütçede; soğuk önbellekte kapsama `scan_coverage` + `partial` ile bildiriliyor. |
| MGN#2/#3 | Muhafazakâr | `contract_type` taşımayan çıplak kripto çifti perpetual ise spot %100 teminatla fiyatlanıyor; ürün işaretçisi broker/pozisyon kaynağından gelmeli. |
| AIM#3 | Bildiriliyor | Eşlenmemiş iki broker etiketinde aynı order_id bir kez sayılıyor ve uyarıyla adlandırılıyor (iki dalga arasında bilinçli karar). |
| FLY#6 | Açık | OpenSky kullanım politikası çevrimdışı doğrulanamıyor. |
| TSOX#3 | Açık | ZN=F için kaynaklı sözleşme şartnamesi (çarpan, nominal) olmadan gerçek DV01 hesaplanamaz. |
| WCRS#4 | Açık | FX spot çözümlemesi için paket düzeyinde karar gerekiyor (FXFC/FXIP/FRD sahipleri). |
| PFA#5 | Özellik | Varlık bazlı atıf yok; sektör ağırlıkları/getirileri elle giriliyor (etiketli). |
| TRA#1, WACC#1 | Canlı doğrulama | Kod düzeltildi; canlı sağlayıcı değerleri ağsız testlerde yeniden ölçülmedi. |

Süreç notları (commit imzasında Haiku/Opus, kapsam dışı test dosyası) ürün kusuru değildir ve
listelenmemiştir.

## Doğrulama (sabitlenmiş commit üzerinde, `.claude/worktrees/verify`)

| Kontrol | Sonuç |
|---|---|
| Backend tam paket (006b64a1) | **6703 geçti**, 9 atlandı, 3 başarısız: TSAR ×2 ve flowmap WS; üçü de tek başına geçiyor (aşağı) |
| UI vitest tam paket (9db692ae; sonrasında UI değişmedi) | **514 dosya, 4201 geçti**, 2 atlandı |
| e2e smoke (Playwright, UI build dahil) | **20/20 geçti** |
| `tsc --noEmit`, eslint `--max-warnings 0` | temiz |
| Çevrimdışı dürüstlük denetimi (ağ kesik, 142 fonksiyon) | kırmızı 0 |
| Statik doğruluk kapısı | 411 (taban düşürüldü) |
| Canlı strict denetim (kendi sidecar'ı, app-home kopyası, botlar kapalı) | 131 SARI, 11 KIRMIZI |

Canlı denetimdeki KIRMIZI'lar: SRSK (negatif temerrüt olasılığı, **düzeltildi** — 32ef91b6) ve
10 fonksiyonun denetimin genel isteğine verdiği dürüst "girdi gerekli" yanıtı (BBGT emir tipi,
BRIEF portföy/izleme listesi, DINE konum, FXFC politika faizi, GEX `live_options`, LANG dil
kodu, PFA ağırlık/getiri, PORT_WHATIF miktar/maliyet, REBA canlı defter, SECF sorgu sütunu).
Bunlar sahte veri değil; denetim aracı fonksiyona özgü girdi göndermediği için KIRMIZI
notlanıyor. DARK/DPF "bayat veri" FINRA'nın 2–4 haftalık yayın gecikmesiydi; denetim
yapılandırmasına `finra_ats_weekly` (42 gün) eklendi ve DARK `as_of` yayımlıyor.

Bilinen yük kaynaklı kararsız testler: `test_flowmap_ws::test_disconnect_tears_feed_down`
(zamanlama) ve `test_degarbage_news_tsar` (yerel FinBERT modelini yükler; tam pakette
eşzamanlı ağır işler varken model yüklenemeyince TSAR dürüstçe `provider_unavailable` döner.
Kendinden önceki 215 dosyayla birlikte koşulduğunda geçer, yani sıraya bağlı bir sızıntı değil).

## Diğer oturumla koordinasyon

Awareness oturumunun sahip olduğu fonksiyonlar (TOP, NI, CN, NALRT, NSE, SOSC, EVTS, ECO,
MEET, DVD, CACT, TRDH) yönlendirici politikasında `_LEGACY_PROBE_ROUTE_CODES` ile muaf
tutuldu; o oturum birleştirmede kendi kodlarını politikaya alacağını ve kendi modüllerindeki
hata metni taramasını yapacağını bildirdi.

## v0.3.0 sonrası (2026-11-11, dal `fix/post-0.3.0-followups`)

Yukarıdaki "kararsız test" ve "KIRMIZI" notlarının yerine geçer:

- **flowmap WS oturum sızıntısı (gerçek hata).** Bağlantı görevi iptal edilince `run()`
  içindeki `finally` bloğunun ilk `await`'i hata veriyor, `_drop_session` hiç çalışmıyordu:
  hub oturumu ve üst akış istemcisiz açık kalıyordu. Temizlik artık korumalı kapsamda
  çalışıyor. `test_disconnect_tears_feed_down` CPU yükü altında 4/6 düşüyordu, şimdi 0/6.
  "Zamanlama kaynaklı kararsız test" tanısı yanlıştı.
- **TSAR testleri.** Neden ne bellek baskısı ne de model kilidiydi. `test_kaos_parity`
  test toplama sırasında başka bir projenin (Entropy) sanal ortamını `sys.path`'e ekliyor ve
  hiç kaldırmıyordu; bu ortamda bulunmayan PIL oradaki uyumsuz derlemeden çözülünce FinBERT
  oturumun geri kalanında yüklenemiyordu. Yol artık yalnızca o modülün testleri sırasında
  ekli. Eski dosyayla hata yeniden üretildi (2 başarısız), düzeltmeyle geçti. Ayrıca
  `conftest` her testten önce model hata kilidini temizliyor. Yukarıdaki "sıraya bağlı bir
  sızıntı değil" ifadesi yanlıştı.
- **Tarihe bağlı testler.** GEX testlerindeki sabit vade (2026-11-09) geçti, TCA testindeki
  sabit işlem gün içi veri saklama süresini aştı; testler artık koşulduğu güne göre çalışıyor.
- **Canlı strict denetim.** 10 "girdi gerekli" KIRMIZI'nın nedeni denetim aracının genel
  isteğiydi. Araç artık her fonksiyona zorunlu girdisini gönderiyor. Önceki 13 KIRMIZI'nın
  canlı yeniden koşusu: **0 KIRMIZI** (11 SARI, DARK ve DPF YEŞİL; SRSK'de negatif olasılık yok).
- **MGN#2/#3.** Ürün işaretçisi olmayan kripto çifti hâlâ spot oranıyla teminatlandırılıyor
  (büyük olan gereksinim), ama artık satırda `product_assumed=spot` ve MGN uyarısıyla
  açıkça belirtiliyor.
- **Lint.** Backend'de ruff temiz (55 kullanılmayan import, 3 tanımsız ad düzeltildi).
