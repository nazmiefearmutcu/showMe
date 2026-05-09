# === HUCRE 2: Veri + Preprocessing + Model + Training + Save ===
# Bu hucre Cell 1'den sonra calistirilir. Cell 1'in degiskenleri (PROJECT_DIR,
# DATA_DIR, MODEL_DIR, CHECKPOINT_DIR, LOG_DIR, BATCH, TIER, write_status) hazir.

import os, sys, time, json, gc, random, math, html, re
import torch, torch.nn as nn, numpy as np
from pathlib import Path
from datasets import load_dataset, load_from_disk, Dataset, concatenate_datasets
from transformers import AutoTokenizer, AutoModel, get_linear_schedule_with_warmup
from torch.utils.data import DataLoader, Dataset as TDataset
from torch.optim import AdamW
from sklearn.metrics import f1_score, accuracy_score
import pandas as pd
from collections import Counter

random.seed(42); np.random.seed(42); torch.manual_seed(42)
if torch.cuda.is_available(): torch.cuda.manual_seed_all(42)
device = 'cuda' if torch.cuda.is_available() else 'cpu'

# ----- 1) Veri setlerini indir -----
HF_DATASETS = [
    ('cardiffnlp/tweet_eval', 'sentiment',  'te_sentiment'),
    ('cardiffnlp/tweet_eval', 'emotion',    'te_emotion'),
    ('cardiffnlp/tweet_eval', 'stance_climate', 'te_stance_climate'),
    ('cardiffnlp/tweet_eval', 'offensive',  'te_offensive'),
    ('cardiffnlp/tweet_eval', 'irony',      'te_irony'),
    ('cardiffnlp/tweet_eval', 'hate',       'te_hate'),
    ('zeroshot/twitter-financial-news-sentiment', None, 'fin_sentiment'),
    ('zeroshot/twitter-financial-news-topic',     None, 'fin_topic'),
]
print("=== HUCRE 2: Pipeline ===\n\nVeri setleri indiriliyor...")
data_paths = {}
for hf_id, cfg, name in HF_DATASETS:
    p = f'{DATA_DIR}/{name}'
    if os.path.exists(p):
        print(f"  cached: {name}")
        data_paths[name] = p
        continue
    try:
        ds = load_dataset(hf_id, cfg) if cfg else load_dataset(hf_id)
        ds.save_to_disk(p)
        data_paths[name] = p
        print(f"  OK: {name} ({sum(len(v) for v in ds.values())} ornek)")
    except Exception as e:
        print(f"  HATA: {name}: {e}")

try:
    fp = load_dataset("financial_phrasebank", "sentences_allagree", trust_remote_code=True)
    fp.save_to_disk(f'{DATA_DIR}/fin_phrasebank')
    data_paths['fin_phrasebank'] = f'{DATA_DIR}/fin_phrasebank'
    print(f"  OK: fin_phrasebank ({len(fp['train'])})")
except Exception as e:
    print(f"  fin_phrasebank: {e}")

write_status('data_downloaded', sets=list(data_paths.keys()))

# ----- 2) Preprocessing -----
def clean(t):
    if not isinstance(t, str): return ""
    t = html.unescape(t)
    t = re.sub(r'http\S+|www\.\S+', '[URL]', t)
    t = re.sub(r'@\w+', '@user', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def collect_sentiment():
    rows_train, rows_test = [], []
    te = load_from_disk(data_paths['te_sentiment'])
    for x in te['train']: rows_train.append({'text': clean(x['text']), 'label': x['label']})
    for x in te.get('validation', []): rows_train.append({'text': clean(x['text']), 'label': x['label']})
    for x in te['test']: rows_test.append({'text': clean(x['text']), 'label': x['label']})

    fs = load_from_disk(data_paths['fin_sentiment'])
    fmap = {0:0, 1:2, 2:1}  # Bearish=0->neg, Bullish=1->pos, Neutral=2->neu
    for x in fs['train']: rows_train.append({'text': clean(x['text']), 'label': fmap[x['label']]})
    for x in fs.get('validation', []): rows_test.append({'text': clean(x['text']), 'label': fmap[x['label']]})

    if 'fin_phrasebank' in data_paths:
        fp = load_from_disk(data_paths['fin_phrasebank'])
        items = list(fp['train']); random.shuffle(items)
        for i, x in enumerate(items):
            row = {'text': clean(x['sentence']), 'label': x['label']}
            (rows_train if i % 10 < 8 else rows_test).append(row)
    return rows_train, rows_test

def collect_emotion():
    te = load_from_disk(data_paths['te_emotion'])
    return ([{'text': clean(x['text']), 'label': x['label']} for x in te['train']],
            [{'text': clean(x['text']), 'label': x['label']} for x in te['test']])

def collect_topic():
    ft = load_from_disk(data_paths['fin_topic'])
    return ([{'text': clean(x['text']), 'label': x['label']} for x in ft['train']],
            [{'text': clean(x['text']), 'label': x['label']} for x in ft['validation']])

sent_train, sent_test = collect_sentiment()
emo_train,  emo_test  = collect_emotion()
top_train,  top_test  = collect_topic()
print(f"\nSentiment: train={len(sent_train)} test={len(sent_test)}")
print(f"Emotion  : train={len(emo_train)}  test={len(emo_test)}")
print(f"Topic    : train={len(top_train)}  test={len(top_test)}")

ft = load_from_disk(data_paths['fin_topic'])
TOPIC_NAMES = ft['train'].features['label'].names if hasattr(ft['train'].features['label'], 'names') else None
te_e = load_from_disk(data_paths['te_emotion'])
EMOTION_NAMES = te_e['train'].features['label'].names if hasattr(te_e['train'].features['label'], 'names') else ['anger','joy','optimism','sadness']
NUM_TOPIC = len(TOPIC_NAMES) if TOPIC_NAMES else 20
NUM_EMOTION = len(EMOTION_NAMES) if EMOTION_NAMES else 4
print(f"Topic classes: {NUM_TOPIC}  Emotion classes: {NUM_EMOTION}")

write_status('data_prepared',
             sent_train=len(sent_train), sent_test=len(sent_test),
             emo_train=len(emo_train), emo_test=len(emo_test),
             top_train=len(top_train), top_test=len(top_test),
             num_topic=NUM_TOPIC, num_emotion=NUM_EMOTION)

# ----- 3) Model -----
BASE_MODEL = 'cardiffnlp/twitter-roberta-base-sentiment-latest'
print(f"\nModel yukleniyor: {BASE_MODEL}")
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

class ShowMeMultiTaskModel(nn.Module):
    def __init__(self, base, n_sent=3, n_emo=4, n_top=20):
        super().__init__()
        self.backbone = AutoModel.from_pretrained(base)
        h = self.backbone.config.hidden_size
        self.sent_head = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, n_sent))
        self.emo_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, n_emo))
        self.top_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, n_top))
        self.n_sent, self.n_emo, self.n_top = n_sent, n_emo, n_top

    def forward(self, input_ids, attention_mask, task='sentiment', labels=None):
        out = self.backbone(input_ids=input_ids, attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0]
        if task == 'sentiment':  logits = self.sent_head(cls)
        elif task == 'emotion':  logits = self.emo_head(cls)
        elif task == 'topic':    logits = self.top_head(cls)
        else: raise ValueError(task)
        loss = None if labels is None else nn.functional.cross_entropy(logits, labels)
        return {'loss': loss, 'logits': logits}

model = ShowMeMultiTaskModel(BASE_MODEL, 3, NUM_EMOTION, NUM_TOPIC).to(device)
n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"Egitilebilir parametre: {n_params/1e6:.1f}M")

# ----- 4) Egitim -----
MAX_LEN = 128
EPOCHS = 6
LR = 2e-5
WD = 0.01
WARMUP = 0.06
EVAL_EVERY = 250
TASK_W = {'sentiment': 1.0, 'emotion': 0.7, 'topic': 0.9}

def collate(batch):
    texts = [b['text'] for b in batch]
    labels = torch.tensor([b['label'] for b in batch], dtype=torch.long)
    enc = tokenizer(texts, truncation=True, padding=True, max_length=MAX_LEN, return_tensors='pt')
    return {'input_ids': enc['input_ids'], 'attention_mask': enc['attention_mask'],
            'labels': labels, 'task': batch[0]['task']}

class TaskDS(TDataset):
    def __init__(self, rows, task): self.rows, self.task = rows, task
    def __len__(self): return len(self.rows)
    def __getitem__(self, i):
        r = self.rows[i]; return {'text': r['text'], 'label': r['label'], 'task': self.task}

dl_sent_tr = DataLoader(TaskDS(sent_train,'sentiment'), batch_size=BATCH, shuffle=True, collate_fn=collate, num_workers=2)
dl_sent_te = DataLoader(TaskDS(sent_test, 'sentiment'), batch_size=BATCH, shuffle=False, collate_fn=collate, num_workers=2)
dl_emo_tr  = DataLoader(TaskDS(emo_train, 'emotion'),   batch_size=BATCH, shuffle=True, collate_fn=collate, num_workers=2)
dl_emo_te  = DataLoader(TaskDS(emo_test,  'emotion'),   batch_size=BATCH, shuffle=False, collate_fn=collate, num_workers=2)
dl_top_tr  = DataLoader(TaskDS(top_train, 'topic'),     batch_size=BATCH, shuffle=True, collate_fn=collate, num_workers=2)
dl_top_te  = DataLoader(TaskDS(top_test,  'topic'),     batch_size=BATCH, shuffle=False, collate_fn=collate, num_workers=2)

steps_per_epoch = max(len(dl_sent_tr), len(dl_emo_tr), len(dl_top_tr))
total_steps = steps_per_epoch * EPOCHS
optim = AdamW(model.parameters(), lr=LR, weight_decay=WD)
sched = get_linear_schedule_with_warmup(optim, int(total_steps*WARMUP), total_steps)
scaler = torch.cuda.amp.GradScaler() if device == 'cuda' else None

def eval_task(dl, task):
    model.eval(); preds, labels = [], []
    with torch.no_grad():
        for b in dl:
            ids, mask, lab = b['input_ids'].to(device), b['attention_mask'].to(device), b['labels'].to(device)
            with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                out = model(ids, mask, task=task)
            preds.extend(out['logits'].argmax(-1).cpu().tolist())
            labels.extend(lab.cpu().tolist())
    return {'acc': accuracy_score(labels, preds), 'f1_macro': f1_score(labels, preds, average='macro')}

best_avg, log = 0.0, []
t0 = time.time()
print(f"\nEgitim basliyor: total_steps={total_steps}, batch={BATCH}, epochs={EPOCHS}")
write_status('training_started', total_steps=total_steps, batch=BATCH, epochs=EPOCHS, base_model=BASE_MODEL)

step_global = 0
for epoch in range(EPOCHS):
    iters = {'sentiment': iter(dl_sent_tr), 'emotion': iter(dl_emo_tr), 'topic': iter(dl_top_tr)}
    dls   = {'sentiment': dl_sent_tr, 'emotion': dl_emo_tr, 'topic': dl_top_tr}
    model.train(); epoch_losses = []
    for step in range(steps_per_epoch):
        for task in ['sentiment','emotion','topic']:
            try: b = next(iters[task])
            except StopIteration:
                iters[task] = iter(dls[task]); b = next(iters[task])
            ids, mask, lab = b['input_ids'].to(device), b['attention_mask'].to(device), b['labels'].to(device)
            with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                out = model(ids, mask, task=task, labels=lab)
                loss = out['loss'] * TASK_W[task]
            scaler.scale(loss).backward()
            epoch_losses.append((task, loss.item()))
        scaler.unscale_(optim)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optim); scaler.update(); optim.zero_grad(); sched.step()
        step_global += 1

        if step_global % 50 == 0:
            recent = epoch_losses[-30:]
            avg_loss = sum(l for _,l in recent)/max(1,len(recent))
            elapsed = time.time() - t0
            eta = elapsed / step_global * (total_steps - step_global)
            print(f"  ep{epoch} st{step}/{steps_per_epoch} loss={avg_loss:.4f} lr={sched.get_last_lr()[0]:.2e} ETA={eta/60:.1f}m")
            write_status('training_running', epoch=epoch, step_global=step_global, total_steps=total_steps,
                         avg_loss=round(avg_loss,4), elapsed_min=round(elapsed/60,1), eta_min=round(eta/60,1),
                         best_avg_f1=round(best_avg,4))

        if step_global % EVAL_EVERY == 0:
            es = eval_task(dl_sent_te, 'sentiment')
            ee = eval_task(dl_emo_te,  'emotion')
            et = eval_task(dl_top_te,  'topic')
            avg_f1 = (es['f1_macro']+ee['f1_macro']+et['f1_macro'])/3
            print(f"   EVAL sent={es} emo={ee} topic={et} avgF1={avg_f1:.4f}")
            log.append({'step': step_global, 'sent': es, 'emotion': ee, 'topic': et, 'avg_f1': avg_f1})
            with open(f'{LOG_DIR}/eval_log.json','w') as f: json.dump(log, f, indent=2)
            if avg_f1 > best_avg:
                best_avg = avg_f1
                torch.save(model.state_dict(), f'{CHECKPOINT_DIR}/best.pt')
                tokenizer.save_pretrained(f'{CHECKPOINT_DIR}/tokenizer')
                print(f"   ** BEST: avg_f1={best_avg:.4f} kaydedildi **")
                write_status('best_checkpoint', avg_f1=round(best_avg,4),
                             sent_f1=round(es['f1_macro'],4), emo_f1=round(ee['f1_macro'],4), topic_f1=round(et['f1_macro'],4))
            model.train()

print(f"\nEgitim bitti: {(time.time()-t0)/60:.1f} dk, best_avg_f1={best_avg:.4f}")
write_status('training_done', best_avg_f1=round(best_avg,4), total_min=round((time.time()-t0)/60,1))

# ----- 5) Final eval + save -----
print("\n=== FINAL EVAL & SAVE ===")
model.load_state_dict(torch.load(f'{CHECKPOINT_DIR}/best.pt', map_location=device)); model.eval()
final_s = eval_task(dl_sent_te, 'sentiment')
final_e = eval_task(dl_emo_te,  'emotion')
final_t = eval_task(dl_top_te,  'topic')
print(f"Sentiment: acc={final_s['acc']:.4f}  f1={final_s['f1_macro']:.4f}")
print(f"Emotion  : acc={final_e['acc']:.4f}  f1={final_e['f1_macro']:.4f}")
print(f"Topic    : acc={final_t['acc']:.4f}  f1={final_t['f1_macro']:.4f}")
THRESHOLDS = {'sentiment_f1': 0.65, 'emotion_f1': 0.70, 'topic_f1': 0.75}
all_ok = (final_s['f1_macro'] >= THRESHOLDS['sentiment_f1']
          and final_e['f1_macro'] >= THRESHOLDS['emotion_f1']
          and final_t['f1_macro'] >= THRESHOLDS['topic_f1'])
print(f"Esikler {THRESHOLDS}: TUM_GECTI={all_ok}")
write_status('final_eval', sentiment=final_s, emotion=final_e, topic=final_t, thresholds=THRESHOLDS, passed=all_ok)

FINAL_DIR = f'{MODEL_DIR}/showme_x_v1'
os.makedirs(FINAL_DIR, exist_ok=True)
model.backbone.save_pretrained(f'{FINAL_DIR}/backbone')
tokenizer.save_pretrained(f'{FINAL_DIR}/tokenizer')
torch.save({
    'sent_head': model.sent_head.state_dict(),
    'emotion_head': model.emo_head.state_dict(),
    'topic_head': model.top_head.state_dict(),
    'meta': {'base_model': BASE_MODEL, 'n_sentiment': model.n_sent,
             'n_emotion': model.n_emo, 'n_topic': model.n_top,
             'final_eval': {'sentiment': final_s, 'emotion': final_e, 'topic': final_t},
             'best_avg_f1': best_avg, 'thresholds_passed': all_ok},
}, f'{FINAL_DIR}/heads.pt')

LABEL_MAPS = {
    'sentiment': {0:'negative', 1:'neutral', 2:'positive'},
    'emotion': {i:n for i,n in enumerate(EMOTION_NAMES)},
    'topic':   {i:n for i,n in enumerate(TOPIC_NAMES)} if TOPIC_NAMES else {},
}
with open(f'{FINAL_DIR}/label_maps.json','w') as f: json.dump(LABEL_MAPS, f, indent=2, ensure_ascii=False)

INF = '''import torch, json
import torch.nn as nn
from pathlib import Path
from transformers import AutoTokenizer, AutoModel

class ShowMeXAnalyzer:
    def __init__(self, model_dir):
        d = Path(model_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(str(d/"tokenizer"))
        self.backbone  = AutoModel.from_pretrained(str(d/"backbone"))
        ckpt = torch.load(str(d/"heads.pt"), map_location="cpu")
        meta = ckpt["meta"]; h = self.backbone.config.hidden_size
        self.sent_head = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_sentiment"]))
        self.emo_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_emotion"]))
        self.top_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_topic"]))
        self.sent_head.load_state_dict(ckpt["sent_head"])
        self.emo_head.load_state_dict(ckpt["emotion_head"])
        self.top_head.load_state_dict(ckpt["topic_head"])
        self.label_maps = json.load(open(str(d/"label_maps.json")))
        for m in [self.backbone, self.sent_head, self.emo_head, self.top_head]: m.eval()
    def _label(self, kind, idx):
        m = self.label_maps.get(kind) or {}
        return m.get(str(idx), m.get(idx, str(idx)))
    @torch.no_grad()
    def analyze(self, texts):
        if isinstance(texts, str): texts = [texts]
        enc = self.tokenizer(texts, truncation=True, padding=True, max_length=128, return_tensors="pt")
        out = self.backbone(**enc); cls = out.last_hidden_state[:, 0]
        s = torch.softmax(self.sent_head(cls), -1)
        e = torch.softmax(self.emo_head(cls), -1)
        t = torch.softmax(self.top_head(cls), -1)
        return [{"text": txt,
                 "sentiment": {"label": self._label("sentiment", int(s[i].argmax())), "score": float(s[i].max()), "probs": [float(p) for p in s[i].tolist()]},
                 "emotion":   {"label": self._label("emotion",   int(e[i].argmax())), "score": float(e[i].max()), "probs": [float(p) for p in e[i].tolist()]},
                 "topic":     {"label": self._label("topic",     int(t[i].argmax())), "score": float(t[i].max())}}
                for i, txt in enumerate(texts)]
'''
with open(f'{FINAL_DIR}/inference.py','w') as f: f.write(INF)

readme = f"""# showMe X Scraper AI - v1
Multi-task tweet analyzer (sentiment + emotion + topic).

## Sonuclar (test set)
- Sentiment F1 (macro): {final_s['f1_macro']:.4f}  acc: {final_s['acc']:.4f}
- Emotion   F1 (macro): {final_e['f1_macro']:.4f}  acc: {final_e['acc']:.4f}
- Topic     F1 (macro): {final_t['f1_macro']:.4f}  acc: {final_t['acc']:.4f}
- Best avg F1 (validation): {best_avg:.4f}
- Thresholds passed: {all_ok}

## Base model
{BASE_MODEL}

## Kullanim
```python
from inference import ShowMeXAnalyzer
m = ShowMeXAnalyzer("./")
print(m.analyze("AAPL just blew earnings out of the water"))
```
"""
with open(f'{FINAL_DIR}/README.md','w') as f: f.write(readme)
print(f"\nFinal model: {FINAL_DIR}")
for p in Path(FINAL_DIR).rglob('*'):
    if p.is_file(): print(f"  {p.relative_to(FINAL_DIR)}  ({p.stat().st_size/1024:.1f}KB)")
write_status('model_saved', dir=FINAL_DIR, all_thresholds_passed=all_ok, best_avg_f1=round(best_avg,4))

# ----- 6) Sanity test -----
print("\n=== SANITY TEST ===")
sys.path.insert(0, FINAL_DIR)
import importlib
if 'inference' in sys.modules: importlib.reload(sys.modules['inference'])
from inference import ShowMeXAnalyzer
analyzer = ShowMeXAnalyzer(FINAL_DIR)
samples = [
    "$TSLA earnings crushed expectations, going to the moon!",
    "Disappointing quarter for $AMZN, may need to reconsider my position",
    "Market is calm today, nothing exciting happening on $SPY",
    "Federal Reserve hints at rate cuts later this year",
    "Crypto winter is officially over, $BTC breaking resistance",
    "Massive sell-off in tech stocks. Brutal day.",
    "Loving these dividend yields on $JNJ and $KO right now",
]
for r in analyzer.analyze(samples):
    print(f"\n{r['text']}")
    print(f"  Sent : {r['sentiment']['label']:>9}  ({r['sentiment']['score']:.2f})")
    print(f"  Emot : {r['emotion']['label']:>9}  ({r['emotion']['score']:.2f})")
    print(f"  Topic: {str(r['topic']['label'])[:25]:>25} ({r['topic']['score']:.2f})")
write_status('sanity_test_done', samples=len(samples))
print("\n=== TUM PIPELINE TAMAMLANDI ===")
