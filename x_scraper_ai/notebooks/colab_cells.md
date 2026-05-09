# showMe X Scraper AI - Colab Notebook Hücreleri

Bu dosya Colab notebook'una yapıştırılacak hücrelerin master kopyasıdır.
Her `## CELL N` başlığı yeni bir Code hücresidir.

## CELL 1: Setup, Drive Mount, GPU Kontrol

```python
# ============================================================
# showMe X Scraper AI - Multi-task Tweet Analysis Model
# ============================================================
import os, sys, time, json, gc, subprocess
from pathlib import Path

# --- Drive Mount ---
from google.colab import drive
print("Drive baglaniyor (popup acilabilir)...")
drive.mount('/content/drive', force_remount=False)

PROJECT_DIR = '/content/drive/MyDrive/showme_x_scraper_ai'
DATA_DIR    = f'{PROJECT_DIR}/data'
MODEL_DIR   = f'{PROJECT_DIR}/model'
CHECKPOINT_DIR = f'{PROJECT_DIR}/checkpoints'
LOG_DIR     = f'{PROJECT_DIR}/logs'
STATUS_FILE = f'{PROJECT_DIR}/status.json'

for d in [PROJECT_DIR, DATA_DIR, MODEL_DIR, CHECKPOINT_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)
os.chdir(PROJECT_DIR)
print(f"PROJECT_DIR: {PROJECT_DIR}")

# --- GPU Kontrolü ---
import torch
print(f"\nCUDA: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    name = torch.cuda.get_device_name(0)
    mem  = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"GPU: {name}  |  VRAM: {mem:.1f} GB")
    # Detect tier
    n = name.upper()
    if 'H100' in n: TIER, BATCH = 'H100', 64
    elif 'A100' in n: TIER, BATCH = 'A100', 48
    elif 'BLACKWELL' in n or 'RTX PRO 6000' in n or 'G4' in n: TIER, BATCH = 'G4_BLACKWELL', 56
    elif 'L4' in n: TIER, BATCH = 'L4', 32
    elif 'V100' in n: TIER, BATCH = 'V100', 24
    elif 'T4' in n: TIER, BATCH = 'T4', 16
    else: TIER, BATCH = name, 16
    print(f"Tier: {TIER}  |  Suggested batch: {BATCH}")
else:
    print("UYARI: GPU yok! Calisma zamani > Calisma zamani turunu degistir > GPU sec.")
    TIER, BATCH = 'CPU', 4

# --- status.json: 10 dakikalik kontrol icin ---
def write_status(stage, **kwargs):
    payload = {'stage': stage, 'ts': time.time(),
               'iso': time.strftime('%Y-%m-%d %H:%M:%S'),
               'gpu': TIER, **kwargs}
    with open(STATUS_FILE, 'w') as f:
        json.dump(payload, f, indent=2)
    print(f"[STATUS] {stage}: {kwargs}")

write_status('setup_complete', gpu=TIER, vram_gb=round(mem,1) if torch.cuda.is_available() else 0)
```

## CELL 2: Bagimliliklari yukle

```python
import subprocess

# Colab on yukluleri zaten var; minimum upgrade
pkgs = ['transformers>=4.46', 'datasets>=3.0', 'accelerate>=1.0',
        'evaluate', 'scikit-learn', 'huggingface_hub',
        'sentence-transformers', 'peft>=0.13']
print("Paketler yukleniyor...")
subprocess.run(['pip', 'install', '-q'] + pkgs, check=True)

# Versiyon kontrolu
import transformers, datasets, accelerate
print(f"transformers: {transformers.__version__}")
print(f"datasets:     {datasets.__version__}")
print(f"accelerate:   {accelerate.__version__}")
print(f"torch:        {torch.__version__}")

write_status('deps_installed')
```

## CELL 3: Veri setlerini indir (HuggingFace + GitHub)

```python
from datasets import load_dataset, Dataset, DatasetDict
import pandas as pd
import requests
from collections import Counter

# Kullanilacak veri setleri (hepsi acik)
HF_DATASETS = [
    # (hf_id, config, train_split, test_split, save_name, task)
    ('cardiffnlp/tweet_eval', 'sentiment',  'train', 'test', 'te_sentiment', 'sentiment'),
    ('cardiffnlp/tweet_eval', 'emotion',    'train', 'test', 'te_emotion',   'emotion'),
    ('cardiffnlp/tweet_eval', 'stance_climate', 'train', 'test', 'te_stance',  'stance'),
    ('cardiffnlp/tweet_eval', 'offensive',  'train', 'test', 'te_offensive', 'offensive'),
    ('cardiffnlp/tweet_eval', 'irony',      'train', 'test', 'te_irony',     'irony'),
    ('zeroshot/twitter-financial-news-sentiment', None, 'train', 'validation', 'fin_sentiment', 'fin_sentiment'),
    ('zeroshot/twitter-financial-news-topic',     None, 'train', 'validation', 'fin_topic',     'fin_topic'),
]

stats = {}
for hf_id, cfg, tr, te, name, task in HF_DATASETS:
    print(f"  -> {hf_id} [{cfg}]")
    try:
        ds = load_dataset(hf_id, cfg) if cfg else load_dataset(hf_id)
        ds.save_to_disk(f'{DATA_DIR}/{name}')
        n_tr = len(ds[tr]) if tr in ds else len(ds[list(ds.keys())[0]])
        stats[name] = {'task': task, 'train_size': n_tr}
        print(f"     OK  train={n_tr}")
    except Exception as e:
        print(f"     HATA: {e}")
        stats[name] = {'task': task, 'error': str(e)}

# Financial PhraseBank (sentiment - Reuters press releases, finance domain)
try:
    fp = load_dataset("financial_phrasebank", "sentences_allagree", trust_remote_code=True)
    fp.save_to_disk(f'{DATA_DIR}/fin_phrasebank')
    stats['fin_phrasebank'] = {'task': 'sentiment_finance', 'size': len(fp['train'])}
    print(f"  fin_phrasebank: {len(fp['train'])}")
except Exception as e:
    print(f"  fin_phrasebank HATA: {e}")

print("\nOzet:")
for k,v in stats.items(): print(f"  {k}: {v}")

write_status('data_downloaded', datasets=list(stats.keys()))
```

## CELL 4: Veri on isleme + birlestirme

```python
from datasets import load_from_disk, Dataset, concatenate_datasets
import re, html

# --- Tweet temizleyici ---
def clean_tweet(t):
    if not isinstance(t, str): return ""
    t = html.unescape(t)
    t = re.sub(r'http\S+|www\.\S+', ' [URL] ', t)
    t = re.sub(r'@\w+', '@user', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# Task -> label mapping (multi-head model icin)
# Sentiment: 0=negative, 1=neutral, 2=positive
# Emotion:   0=anger, 1=joy, 2=optimism, 3=sadness
# Stance:    0=against, 1=neutral, 2=for (bearish/neutral/bullish equivalent)
# Topic-fin: zeroshot/twitter-financial-news-topic'in kendi 20 sinifi

def build_unified():
    # Sentiment -- TweetEval(3) + FinancialPhraseBank(3) + FinNewsSentiment(3)
    sent_examples = []

    te_s = load_from_disk(f'{DATA_DIR}/te_sentiment')
    for split in ['train','validation','test']:
        if split in te_s:
            for x in te_s[split]:
                sent_examples.append({'text': clean_tweet(x['text']),
                                      'label': x['label'], 'split': split, 'src':'te_sent'})

    fin_s = load_from_disk(f'{DATA_DIR}/fin_sentiment')
    # zeroshot label map: 0=Bearish, 1=Bullish, 2=Neutral -> remap to negative/neutral/positive
    fin_remap = {0:0, 1:2, 2:1}
    for split in ['train','validation','test']:
        if split in fin_s:
            tag = 'train' if split=='train' else ('test' if split in ('validation','test') else 'train')
            for x in fin_s[split]:
                sent_examples.append({'text': clean_tweet(x['text']),
                                      'label': fin_remap[x['label']],
                                      'split': tag, 'src':'fin_sent'})

    try:
        fp = load_from_disk(f'{DATA_DIR}/fin_phrasebank')
        # phrasebank: 0=neg,1=neutral,2=pos
        for x in fp['train']:
            sent_examples.append({'text': clean_tweet(x['sentence']),
                                  'label': x['label'], 'split': 'train', 'src':'phrasebank'})
    except Exception as e:
        print(f"phrasebank skipped: {e}")

    return sent_examples

sent_examples = build_unified()
print(f"Sentiment ornek sayisi: {len(sent_examples)}")
print(f"Etiket dagilimi: {Counter(x['label'] for x in sent_examples)}")

# DataFrame uzerinden train/validation ayrimi
df = pd.DataFrame(sent_examples)
train_df = df[df['split']=='train'].sample(frac=1, random_state=42).reset_index(drop=True)
test_df  = df[df['split'].isin(['validation','test'])].sample(frac=1, random_state=42).reset_index(drop=True)
print(f"\nTrain={len(train_df)}, Test={len(test_df)}")

train_ds = Dataset.from_pandas(train_df[['text','label']])
test_ds  = Dataset.from_pandas(test_df[['text','label']])

train_ds.save_to_disk(f'{DATA_DIR}/unified_sentiment_train')
test_ds.save_to_disk(f'{DATA_DIR}/unified_sentiment_test')

# Topic ve emotion'u da hazirla (ayri dataset)
te_e = load_from_disk(f'{DATA_DIR}/te_emotion')
emotion_train = te_e['train'].map(lambda x: {'text': clean_tweet(x['text']), 'label': x['label']})
emotion_test  = te_e['test'].map(lambda x: {'text': clean_tweet(x['text']), 'label': x['label']})
emotion_train.save_to_disk(f'{DATA_DIR}/emotion_train')
emotion_test.save_to_disk(f'{DATA_DIR}/emotion_test')
print(f"\nEmotion train={len(emotion_train)}, test={len(emotion_test)}")

fin_t = load_from_disk(f'{DATA_DIR}/fin_topic')
topic_train = fin_t['train'].map(lambda x: {'text': clean_tweet(x['text']), 'label': x['label']})
topic_test  = fin_t['validation'].map(lambda x: {'text': clean_tweet(x['text']), 'label': x['label']})
topic_train.save_to_disk(f'{DATA_DIR}/topic_train')
topic_test.save_to_disk(f'{DATA_DIR}/topic_test')
print(f"Topic train={len(topic_train)}, test={len(topic_test)}")

NUM_TOPIC_CLASSES = len(set(topic_train['label']))
print(f"Topic siniflar: {NUM_TOPIC_CLASSES}")

write_status('data_prepared',
             sentiment_train=len(train_ds), sentiment_test=len(test_ds),
             emotion_train=len(emotion_train), topic_train=len(topic_train),
             topic_classes=NUM_TOPIC_CLASSES)
```

## CELL 5: Model + Tokenizer (multi-head)

```python
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel, AutoConfig

BASE_MODEL = 'cardiffnlp/twitter-roberta-base-sentiment-latest'

print(f"Tokenizer ve base model yukleniyor: {BASE_MODEL}")
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
config = AutoConfig.from_pretrained(BASE_MODEL)

# Multi-head model
class ShowMeMultiTaskModel(nn.Module):
    def __init__(self, base_model_name, n_sentiment=3, n_emotion=4, n_topic=20):
        super().__init__()
        self.backbone = AutoModel.from_pretrained(base_model_name)
        h = self.backbone.config.hidden_size
        self.sent_head    = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, n_sentiment))
        self.emotion_head = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, n_emotion))
        self.topic_head   = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, n_topic))
        self.n_sentiment, self.n_emotion, self.n_topic = n_sentiment, n_emotion, n_topic

    def forward(self, input_ids, attention_mask, task='sentiment', labels=None):
        out = self.backbone(input_ids=input_ids, attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0]
        if task == 'sentiment':  logits = self.sent_head(cls)
        elif task == 'emotion':  logits = self.emotion_head(cls)
        elif task == 'topic':    logits = self.topic_head(cls)
        else: raise ValueError(f"unknown task {task}")
        loss = None
        if labels is not None:
            loss = nn.functional.cross_entropy(logits, labels)
        return {'loss': loss, 'logits': logits}

model = ShowMeMultiTaskModel(BASE_MODEL, n_sentiment=3, n_emotion=4, n_topic=NUM_TOPIC_CLASSES)
model = model.to('cuda' if torch.cuda.is_available() else 'cpu')
n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"Egitilebilir parametre: {n_params/1e6:.1f}M")

write_status('model_built', params_M=round(n_params/1e6, 1), base=BASE_MODEL)
```

## CELL 6: Egitim donguusu (multi-task)

```python
import torch, time, json, math, random
from torch.utils.data import DataLoader, Dataset as TDataset
from torch.optim import AdamW
from transformers import get_linear_schedule_with_warmup
from datasets import load_from_disk
from sklearn.metrics import f1_score, accuracy_score
import numpy as np
random.seed(42); np.random.seed(42); torch.manual_seed(42)

MAX_LEN = 128
EPOCHS = 4
LR = 2e-5
WARMUP_RATIO = 0.06
GRAD_ACC = 1
EVAL_EVERY_STEPS = 200
TASK_WEIGHTS = {'sentiment': 1.0, 'emotion': 0.7, 'topic': 0.9}

# tokenize helper
def tok(batch_texts, max_len=MAX_LEN):
    return tokenizer(batch_texts, truncation=True, padding='max_length',
                     max_length=max_len, return_tensors='pt')

# Custom torch dataset
class TaskDS(TDataset):
    def __init__(self, hf_ds, task):
        self.texts  = list(hf_ds['text'])
        self.labels = list(hf_ds['label'])
        self.task = task
    def __len__(self): return len(self.texts)
    def __getitem__(self, i):
        return {'text': self.texts[i], 'label': self.labels[i], 'task': self.task}

def collate(batch):
    texts = [b['text'] for b in batch]
    labels = torch.tensor([b['label'] for b in batch], dtype=torch.long)
    enc = tok(texts)
    return {'input_ids': enc['input_ids'], 'attention_mask': enc['attention_mask'],
            'labels': labels, 'task': batch[0]['task']}

train_sent = TaskDS(load_from_disk(f'{DATA_DIR}/unified_sentiment_train'), 'sentiment')
test_sent  = TaskDS(load_from_disk(f'{DATA_DIR}/unified_sentiment_test'),  'sentiment')
train_emo  = TaskDS(load_from_disk(f'{DATA_DIR}/emotion_train'), 'emotion')
test_emo   = TaskDS(load_from_disk(f'{DATA_DIR}/emotion_test'),  'emotion')
train_top  = TaskDS(load_from_disk(f'{DATA_DIR}/topic_train'), 'topic')
test_top   = TaskDS(load_from_disk(f'{DATA_DIR}/topic_test'),  'topic')

dl_sent = DataLoader(train_sent, batch_size=BATCH, shuffle=True, collate_fn=collate, num_workers=2)
dl_emo  = DataLoader(train_emo,  batch_size=BATCH, shuffle=True, collate_fn=collate, num_workers=2)
dl_top  = DataLoader(train_top,  batch_size=BATCH, shuffle=True, collate_fn=collate, num_workers=2)
dl_test_sent = DataLoader(test_sent, batch_size=BATCH, shuffle=False, collate_fn=collate)
dl_test_emo  = DataLoader(test_emo,  batch_size=BATCH, shuffle=False, collate_fn=collate)
dl_test_top  = DataLoader(test_top,  batch_size=BATCH, shuffle=False, collate_fn=collate)

steps_per_epoch = max(len(dl_sent), len(dl_emo), len(dl_top))
total_steps = steps_per_epoch * EPOCHS
optim = AdamW(model.parameters(), lr=LR, weight_decay=0.01)
sched = get_linear_schedule_with_warmup(optim, int(total_steps*WARMUP_RATIO), total_steps)

device = 'cuda' if torch.cuda.is_available() else 'cpu'
scaler = torch.cuda.amp.GradScaler()

def eval_task(dl, task):
    model.eval()
    preds, labels = [], []
    with torch.no_grad():
        for b in dl:
            ids = b['input_ids'].to(device); mask = b['attention_mask'].to(device); lab = b['labels'].to(device)
            with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                out = model(ids, mask, task=task)
            preds.extend(out['logits'].argmax(-1).cpu().tolist())
            labels.extend(lab.cpu().tolist())
    acc = accuracy_score(labels, preds)
    f1m = f1_score(labels, preds, average='macro')
    return {'acc': acc, 'f1_macro': f1m}

best_score = 0.0
log = []
step_global = 0
t0 = time.time()
print(f"Egitim basliyor. total_steps={total_steps}, batch={BATCH}, epochs={EPOCHS}")
write_status('training_started', total_steps=total_steps, batch=BATCH, epochs=EPOCHS, lr=LR)

for epoch in range(EPOCHS):
    iters = {'sentiment': iter(dl_sent), 'emotion': iter(dl_emo), 'topic': iter(dl_top)}
    model.train()
    epoch_losses = []
    for step in range(steps_per_epoch):
        # round-robin task secimi
        for task in ['sentiment','emotion','topic']:
            try:
                b = next(iters[task])
            except StopIteration:
                if task == 'emotion':  iters['emotion'] = iter(dl_emo); b = next(iters['emotion'])
                elif task == 'topic':  iters['topic']   = iter(dl_top); b = next(iters['topic'])
                else: continue
            ids = b['input_ids'].to(device); mask = b['attention_mask'].to(device); lab = b['labels'].to(device)
            with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                out = model(ids, mask, task=task, labels=lab)
                loss = out['loss'] * TASK_WEIGHTS[task]
            scaler.scale(loss).backward()
            epoch_losses.append((task, loss.item()))
        scaler.unscale_(optim)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optim)
        scaler.update()
        optim.zero_grad()
        sched.step()
        step_global += 1

        if step_global % 50 == 0:
            recent = epoch_losses[-30:]
            avg_loss = sum(l for _,l in recent)/len(recent)
            elapsed = time.time() - t0
            eta = elapsed / step_global * (total_steps - step_global) if step_global else 0
            print(f"  ep{epoch} step{step}/{steps_per_epoch} loss={avg_loss:.4f} lr={sched.get_last_lr()[0]:.2e} ETA={eta/60:.1f}min")
            write_status('training_running', epoch=epoch, step_global=step_global,
                         total_steps=total_steps, avg_loss=round(avg_loss,4),
                         elapsed_min=round(elapsed/60,1), eta_min=round(eta/60,1))

        if step_global % EVAL_EVERY_STEPS == 0:
            es = eval_task(dl_test_sent, 'sentiment')
            ee = eval_task(dl_test_emo,  'emotion')
            et = eval_task(dl_test_top,  'topic')
            avg_f1 = (es['f1_macro']+ee['f1_macro']+et['f1_macro'])/3
            print(f"   EVAL sent={es} emo={ee} topic={et}  avgF1={avg_f1:.4f}")
            log.append({'step': step_global, 'sent': es, 'emotion': ee, 'topic': et, 'avg_f1': avg_f1})
            with open(f'{LOG_DIR}/eval_log.json','w') as f: json.dump(log, f, indent=2)
            if avg_f1 > best_score:
                best_score = avg_f1
                torch.save(model.state_dict(), f'{CHECKPOINT_DIR}/best.pt')
                tokenizer.save_pretrained(f'{CHECKPOINT_DIR}/tokenizer')
                print(f"   ** BEST: avg_f1={best_score:.4f} kaydedildi **")
                write_status('best_checkpoint', avg_f1=round(best_score,4),
                             sent_f1=round(es['f1_macro'],4),
                             emo_f1=round(ee['f1_macro'],4),
                             topic_f1=round(et['f1_macro'],4))
            model.train()

print(f"\nEgitim bitti. Sure: {(time.time()-t0)/60:.1f} dk. Best avgF1: {best_score:.4f}")
write_status('training_done', best_avg_f1=round(best_score,4),
             total_min=round((time.time()-t0)/60,1))
```

## CELL 7: Final degerlendirme ve kalite kontrolu

```python
# Best checkpoint'i geri yukle
model.load_state_dict(torch.load(f'{CHECKPOINT_DIR}/best.pt', map_location=device))
model.eval()

print("Final degerlendirme...")
final_sent  = eval_task(dl_test_sent, 'sentiment')
final_emo   = eval_task(dl_test_emo,  'emotion')
final_topic = eval_task(dl_test_top,  'topic')

print(f"\nSentiment: acc={final_sent['acc']:.4f}  f1_macro={final_sent['f1_macro']:.4f}")
print(f"Emotion  : acc={final_emo['acc']:.4f}  f1_macro={final_emo['f1_macro']:.4f}")
print(f"Topic    : acc={final_topic['acc']:.4f}  f1_macro={final_topic['f1_macro']:.4f}")

# Kalite esikleri (hepsi gecmesi gerek)
THRESHOLDS = {'sentiment_f1': 0.65, 'emotion_f1': 0.70, 'topic_f1': 0.75}
ok_s = final_sent['f1_macro']  >= THRESHOLDS['sentiment_f1']
ok_e = final_emo['f1_macro']   >= THRESHOLDS['emotion_f1']
ok_t = final_topic['f1_macro'] >= THRESHOLDS['topic_f1']
all_ok = ok_s and ok_e and ok_t

print(f"\nEsik kontrol: sent={ok_s} emo={ok_e} topic={ok_t}  ALL_PASS={all_ok}")
write_status('final_eval',
             sentiment=final_sent, emotion=final_emo, topic=final_topic,
             thresholds=THRESHOLDS, passed=all_ok)
```

## CELL 8: Modeli kaydet (Drive)

```python
import json, shutil

FINAL_DIR = f'{MODEL_DIR}/showme_x_v1'
os.makedirs(FINAL_DIR, exist_ok=True)

# Backbone'u standart HF formatinda kaydet
model.backbone.save_pretrained(f'{FINAL_DIR}/backbone')
tokenizer.save_pretrained(f'{FINAL_DIR}/tokenizer')

# Head'leri ayri kaydet
torch.save({
    'sent_head': model.sent_head.state_dict(),
    'emotion_head': model.emotion_head.state_dict(),
    'topic_head': model.topic_head.state_dict(),
    'meta': {
        'base_model': BASE_MODEL,
        'n_sentiment': model.n_sentiment,
        'n_emotion': model.n_emotion,
        'n_topic': model.n_topic,
        'final_eval': {'sentiment': final_sent, 'emotion': final_emo, 'topic': final_topic},
        'best_avg_f1': best_score,
        'thresholds_passed': all_ok,
    }
}, f'{FINAL_DIR}/heads.pt')

# Etiket isimleri
LABEL_MAPS = {
    'sentiment': {0:'negative', 1:'neutral', 2:'positive'},
    'emotion':   {0:'anger', 1:'joy', 2:'optimism', 3:'sadness'},
    'topic':     None,  # zeroshot/twitter-financial-news-topic'in 20 sinifi
}
# Topic etiketlerini orijinal datasetten oku
try:
    fin_t = load_from_disk(f'{DATA_DIR}/fin_topic')
    if hasattr(fin_t['train'].features['label'], 'names'):
        LABEL_MAPS['topic'] = {i: n for i,n in enumerate(fin_t['train'].features['label'].names)}
except Exception as e:
    print(f"topic label mapping error: {e}")

with open(f'{FINAL_DIR}/label_maps.json','w') as f:
    json.dump(LABEL_MAPS, f, indent=2, ensure_ascii=False)

# Inference helper module
inference_code = '''import torch, json
import torch.nn as nn
from pathlib import Path
from transformers import AutoTokenizer, AutoModel

class ShowMeXAnalyzer:
    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir/"tokenizer"))
        self.backbone  = AutoModel.from_pretrained(str(model_dir/"backbone"))
        ckpt = torch.load(str(model_dir/"heads.pt"), map_location="cpu")
        meta = ckpt["meta"]
        h = self.backbone.config.hidden_size
        self.sent_head = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_sentiment"]))
        self.emo_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_emotion"]))
        self.top_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_topic"]))
        self.sent_head.load_state_dict(ckpt["sent_head"])
        self.emo_head.load_state_dict(ckpt["emotion_head"])
        self.top_head.load_state_dict(ckpt["topic_head"])
        self.label_maps = json.load(open(str(model_dir/"label_maps.json")))
        self.meta = meta
        for m in [self.backbone, self.sent_head, self.emo_head, self.top_head]:
            m.eval()

    @torch.no_grad()
    def analyze(self, texts, max_len=128):
        if isinstance(texts, str): texts = [texts]
        enc = self.tokenizer(texts, truncation=True, padding=True,
                             max_length=max_len, return_tensors="pt")
        out = self.backbone(**enc)
        cls = out.last_hidden_state[:, 0]
        s = torch.softmax(self.sent_head(cls), -1)
        e = torch.softmax(self.emo_head(cls), -1)
        t = torch.softmax(self.top_head(cls), -1)
        results = []
        for i, text in enumerate(texts):
            si = int(s[i].argmax()); ei = int(e[i].argmax()); ti = int(t[i].argmax())
            results.append({
                "text": text,
                "sentiment": {"label": self.label_maps["sentiment"][str(si)] if str(si) in self.label_maps["sentiment"] else self.label_maps["sentiment"][si],
                               "score": float(s[i,si]),
                               "probs": [float(p) for p in s[i].tolist()]},
                "emotion": {"label": self.label_maps["emotion"][str(ei)] if str(ei) in self.label_maps["emotion"] else self.label_maps["emotion"][ei],
                            "score": float(e[i,ei]),
                            "probs": [float(p) for p in e[i].tolist()]},
                "topic": {"index": ti,
                          "label": (self.label_maps["topic"][str(ti)] if self.label_maps["topic"] and str(ti) in self.label_maps["topic"] else None),
                          "score": float(t[i,ti])},
            })
        return results
'''
with open(f'{FINAL_DIR}/inference.py','w') as f:
    f.write(inference_code)

# README
readme = f"""# showMe X Scraper AI - v1

Multi-task Twitter analiz modeli (sentiment + emotion + topic).

## Sonuclar
- Sentiment F1 (macro): {final_sent['f1_macro']:.4f}, Acc: {final_sent['acc']:.4f}
- Emotion   F1 (macro): {final_emo['f1_macro']:.4f}, Acc: {final_emo['acc']:.4f}
- Topic     F1 (macro): {final_topic['f1_macro']:.4f}, Acc: {final_topic['acc']:.4f}
- Best avg F1 (training): {best_score:.4f}
- All thresholds passed: {all_ok}

## Base
- {BASE_MODEL}

## Kullanim
```python
from inference import ShowMeXAnalyzer
m = ShowMeXAnalyzer("./")
print(m.analyze("AAPL just blew earnings out of the water"))
```
"""
with open(f'{FINAL_DIR}/README.md','w') as f:
    f.write(readme)

print(f"\nFinal model: {FINAL_DIR}")
print("Icerik:")
for p in Path(FINAL_DIR).rglob('*'):
    if p.is_file(): print(f"  {p.relative_to(FINAL_DIR)}  ({p.stat().st_size/1024:.1f}KB)")

write_status('model_saved', model_dir=FINAL_DIR, all_thresholds_passed=all_ok)
```

## CELL 9: Hizli sanity test

```python
import sys
sys.path.insert(0, FINAL_DIR)
import importlib
if 'inference' in sys.modules: importlib.reload(sys.modules['inference'])
from inference import ShowMeXAnalyzer

m = ShowMeXAnalyzer(FINAL_DIR)
samples = [
    "$TSLA earnings crushed expectations, going to the moon!",
    "Disappointing quarter for $AMZN, may need to reconsider my position",
    "Market is calm today, nothing exciting happening on $SPY",
    "Federal Reserve hints at rate cuts later this year",
    "Crypto winter is officially over, $BTC breaking resistance",
]
results = m.analyze(samples)
for r in results:
    print(f"\n{r['text']}")
    print(f"  Sent : {r['sentiment']['label']:>9}  ({r['sentiment']['score']:.2f})")
    print(f"  Emot : {r['emotion']['label']:>9}  ({r['emotion']['score']:.2f})")
    print(f"  Topic: {r['topic']['label']!r:>9} ({r['topic']['score']:.2f})")

write_status('sanity_test_done', samples=len(samples))
```
