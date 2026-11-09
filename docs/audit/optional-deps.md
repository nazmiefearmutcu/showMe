# Opsiyonel Python paketleri

Son tarama: 2026-11-07 (`fix/foundation-audit`, Görev 1). Yöntem: `backend/showme` altındaki tüm
üst-düzey (`level == 0`) import'lar AST ile taranır, stdlib ve `showme` dışındakiler venv'de
`importlib.util.find_spec` ile aranır.

İlk tablodaki yollar `backend/showme/`, ikinci tablodakiler `backend/showme/engine/` köküne görelidir (tam yol verilenler hariç).

Kural: bir paket **anahtarsız bir fonksiyonun çekirdek yolunda** gerekiyorsa
`backend/pyproject.toml` `dependencies`'e girer. Yoksa opsiyonel kalır; import'u fonksiyon
içinde ya da `try` bloğunda olmalı ve paket yokken sebep açıkça yüzeye çıkmalı.

## Bu turda zorunlu yapılanlar

| Paket | Neden |
|---|---|
| `exchange-calendars` | `engine/reference/calendar_registry.py`: yoksa oturumlar yalnızca hafta içi/sonu kuralına düşer, tatiller görünmez (TRDH, piyasa açık/kapalı durumu). |
| `openpyxl` | `engine/data_sources/macro/damodaran_adapter.py`: anahtarsız Damodaran `ctryprem.xlsx` ayrıştırması. Import `_parse_workbook` içinde ve çağıran `try/except Exception: pass` içinde (satır ~137–149); paket yokken canlı veri **sessizce** gömülü `_ERP_FALLBACK` tablosuna düşüyordu. Artık temiz kurulumda canlı Damodaran verisi gelir. (Sessiz düşüş B denetiminin konusu.) |
| `pytest-timeout` (dev) | Testler `@pytest.mark.timeout` kullanıyor. |

## Bilinçli opsiyonel kalanlar

| Paket | Kullanan | Paket yokken davranış | Gerekçe |
|---|---|---|---|
| `python-binance` (`binance`) | `engine/api/binance_client.py` (eski TBV3 bot/tarayıcı: `bot_service`, `scanner_service`, `engine/main.py`) | Modül yüklenir; `BinanceClient.initialize()` → `BinanceUnavailableError` (`engine/main.py` yakalayıp 1 ile çıkar) | Yalnızca eski bot hattı kullanıyor; fonksiyon kataloğu `BinanceClient`'ı başlatmıyor (`binance_broker` paper yolu `initialize()` çağırmaz). Kurulum: `uv sync --extra binance`. |
| `scipy` | `functions/portfolio/port.py`, `pvar.py` (`norm.ppf`) | Acklam yaklaşıklığı (azami göreli hata ~1.15e-9) | Saf Python yedek yeterince hassas. |
| `scikit-learn`, `xgboost`, `lightgbm` | `services/ml_signals.py` (MLSIG) | `lstsq_logistic` saf NumPy taban modeli, `backend` alanında raporlanır | Paket boyutu (scipy dahil) sidecar paketini büyütür; MLSIG'in kalitesi D (portföy) kapsamında kararlaştırılacak. |
| `openai`, `anthropic` | `agents/llm_router.py`, `services/transcription.py` | LLM yönlendirme / bulut transkripsiyon devre dışı | Anahtar gerektirir. |
| `openai-whisper`, `faster-whisper` | `services/transcription.py` | Yerel transkripsiyon devre dışı | Ağır model indirmesi. |
| `onnxruntime` | `services/semantic_tagger.py` | Anlamsal etiketleyici devre dışı | Ağır çalışma zamanı. |
| `nltk` | `services/sentiment.py` | VADER yedeği yerine FinBERT/diğer yol | İkincil yedek. |
| `meilisearch` | `services/news_index.py` | Arama indeksi devre dışı | Harici sunucu + anahtar. |
| `plotly` | `agents/viz.py` | Ajan görselleştirmesi devre dışı | UI kendi grafiklerini çiziyor. |
| `fido2` | `services/webauthn_service.py` | WebAuthn devre dışı | Opsiyonel güvenlik özelliği. |
| `alpaca-py`, `ib_insync` | `data_sources/broker/*` | İlgili broker adaptörü kullanılamaz | Broker hesabı + anahtar gerektirir. |
| `veryfinder` | `backend/showme/veryfinder_bridge.py` | Köprü devre dışı | Harici yerel araç. |
