# Strict truth audit — ilk canlı tarama (B1)

Çalıştırma: `python scripts/showme_function_audit.py --strict` — 2026-11-07 21:30Z, Windows 11,
`fix/foundation-audit`. Ham çıktı (gitignore'da): `artifacts/showme-truth-audit/20261107T213030Z/`
(`ledger.json`, `summary.md`, istek/yanıtlar). Kurallar daraltıldıktan sonra aynı yanıtlar
`--regrade` ile yeniden notlandı (fonksiyon yeniden çağrılmadı).

Ortam: sidecar `--port 0`, `SHOWME_DISABLE_BOTS=1`, kullanıcı app-home'unun **kopyası** (botlar
kapalı, kimlik dosyaları hariç). Trade çağrıları zorla `submit=false, paper_mode=true`.
153 vaka (fonksiyon × birincil varlık), sidecar tıkanması: 0.

## Notlar

**Veri doğruluğu** (yalnızca canlı vakalar; yardım metni hariç):

| Not | Fonksiyon |
|---|---:|
| YEŞİL | 91 |
| SARI | 42 |
| KIRMIZI | 9 |

**Birleşik not** (yardım-metni borcu SARI sayılınca): 4 YEŞİL · 129 SARI · 9 KIRMIZI.
142 fonksiyonun 131'inde girdiler genel ("symbol"), 80'inde açıklama boş, 75'inde amaç metni
şablon ("X function.") — dokümantasyon borcu, ayrı sütunda izlenir, KIRMIZI'ya karar vermez.

## KIRMIZI (9) — doğrulanmış

| Kod | Kural | Ne gösteriyor |
|---|---|---|
| GREEKS | live_claim_without_provider | Kendi hesapladığı Greeks'i `data_state=live` diye sunuyor; özet kartında delta/gamma `null` |
| TLH | live_claim_without_provider | `portfolio_state` tek kaynak, `live` iddiası; fiyat sağlayıcısı görünmüyor |
| BBGT, EMSX, FXGO, TSOX | live_claim_without_provider | Paper ticket önizlemesi `live` etiketiyle |
| MGN | fake_source + placeholder_value | `sample_margin_positions` örnek pozisyonları, `cash=10000` |
| PSC | placeholder_value | `account=10000`, `entry=100` istenmeden kullanılıyor |
| YAS | static_output | US10Y ve US2Y için 115 sayı birebir aynı (girdi yok sayılıyor; fiyat 99.5/kupon 4.25 varsayılanları) |

## SARI — dikkat çekenler

Boş / sağlayıcı yok (24 vaka):

| Kod | Gerekçe (fonksiyonun kendi mesajı) | Not |
|---|---|---|
| TOP | no records returned for the current input | **çekirdek haber fonksiyonu boş** — B2 öncelik |
| NSE | No live news rows returned for query 'market news' | haber araması boş |
| BRIEF, MOST | warming in background | ev SWR önbelleği soğuk çağrıda ısınma zarfı döndürüyor |
| DARK, DPF | FINRA latest week 2025-09-15 / 2023-12-11 is stale | veri kaynağı bayat (C) |
| EREV | finnhub: FINNHUB_API_KEY not set | anahtarsız alternatif gerekli |
| MLSIG | Need at least 200 OHLCV rows; provider returned 65 | fonksiyon yetersiz geçmiş istiyor (hata) |
| SOSC | GDELT request failed: ConnectTimeout | GDELT erişimi |
| TSAR | No stored transcript matches found for 'revenue' | yerel transkript deposu boş |
| PORT, PVAR, PCAS, STRS, LOTS, TCA, ACCT, AIM, EXEC | boş portföy / emir yok | app-home kopyasında pozisyon yok — portföy fonksiyonlarının gerçek davranışı B2'de dolu bir portföyle ölçülmeli |
| DDIS, DINE, LITM, MICRO, READ | girdiye göre kayıt yok / L2 sağlayıcı yok | B2'de girdi ve kaynak kontrolü |

Yavaş (T8, sıcak > 3 sn): ALLQ 11.1 · AV 10.2 · PORT_OPT 9.1 · SOSC 6.9 · SRCH 5.0 · GLCO 4.5 ·
SECT 4.3 · FA 4.1 · NI 4.0 · TLDR 4.0 · CN 3.5 · MARS 3.3 · MOST 3.3 · RV 3.1.

Diğer: POLY ve SRSK olasılıkları yüzde ölçeğinde ama birimsiz adla (`implied_prob=89.25`,
`highest_pd=11.30`); ALRT, CDE, DCF, DDM yerel/model verisini `none` kaynağıyla etiketliyor.

Koda gömülü yer tutucu varsayılanlar (T4, kaynak): GEX/OVME `params.get("spot", 100)`, MGN
`cash=10000.0`, PSC `account=10000`/`entry=100`, HVT/IVOL/OSA `_stubs.py` spot/strike
şablonları, ticket `quantity: 0`, PORT_WHATIF `quantity` 0.

## Kural ayarları (bu turda)

İlk notlamadaki yanlış alarmlar fonksiyonlara dokunmadan kurallardan ayıklandı
(`contracts/truth_audit.json`): takvim/tahmin kodları (CPF, WIRP, WETR, ECFC, FXFC) ileri tarih
gösterebilir; VCAP yıllık; opsiyon zinciri strike'ları ve backtest başlangıç sermayesi yer tutucu
değil; DCF/DDM ve ticket'larda T3 geçersiz (denetim açık girdi veriyor); `none` kaynağı yalnızca
canlı iddiasıyla birlikte KIRMIZI; yüzde ölçekli olasılık birimsizse SARI.

## Sınırlar

- Otomatik kapı hesap doğruluğunu ölçmez (ör. PFA'nın Brinson ayrıştırması doğru mu) — B2.
- Denetim parametreleri `scripts/audit_functions.py:params_for`'dan; bazı fonksiyonlar gerçek
  girdileriyle (ör. DCF'in sembolden nakit akışı çekmesi) hiç denenmedi — B2.
- Portföy fonksiyonları boş portföyle koştu; app-home kopyasında pozisyon yoktu.
- Tek örnek gecikme (p95 değil); ilk tarama denemesi bir sidecar tıkanmasıyla geçersiz kaldı
  (tekrarlanamadı) — runner artık kanarya + yeniden başlatma ile ayırt ediyor.
