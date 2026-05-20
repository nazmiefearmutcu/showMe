# showMe X Scraper AI

X (Twitter) paylaşımları üzerinden gerçek-zamanlı sentiment + emotion + topic analizi yapan modüler bir AI bileşeni — showMe app'in **haber** ve **hisse haberi** kısımlarına entegre edilmek üzere tasarlandı.

## Klasör yapısı

```
x_scraper_ai/
├── model/
│   └── showme_x_v1/          # Eğitilmiş model (~490 MB)
│       ├── backbone/         # RoBERTa safetensors
│       ├── tokenizer/
│       ├── heads.pt          # 3 task head + meta
│       ├── label_maps.json   # sentiment/emotion/topic etiketleri
│       ├── inference.py      # ShowMeXAnalyzer sınıfı
│       ├── requirements.txt  # torch + transformers
│       └── README.md         # Model dokümantasyonu
├── scripts/
│   ├── x_scraper.py          # X paylaşımı çekme (snscrape/twscrape/ntscraper fallback)
│   └── analyze.py            # Sorgu → scrape → model → toplu metrik + doğal dil özet
├── notebooks/
│   ├── colab_cells.md        # Colab notebook hücreleri (master kopya)
│   └── cell2_pipeline.py     # Tam eğitim pipeline'ı (yeniden eğitim için)
├── data/                     # Boş — Colab'da Drive'a yüklenir
├── docs/
└── README.md                 # Bu dosya
```

## Eğitim Sonuçları

| Görev      | Acc      | F1 (macro) | Eşik    | Sonuç |
|------------|----------|------------|---------|-------|
| Sentiment  | 0.7448   | **0.7376** | ≥ 0.65  | ✅    |
| Emotion    | 0.8346   | **0.8002** | ≥ 0.70  | ✅    |
| Topic      | 0.9262   | **0.9153** | ≥ 0.75  | ✅    |
| **Best avg F1** |     | **0.8177** |    | ✅    |

Eğitim: Colab G4 (NVIDIA RTX Pro 6000 Blackwell, 102 GB VRAM) · 6 epoch · batch=96 · bf16.
Base: `cardiffnlp/twitter-roberta-base-sentiment-latest` (124M tweet ile pre-trained).

## Hızlı kullanım

```bash
# 1. Bağımlılıklar
pip install -r model/showme_x_v1/requirements.txt
pip install snscrape  # ya da twscrape / ntscraper

# 2. Sorgu üzerinden tek komutla analiz
python scripts/analyze.py "AAPL" --limit 200 --since 2026-04-01 --lang en

# 3. Doğal dil sorgusu
python scripts/analyze.py "\$TSLA bugün bullish mi?" --natural
```

## Programatik kullanım

```python
from scripts.analyze import ShowMeXAnalyzer

a = ShowMeXAnalyzer(model_dir="model/showme_x_v1")
result = a.analyze_topic("AAPL", limit=200, since="2026-04-01", lang="en")
print(result["summary_tr"])
print(result["scores"])
print(result["distributions"])
```

Sadece tek bir metin için sınıflandırma (scrape olmadan):

```python
import sys; sys.path.insert(0, "model/showme_x_v1")
from inference import ShowMeXAnalyzer
m = ShowMeXAnalyzer("model/showme_x_v1")
print(m.analyze("AAPL just blew earnings out of the water"))
```

## showMe entegrasyon notu

Bu paket **standalone** bir bileşen olarak teslim edildi — showMe app'ine otomatik enjekte edilmedi.
Backend sidecar'ından çağırılabilir, ya da ayrı bir Python servisi olarak çalıştırılabilir.

Önerilen entegrasyon noktaları:
- `showMe/backend` Python sidecar'ında lazy-loaded olarak başlat (cold-start ~1-2 sn)
- Bir endpoint: `POST /api/x_analyze` → body `{query, limit, since}` → JSON özet
- Frontend (haber + hisse haberi kısmı) bu endpoint'ten metric + örnekler çeker

Üretim ipuçları:
- Modeli singleton tut (process başına 1 kez yükle, ~500 MB RAM)
- Uzun sorgu listesi için batch=32 ile işle
- GPU/MPS varsa 6× hızlanma

## Yeniden eğitim / iyileştirme

`notebooks/cell2_pipeline.py` Colab'da yeniden çalıştırılabilir. Daha güçlü bir model için:
- Base'i `cardiffnlp/twitter-roberta-large-topic-sentiment-latest` (355M) olarak değiştir → ~+2-3 F1
- Daha çok finansal veri (örn. StockTwits dump'ları) ile augment
- Topic için daha geniş taxonomy (Brand24-style)
