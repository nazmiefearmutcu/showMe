# MEET Quality Gate Suite — tasarım

Tarih: 2026-09-19 · Kapsam: MEET pilot (desen sonra 141 fonksiyona yayılır)
Karar: Yaklaşım A — 4 hermetik CI kapısı + `contracts/meet.json` + cron probe.
Yaptırım: CI-blocking. Canlı veri: hermetik CI + advisory cron.

## 1. Mimari

Üç parça: (a) `contracts/meet.json` — `scripts/gen_meet_contract.py` ile
`meet_seed.py` + `meet.py::_DATA_FILTERS` içinden üretilen tek doğruluk
kaynağı (input adları + options + defaults, must_have, kart slotları,
data_filter değerleri). (b) 4 kapı testi — hermetik, ağ yok, mevcut
105+52 testin üstüne eklenir. (c) `.github/workflows/meet_probe.yml` —
gece cron + manuel dispatch, advisory, fail etmez.

Akış: manifest → üretici → JSON → tüketici testler (freshness dahil).
UI Python'a değil JSON'a bakar. Yeni regresyon = fixture JSON'a satır;
eşik yükseltme = tek sayı.

## 2. Altın-set skoru (`test_meet_golden.py`)

Fixture: `backend/tests/fixtures/meet_golden.json`, ~60 kayıt
`{text, expected: {countries, asset_tags, topic_tags, event_type,
impact, pairs}}`. Tohum: Task 3'ün 30+12 kanıtlanmış örneği (EU vakaları,
war-override, hack, ETF-çoğul, Türkçe, `Turkeyrate` bitişiği).
Kapılar: country mikro-F1 ≥ 0.95, event_type exact ≥ 0.90, impact exact
≥ 0.90, pairs recall ≥ 0.95. Skor fonksiyonu `world_events`'i doğrudan
çağırır (<1s, deterministik, providersız).

## 3. Kontrat-drift

Üç assertion: (a) freshness — JSON üretici çıktısıyla birebir değilse
fail (geliştirici scripti koşup commitler). (b) backend — `_shell`
anahtarları must_have + kartları kapsar, `_DATA_FILTERS` seed options
ile eşit. (c) UI — `MEET.tsx` DATA seçenekleri JSON ile birebir aynı
(alt küme kabul edilmez). Yeni ölü input / eksik kart / seçeneksiz
filtre = kırmızı CI.

## 4. Latency + veri-kalite

Latency (`test_meet_budgets.py`, gerçek bekleme yok — `wait_for` spy +
anlık fake'ler): soğuk-açılış worst-case ≤ 5s, GDELT leg
`min(timeout,5)`, cache-hit µs mertebesi, per-feed/collection 3..5s
clamp tablosu. Veri-kalite (`test_meet_data_quality.py`, kusurlu
fixture ~40 takvim + 30 headline): `dropped_no_time` tam-sayı pinli,
dupe = 0, `seconds_to_event` ±2s, bilinmeyen token kaybı whitelist'li
(`ALL`→global hariç kayıp = fail), zorunlu ISO kapsama seti
(US/EU/GB/JP/CH/CA/AU + TR mapping varlığı).

## 5. Cron + CI + yayılma

Cron 03:00 UTC schedule + dispatch: FF/GDELT/RSS latency, count,
429/timeout, tagged_ratio, TR kapsama → artifact + summary, fail yok.
CI: yeni testler mevcut `ci.yml` python job'una otomatik dahil, ekstra
job yok. Yayılma bu spec'in dışında; desen (`contracts/<CODE>.json` +
4 kapı şablonu) sabit kalır.

## Bağlayıcı kararlar

- Gürültü filtresi opt-in strict yorumu korunur (`major_only` tüm
  low'ları düşürür); UI başlığı bunu yazar.
- Canlı eşikler cron'a taşınmaz; CI deterministik kalır.
- Mutasyon testi, canlı-in-CI, repo-çapı rollout: YAGNI, yok.
- Test sayıları hedefi: backend ~130, UI ~60 (mevcut yeşilin üstü).
