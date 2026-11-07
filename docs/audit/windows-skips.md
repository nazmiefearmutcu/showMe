# Backend test skip'leri — Windows (2026-11-07)

Ortam: Windows 11, `backend/.venv` (CPython 3.13), `fix/foundation-audit`.
Komut: `pytest -rs -o addopts=''` skip işaretli dosyalar üzerinde.

**Sonuç: platforma özgü (`skipif(win32)`) skip yok.** Windows'ta bir testi platform yüzünden
atlamaya gerek kalmadı. Kalan skip'ler iki gruba ayrılıyor.

## Düzeltilen sahte skip'ler

| Test | Eski skip sebebi | Gerçek neden | Düzeltme |
|---|---|---|---|
| `test_degarbage_commodity_cpf.py` (2 test) | "CPF execute raised (likely offline)" | Test yardımcısı `asyncio.get_event_loop()` Python 3.12+/3.13'te "no current event loop" fırlatıyordu; `except Exception → skip` bunu ağ hatası gibi gizliyordu | `_run` → `asyncio.run` (repo emsali: `test_session03_codes.py`). Testler artık canlı yolu koşup geçiyor. |
| `test_session08_codes.py` | (skip değil, kırılgan) | Aynı `get_event_loop` deseni | Aynı düzeltme. |

## Kalan skip'ler (10) — platform değil, B/D takibi

| Test | Skip sebebi | Değerlendirme |
|---|---|---|
| `test_degarbage_deriv_stubs.py:177` (2) | "no real deps with a yfinance adapter available" | Test, motorun gerçek `FunctionDeps` kurulumunu bulamıyor; canlı dalı hiç koşmuyor. Gerçek deps ile `-m live` testine çevrilmeli. |
| `test_degarbage_fx_ovdv.py:84`, `:110` | "yfinance history unavailable" | `OVDVFunction()` deps'siz kuruluyor → her zaman etiketli referans yedeğine düşüyor; canlı ATM yüzeyi bu ortamda hiç test edilmiyor. Aynı takip. |
| `test_degarbage_portfolio_pvar.py:79`, `:98` | "provider unavailable" | `PVARFunction()` pozisyonsuz/deps'siz → `empty`; VaR monotonluk/ölçekleme invaryantları hiç koşmuyor. Aynı takip. |
| `test_kaos_parity.py:189` (2), `:230` | "Entropy engine not importable" | Harici yerel motor (`~/Entropy`) gerektiren parite testi — meşru ortam skip'i. |
| `test_migration.py:137` | "showMe/engine not local" | Eski motor dizinini gerektiren göç testi — meşru ortam skip'i. |

Not: varsayılan pakette ağa çıkan ve ağ yoksa skip'e düşen başka testler de var (World Bank,
Polymarket, Binance/Yahoo klines — `test_degarbage_*`). Bu makinede ağ olduğu için skip'e
düşmediler. Hermetik varsayılan paket hedefi için bunların `-m live`'a taşınması B1 kapısıyla
birlikte ele alınacak (plan Görev 8).
