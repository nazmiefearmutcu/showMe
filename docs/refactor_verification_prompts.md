# showMe — Refactor Doğrulama Prompt Ailesi

> Bu dosya **2026-05-09 yekpare-tek-ağaç refactor**'undan sonra coder AI ajanı
> üzerinden çalıştırılacak doğrulama promptlarını içerir. Her prompt
> bağımsızdır: önce P0'ı bir defa yapıştır (sürekli context), sonra P1 → P6'yı
> sırayla çalıştır. Her promptun başında ajanın hangi kabuk komutlarını
> çalıştıracağı, beklenen çıktı ve hata durumunda ne yapacağı net yazılı.

---

## 📌 ARKA PLAN BİLGİSİ (ajan otomatik bilmiyor — promptlara dahildir)

- **Repo kökü:** `/Users/nazmi/Desktop/Projeler/proje/showMe`
- **Ne yapıldı:** `src-tauri` → `tauri/`, `src-ui` → `ui/`, `src-py` → `backend/`,
  `engine/src/*` → `backend/showme/engine/*`, `engine/config` → `backend/config`.
  234 dosyada `from src.X` → `from showme.engine.X`. PyInstaller spec, Tauri
  config, packaging script'leri, root `package.json`, root `README.md`
  güncellendi.
- **Snapshot:** Tag `refactor-base-2026-05-09`, branch
  `backup-pre-restructure`, commit `e2e864c`. Geri dönmek için:
  `git reset --hard refactor-base-2026-05-09`.
- **Sandbox kalıntıları (silinemedi, gizli):** `.legacy_engine_empty/` ve
  `.legacy_src_py_tmp/`. macOS Finder'da görünür yapıp normal `rm -rf` ile
  silinebilirler.
- **Hâlâ diskte ama gitignore'da (~3.6 GB):** `node_modules/`,
  `tauri/target/` (ex `src-tauri/target`), `backend/.legacy_src_py_tmp/.venv/`,
  `artifacts/`, `output/`, `test-artifacts/`, `.playwright-cli/`.

---

## 🅿️ P0 — Bağlam Promptu (ilk yapıştır, sonraki promptlarda atıfta bulun)

```
Sen showMe projesinin kıdemli refactor doğrulayıcısısın. Repo:
/Users/nazmi/Desktop/Projeler/proje/showMe

09 Mayıs 2026'da yapılan "yekpare tek ağaç" refactor'unun ardından doğrulama
yapacaksın. Refactor özeti:

- src-tauri/   → tauri/
- src-ui/      → ui/
- src-py/      → backend/
- engine/src/* → backend/showme/engine/* (artık normal Python alt-paketi)
- engine/config → backend/config/
- 234 dosyada `from src.X import Y` → `from showme.engine.X import Y`
- Root package.json workspace: ui (eski src-ui yerine)
- tauri/tauri.conf.json frontendDist: ../ui/dist
- tauri/src/sidecar.rs default_sidecar_cwd: ../backend
- backend/showme-backend.spec yol-bağımsız, collect_submodules('showme')
- packaging/build_sidecar.sh sadece spec'i çalıştırıyor, çıktı tauri/binaries

Kurallar:
1. Snapshot tag'i `refactor-base-2026-05-09`. Bir şey ciddi bozulursa bana
   sormadan ASLA `git reset --hard` çalıştırma; önce hata raporu ver.
2. Yeni dosya yaratmaya gerek yok — sadece doğrulama, küçük yamalar ve
   commit yapacaksın.
3. Tüm bash komutlarını gerçek terminale yaz; çıktıyı tam göster.
4. Bir prompt başarısız olursa sonrakileri çalıştırma; hatayı şu formatta
   raporla:
   - HATA: <komut>
   - ÇIKTI: <son 30 satır>
   - HİPOTEZ: <muhtemel sebep>
   - ÖNERİ: <küçük yama veya escalate>
5. Başarı durumunda her promptun sonunda kısa bir checkmark özeti ver.

Hazır olduğunda "P0 alındı" diye yaz. Sonra P1'i bekle.
```

---

## 🅿️ P1 — Eski Kalıntıları Temizle ve Bağımlılıkları Yükle

```
P1 — Cleanup + dependency install.

Adımlar (sırayla, her birini gerçekten çalıştır, çıktıyı göster):

1) Repo köküne git:
   cd /Users/nazmi/Desktop/Projeler/proje/showMe

2) Sandbox'ın silemediği kalıntıları kaldır:
   rm -rf .legacy_engine_empty .legacy_src_py_tmp
   rm -f .DS_Store .git/*.lock.dead* .git/*.lock.dead .git/refs/tags/*.lock.dead*
   ls -la | head -25  # üst seviyenin temiz olduğunu doğrula

3) Eski venv ve build artefaktlarını kaldır (yeni konuma kuracağız):
   rm -rf node_modules backend/.venv backend/build backend/dist
   rm -rf backend/showme_backend.egg-info
   rm -rf tauri/target tauri/binaries
   rm -rf artifacts output test-artifacts .playwright-cli

4) Frontend deps:
   npm install
   # Workspace: ui'yi çözmeli; node_modules root'ta + ui/'da hoisted

5) Backend deps (uv tercih, yoksa pip):
   cd backend
   if command -v uv >/dev/null; then
     uv venv
     uv pip install -e ".[dev]"
   else
     python3 -m venv .venv
     . .venv/bin/activate
     pip install -e ".[dev]"
   fi
   cd ..

6) Rust toolchain hazır mı kontrol et:
   cargo --version || echo "cargo yok — Tauri build skipped olacak"
   rustc --version || true

Çıktı kontrolü:
- npm install: 0 vuln, peer warnings tolere edilir
- backend install: showme 0.0.1, fastapi/uvicorn/yfinance/feedparser çekilmeli
- ls -la sonucunda artık .legacy_* yok

Başarılıysa "P1 ✓" ile bitir; sonra P2 bekle.
```

---

## 🅿️ P2 — Statik Doğrulamalar (Lint + Typecheck + Import Resolution)

```
P2 — Static checks (no test execution, no build).

Adımlar:

1) Repo kökü:
   cd /Users/nazmi/Desktop/Projeler/proje/showMe

2) Python AST + import resolution sweep (no execution):
   python3 << 'PY'
   import ast, sys, pathlib
   sys.path.insert(0, "backend")
   backend = pathlib.Path("backend")
   def mod_exists(d):
       parts = d.split(".")
       p = backend / "/".join(parts)
       return (p.is_dir() and (p / "__init__.py").exists()) or p.with_suffix(".py").is_file()
   syntax_errors, missing = [], set()
   for py in backend.rglob("*.py"):
       if any(s in str(py) for s in ("__pycache__", ".venv", "/build/", "/dist/", "egg-info")):
           continue
       try:
           tree = ast.parse(py.read_text())
       except SyntaxError as e:
           syntax_errors.append((str(py), e.lineno, str(e)))
           continue
       for n in ast.walk(tree):
           if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("showme."):
               if not mod_exists(n.module):
                   missing.add((n.module, str(py)))
   print(f"syntax-errors: {len(syntax_errors)}")
   for e in syntax_errors[:5]: print(" ", e)
   print(f"missing-showme-modules: {len(missing)}")
   for m in sorted(missing)[:10]: print(" ", m)
   PY

3) Hâlâ stale `from src.` referansı kaldı mı:
   grep -rln 'from src\.' backend/showme backend/tests 2>&1 \
     | grep -v __pycache__ || echo "✓ no stale src. imports"

4) JSON config'ler geçerli mi:
   for f in package.json ui/package.json tauri/tauri.conf.json \
            tauri/capabilities/default.json; do
     python3 -c "import json,sys; json.load(open('$f')); print('✓ $f')" \
       || { echo "✗ $f"; exit 1; }
   done

5) UI tarafı tip + lint:
   npm run -w ui typecheck   # tsc --noEmit
   npm run -w ui lint        # eslint . --max-warnings 0

6) Backend ruff:
   cd backend && (uv run ruff check . || ruff check .) ; cd ..

Beklenen sonuç:
- syntax-errors: 0
- missing-showme-modules: 0
- 4 JSON dosyası ✓
- tsc clean
- eslint 0 warning
- ruff clean

Hata varsa raporla ve dur. Başarılıysa "P2 ✓".
```

---

## 🅿️ P3 — Test Süitleri (Backend pytest + UI vitest)

```
P3 — Test suites.

Adımlar:

1) cd /Users/nazmi/Desktop/Projeler/proje/showMe

2) Backend pytest:
   cd backend
   if command -v uv >/dev/null; then uv run pytest -q; else pytest -q; fi
   cd ..

3) UI vitest:
   npm run -w ui test

Beklenen:
- Backend: 17 test dosyası, hepsi pass.
  Eğer test_btmm.py veya tests/ altında "import src.X" patladıysa:
    o test dosyasındaki `import src.X` satırlarını manuel
    `import showme.engine.X` olarak değiştir, tekrar çalıştır.
- UI: 18 dosya × ~91 test, hepsi pass.

Hata sınıflandırması:
A) Import error içeriyorsa: refactor sırasında atlanmış bir dosya — bul ve
   düzelt, raporla.
B) Adapter / network error (yfinance, exchangerate.host vs): test dış servis
   ister; SHOWME_OFFLINE=1 ile ya da test fixture mock'larıyla atlanmalı.
   Geçmiş round'larda bu testler offline-tolerant'tı; rejressyon olabilir.
C) Path-bağımlı test: çalışma dizini varsayımı (eski src-py vs yeni backend);
   ilgili `Path("...")` veya `Path.cwd()` kullanımlarını bul.

Başarılıysa "P3 ✓".
```

---

## 🅿️ P4 — Build (Sidecar + UI + Tauri)

```
P4 — Production builds.

Adımlar:

1) cd /Users/nazmi/Desktop/Projeler/proje/showMe

2) UI bundle:
   npm run build:ui
   ls -la ui/dist/    # index.html + assets/ olmalı

3) PyInstaller sidecar:
   bash packaging/build_sidecar.sh
   # Çıktı: tauri/binaries/showme-backend-aarch64-apple-darwin (yürütülebilir)
   ls -lh tauri/binaries/

4) Sidecar'ın binary olarak çalışıp çalışmadığını doğrula (3 saniye):
   tauri/binaries/showme-backend --port 0 &
   PID=$!
   sleep 3
   kill $PID 2>/dev/null
   wait 2>/dev/null
   # stdout'ta "SIDECAR_PORT=<u16>" görünmeli

5) Tauri full build (sadece cargo varsa):
   if command -v cargo >/dev/null; then
     npm run tauri:build 2>&1 | tail -30
     # showMe.app + .dmg üretmeli
     ls -la tauri/target/release/bundle/macos/  # showMe.app
     ls -la tauri/target/release/bundle/dmg/    # *.dmg
   else
     echo "cargo yok — Tauri build atlandı"
   fi

Hata sınıflandırması:
- PyInstaller "ModuleNotFoundError: showme.engine.X": spec dosyasında
  hiddenimports eksik. backend/showme-backend.spec'e ekle.
- Tauri "frontend dist not found": ui/dist üretilmemiş; P4 adım 2'yi tekrarla.
- Tauri "externalBin not found": tauri/binaries/showme-backend-aarch64-apple-darwin
  yok; P4 adım 3'ü tekrarla.
- Codesign (ad-hoc) failure: macOS'un yeni kuralları için
  --options runtime ekle.

Başarılıysa "P4 ✓".
```

---

## 🅿️ P5 — Canlı Smoke (Sidecar HTTP + UI Sayfası)

```
P5 — Live smoke test.

Adımlar:

1) cd /Users/nazmi/Desktop/Projeler/proje/showMe

2) Sidecar'ı sabit bir portta başlat:
   cd backend && (uv run python -m showme.server --port 8765 &)
   SIDECAR_PID=$!
   sleep 5
   cd ..

3) /api/health:
   curl -sS http://127.0.0.1:8765/api/health
   # {"status":"healthy","engine_path":"...","function_count":138} bekleniyor

4) /api/sidecar/info:
   curl -sS http://127.0.0.1:8765/api/sidecar/info | python3 -m json.tool

5) /api/function-index (cold cache → arka plan thread; ilk istek warmup):
   for i in 1 2 3; do
     curl -sS "http://127.0.0.1:8765/api/function-index" \
       | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'attempt {$i}: {len(d.get(\"functions\",[]))} functions')"
     sleep 2
   done

6) Bir function execution sweep (BTC + AAPL):
   curl -sS "http://127.0.0.1:8765/api/fn/DES?symbol=AAPL"  | python3 -m json.tool | head -30
   curl -sS "http://127.0.0.1:8765/api/fn/CN?symbol=BTCUSDT" | python3 -m json.tool | head -30
   curl -sS "http://127.0.0.1:8765/api/fn/BETA?symbol=AAPL" | python3 -m json.tool | head -30

7) Sidecar'ı durdur:
   kill $SIDECAR_PID 2>/dev/null
   wait 2>/dev/null

8) (Opsiyonel) Tauri app'i aç (yalnızca cargo varsa):
   open tauri/target/release/bundle/macos/showMe.app
   # 5 saniye sonra Cmd+Q veya manuel kapat
   # Console.app → showMe filtresi: SIDECAR_PORT, /api/health 200 görmelisin

Beklenen:
- /api/health 200 + healthy
- function-index 138 (Round 33 baseline) civarı
- DES/CN/BETA payload'ları warning bile olsa boş olmamalı

Başarılıysa "P5 ✓".
```

---

## 🅿️ P6 — Commit + Round Notes + Doğrulama Bitirişi

```
P6 — Commit & document.

Adımlar:

1) cd /Users/nazmi/Desktop/Projeler/proje/showMe

2) git status'u oku, beklenmedik değişiklik var mı:
   git status --short | head -40

3) Refactor commit'ini at:
   git add -A
   git commit -m "refactor: unified single-tree layout

- src-tauri → tauri, src-ui → ui, src-py → backend
- engine/src/* merged into backend/showme/engine/* (regular Python subpackage)
- 234 imports rewritten: from src.X → from showme.engine.X
- PyInstaller spec made path-independent, uses collect_submodules('showme')
- Tauri config and sidecar.rs updated for new backend/ cwd
- Comprehensive .gitignore for build/cache artifacts
- README + docs/refactor_verification_prompts.md added

Snapshot: tag refactor-base-2026-05-09, branch backup-pre-restructure"

4) Round 34 notesu oluştur (kronoloji):
   cat > docs/round_notes/34.md <<'NOTE'
   # Round 34 — Yekpare tek-ağaç refactor (2026-05-09)

   ## Özet

   Üç-süreçli proje (src-tauri/src-py/src-ui/engine) tek bir yekpare ağaca
   konsolide edildi. engine/ artık ayrı bir Python ağacı değil, normal bir
   `showme.engine` alt-paketi. SHOWME_ENGINE_PATH sys.path enjeksiyonu kalktı.

   ## Yapısal değişiklikler

   - src-tauri/   → tauri/
   - src-ui/      → ui/
   - src-py/      → backend/
   - engine/src/  → backend/showme/engine/
   - engine/config → backend/config/
   - src-py/tests + tests → backend/tests + tests (e2e)

   ## İmport rejimi

   234 dosyada `from src.X` → `from showme.engine.X`. attach_engine() artık
   sadece SHOWME_ENGINE_ROOT yayınlıyor; sys.path'a hiçbir şey eklemiyor.
   PyInstaller `collect_submodules('showme')` ile tüm alt-paketleri otomatik
   buluyor.

   ## Konfig güncellemeleri

   - Root package.json workspace: src-ui → ui
   - sidecar:dev: cd backend && uv run python -m showme.server
   - tauri/tauri.conf.json frontendDist: ../ui/dist
   - tauri/src/sidecar.rs default_sidecar_cwd → ../backend
   - tauri/src/commands.rs migration cwd → ../backend
   - backend/showme-backend.spec yol-bağımsız (Path(SPECPATH))
   - packaging/build_sidecar.sh: sadece spec'i çalıştırır

   ## Doğrulama (P0–P6 sonuçları buraya)

   <P2/P3/P4/P5 özetlerini buraya yapıştır>

   ## Snapshot

   - Tag: refactor-base-2026-05-09
   - Branch: backup-pre-restructure
   - Pre-refactor base: b9cdca6 (Add instant secondary news line)
   - WIP snapshot commit: e2e864c
   NOTE

5) Coder log'a tek satır ekle:
   # docs/coder_log.md başına şunu insert et (en yenisi üstte konvansiyonu):
   # "## 2026-05-09 — Round 34 — Yekpare tek-ağaç refactor"
   # ve docs/round_notes/34.md'ye link ver.

6) Round 34 commit:
   git add docs/round_notes/34.md docs/coder_log.md
   git commit -m "docs: round 34 unified-tree refactor notes"

7) Final smoke özeti yaz, kullanıcıya rapor et:
   - sayım: <kaç dosya değişti, kaç satır>
   - testler: backend X/X pass, UI Y/Y pass, ruff clean, eslint clean
   - build: sidecar OK (boyut MB), UI bundle OK (kB gz), .app + .dmg üretildi mi
   - smoke: /api/health 200, function-index N, DES/CN/BETA payload özet

Başarılıysa "P6 ✓ — refactor production-ready".
```

---

## 🆘 Acil Durum — Geri Dönüş

Refactor üretim ortamına gönderilmeden ÖNCE bir şey ciddi bozulursa:

```
cd /Users/nazmi/Desktop/Projeler/proje/showMe
git status
git stash push -u -m "abort-refactor"   # mevcut değişiklikleri sakla
git reset --hard refactor-base-2026-05-09
# Eski yapı geri geldi. Backend deps eski src-py/.venv'i kullanır.
# pre-refactor-snapshot tag'i de aynı commit'i gösterir.
```

Ya da daha temiz:

```
git checkout backup-pre-restructure
# Snapshot branch'inde çalışmaya devam et; main'de refactor commit'i kalır.
```

---

## ✅ Bitiş Kriteri

| Kriter | Hedef |
|---|---|
| `from src.` import kalmamış | 0 |
| `showme.*` import resolution | 100% |
| pytest backend | 100% pass |
| vitest UI | 100% pass |
| ESLint warning | 0 |
| ruff issue | 0 |
| tsc error | 0 |
| `npm run build:ui` | OK |
| `bash packaging/build_sidecar.sh` | OK, binary çalışıyor |
| `npm run tauri:build` | .app + .dmg üretildi |
| `/api/health` | 200 healthy |
| `/api/function-index` | ≥ 138 fonksiyon |

Hepsi yeşilse refactor production-ready'dir.
