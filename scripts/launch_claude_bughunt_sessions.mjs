#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, openSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import path from "node:path";

const REPO = "/Users/nazmi/Desktop/Projeler/proje/showMe";
const CLAUDE_BIN =
  process.env.CLAUDE_BIN ||
  "/Users/nazmi/Library/Application Support/Claude/claude-code/2.1.138/claude.app/Contents/MacOS/claude";
const BASE_DIR =
  process.env.SHOWME_BUGHUNT_BASE ||
  "/Users/nazmi/Desktop/ShowMe_Claude_Bughunt_2026-05-17";
const STAMP =
  process.env.SHOWME_BUGHUNT_STAMP ||
  new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);

const args = new Set(process.argv.slice(2));
const shouldLaunch = args.has("--launch");
const shouldPrepareWorktrees = args.has("--prepare-worktrees");
const shouldPrepareOnly = args.has("--prepare") || (!shouldLaunch && !shouldPrepareWorktrees);

const officialIndex = path.join(REPO, "ui/src/functions/static-index.ts");
const registryPath = path.join(REPO, "ui/src/functions/registry.tsx");
const promptDir = path.join(BASE_DIR, "prompts");
const logDir = path.join(BASE_DIR, "logs");
const worktreeDir = path.join(BASE_DIR, "worktrees");
mkdirSync(promptDir, { recursive: true });
mkdirSync(logDir, { recursive: true });
mkdirSync(worktreeDir, { recursive: true });

function run(cmd, cmdArgs, options = {}) {
  const result = spawnSync(cmd, cmdArgs, {
    cwd: options.cwd || REPO,
    encoding: "utf8",
    stdio: options.stdio || "pipe",
    env: { ...process.env, ...(options.env || {}) },
  });
  if (result.status !== 0) {
    throw new Error(
      [
        `Command failed: ${cmd} ${cmdArgs.join(" ")}`,
        result.stdout?.trim(),
        result.stderr?.trim(),
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  return result.stdout || "";
}

function parseCodes() {
  const source = readFileSync(officialIndex, "utf8");
  const registrySource = readFileSync(registryPath, "utf8");
  const staticMatches = [...source.matchAll(/"code"\s*:\s*"([A-Z0-9_]+)"/g)].map((m) => m[1]);
  const nativeEntryBlock = registrySource.match(/const NATIVE_FUNCTION_ENTRIES[\s\S]*?];/);
  const nativeMatches = nativeEntryBlock
    ? [...nativeEntryBlock[0].matchAll(/code:\s*"([A-Z0-9_]+)"/g)].map((m) => m[1])
    : [];
  const matches = [...staticMatches, ...nativeMatches.filter((code) => !staticMatches.includes(code))];
  const unique = [...new Set(matches)];
  if (unique.length !== matches.length) {
    throw new Error(`Function code inputs contain duplicates: ${matches.length} vs ${unique.length}`);
  }
  if (unique.length !== 147) {
    throw new Error(
      `Expected 147 function codes, found ${unique.length} (static-index=${staticMatches.length}, native-missing=${
        matches.length - staticMatches.length
      })`,
    );
  }
  return unique;
}

const officialCodes = parseCodes();
const deliberateRepeats = [
  "ALRT",
  "ANR",
  "BIO",
  "BTMM",
  "CN",
  "CORR",
  "DES",
  "EQS",
  "FA",
  "GEX",
  "GP",
  "HP",
  "MAP",
  "NI",
  "PORT",
  "TOP",
  "WCRS",
  "WEI",
  "AGENT",
  "ASK",
  "MIS",
  "WATCH",
  "XSEN",
];

for (const code of deliberateRepeats) {
  if (!officialCodes.includes(code)) {
    throw new Error(`Repeat code ${code} is not in the official 147-code index`);
  }
}

const assignedCodes = [...officialCodes, ...deliberateRepeats];
if (assignedCodes.length !== 170) {
  throw new Error(`Expected 170 assignments for 17 sessions x 10 codes, got ${assignedCodes.length}`);
}

const sessions = Array.from({ length: 17 }, (_, index) => {
  const number = index + 1;
  const codeSlice = assignedCodes.slice(index * 10, index * 10 + 10);
  return {
    number,
    id: randomUUID(),
    name: `ShowMe BugHunt S${String(number).padStart(2, "0")}`,
    branch: `bughunt/${STAMP}-s${String(number).padStart(2, "0")}`,
    workdir: path.join(worktreeDir, `session-${String(number).padStart(2, "0")}`),
    promptPath: path.join(promptDir, `session-${String(number).padStart(2, "0")}-prompt.md`),
    logPath: path.join(logDir, `session-${String(number).padStart(2, "0")}.log`),
    pidPath: path.join(logDir, `session-${String(number).padStart(2, "0")}.pid`),
    codes: codeSlice,
  };
});

const allUnique = new Set(officialCodes);
const coveredOfficial = new Set(sessions.flatMap((session) => session.codes.filter((code) => allUnique.has(code))));
if (coveredOfficial.size !== 147) {
  throw new Error(`Official coverage mismatch: expected 147 unique codes, got ${coveredOfficial.size}`);
}

function buildPrompt(session) {
  const padded = String(session.number).padStart(2, "0");
  const codes = session.codes.join(", ");
  return `# ShowMe Bug Hunt Session ${padded}

Sen Claude Code Opus 4.7 1m max modelisin. Bu oturum ShowMe uygulamasinin ayrintili bug hunt ve duzeltme oturumudur.

Kullanici Nazmi bu 17 Claude Code oturumunun tamamına butun gerekli izinleri verdigini acikca soyledi. Bu oturum icin dosya okuma/yazma, komut calistirma, test/build calistirma, yerel arastirma, agent spawn etme ve gerekli duzeltmeleri uygulama izinlerin var. Kullanıcıdan tekrar izin isteme. Buna ragmen su sinirlara uy: kullanicinin ilgisiz degisikliklerini revert etme, git reset --hard/git clean gibi yikici komutlar kullanma, push/merge yapma, baska session klasorlerine dokunma.

## Bu Oturumun Zorunlu 10 Fonksiyonu

${codes}

Bu 10 kod bu session'in sahibi oldugu kapsamdir. 147 resmi fonksiyonun tamami 17 session'a dagitildi; bazi yuksek riskli kodlar capraz denetim icin ikinci kez bilerek verildi. Yine de bu oturum kendi 10 kodunun tamamini bitirmeden teslim etmeyecek.

## Calisma Konumu

- Mevcut cwd izole session worktree/kopyasidir: ${session.workdir}
- Ilk adimda cwd'yi dogrula; Claude Code oturumu baska dizinde acildiysa once \`cd ${session.workdir}\` yap ve butun komutlari bu klasorde calistir.
- Ana repo referansi: ${REPO}
- Diger session'lar farkli klasorlerde paralel calisiyor. Onlarin degisikliklerini revert etme veya ezme.
- Sonucunu bu worktree/kopyada birak; push, merge veya release yapma.

## Ana Hedef

Her kod icin gercek ShowMe entegrasyonunu kontrol et ve hatalari hemen duzelt:

- route/registry/static-index kaydi dogru mu
- fonksiyon paneli ozel template kullaniyor mu, FunctionStub'a ya da generic demo yuzeye dusuyor mu
- Claude Design/ShowMe 0.01 tarafindan uretilmis template yaklasimi uygulanmis mi
- backend contract/API/state/stream baglantilari calisiyor mu
- Papyrus temasi showme 0.01 konusmasindaki papyrus gibi duruyor mu
- Matrix ve diger temalar gorunur shell, Preferences, toolbar, statusbar, pane, cards, data-grid, modal ve function template yuzeylerine gercek token olarak yayiliyor mu
- Settings/Preferences alt sayfalari, tema secimleri ve shell persistence kirilmiyor mu
- sembol, market, portfoy, haber, risk, chart, terminal akislari fake/statik kalmiyor mu

## Mutlaka Agent Spawn Et

Bu oturum kendi icinde agentlar spawn edecek. Claude Code'da mcp__ccd_session__spawn_task veya session/agent araci varsa en az su 4 agenti paralel calistir:

1. UI/Template Agent: verilen 10 kodun panel/template/rendering dosyalarini, design-export baglantilarini ve FunctionStub dususlerini denetlesin.
2. Backend/Contract Agent: ayni 10 kodun backend function, API contract, state, stream ve veri baglantilarini denetlesin.
3. Theme/Settings Agent: Papyrus, Matrix, diger presetler, Preferences/settings sayfalari ve shell token yayilimini denetlesin.
4. Verification Agent: test, build, routing/template audit ve gerekirse browser/native smoke akisini kursun.

Agent araci yoksa durma; ayni sorumluluklari sirali olarak kendin uygula ve finalde "agent araci yoktu, sirali yurutuldu" diye kanitla. Agentlara farkli dosya sorumluluklari ver; birbirlerinin degisikliklerini geri alma.

## Progresif Calisma Metodu

Her kod icin su donguyu uygula:

1. Envanter cikar: UI dosyasi, template dosyasi, registry/static-index kaydi, backend implementation, contract, i18n, test ve route baglantilarini listele.
2. Tasarim/template farkini bul: ozel template kullanilmiyorsa veya eski gorunum/generic layout gorunuyorsa hemen duzelt.
3. Tema farkini bul: Papyrus/Matrix ve diger preset token'lari bu yuzeye inmiyorsa hemen duzelt.
4. Veri/contract farkini bul: statik demo, fake data, bozuk endpoint veya eksik state varsa hemen duzelt.
5. Focused test calistir: ilgili test yoksa kucuk ve kalici test/probe ekle.
6. Kanit yaz: komut, sonuc, degisen dosyalar, kalan risk.
7. Sonraki koda gec. Buldugun sorunlari biriktirme; tespit ettigini o anda duzelt.

Tikanirsan metod gelistir:

- minimal repro/probe script yaz
- route/template coverage checker'i genislet
- CSS token audit'i yap
- browser/native smoke icin kucuk senaryo olustur
- backend log/HTTP trace al
- alternatif agenttan tersinden inceleme iste
- sorunu daraltmadan final verme

## Calistirilacak Kanit Kapilari

Repo durumuna gore uygun olanlari calistir; komut yoksa esdegerini bul:

- node scripts/verify_template_integration.mjs
- node scripts/verify_routing_coverage.mjs
- node scripts/audit_papyrus_drift.mjs
- npm --workspace ui run test -- --run
- npm --workspace ui run build
- backend icin mevcut pytest hedefleri veya fonksiyon bazli HTTP/probe testleri
- degisen fonksiyon icin render/route smoke testi

Build/test basarisizsa basarisizligi final sayma; once root cause bul, duzelt, tekrar calistir. Cok uzun veya dis servis bagimli bir test bloklarsa, focused yerel kanit uret ve nedenini acikca kaydet.

## Teslim Etme Sarti

Final cevabini ancak asagidakiler tamamlaninca ver:

- Bu session'in 10 kodunun tamami incelendi.
- Her kod icin UI/template/backend/theme/settings entegrasyon karari verildi.
- Bulunan hatalar ayni session'da duzeltildi.
- En az bir template/routing/theme audit ve ilgili focused test/build kaniti calistirildi.
- Kalan blokaj varsa gercek blokaj, dosya/komut/kanitla belgelenmis durumda.
- Final Turkce olacak ve su bolumleri icerecek: Kapsam, Duzeltilenler, Kanit Komutlari, Kalan Risk, Degisen Dosyalar.

Kullanici "isi bitirmeden kesinlikle teslim etmesin" dedi. Bu nedenle sadece analizle durma; ilerle, duzelt, dogrula ve ancak o zaman bitir.`;
}

function writePromptFiles() {
  for (const session of sessions) {
    writeFileSync(session.promptPath, buildPrompt(session), "utf8");
  }
  writeFileSync(
    path.join(BASE_DIR, "manifest.json"),
    JSON.stringify(
      {
        repo: REPO,
        baseDir: BASE_DIR,
        createdAt: new Date().toISOString(),
        claudeBin: CLAUDE_BIN,
        officialFunctionCount: officialCodes.length,
        assignmentCount: assignedCodes.length,
        note: "147 official ShowMe function codes are covered once; 23 high-risk codes are deliberately repeated for cross-session review.",
        sessions,
      },
      null,
      2,
    ),
    "utf8",
  );
}

function linkIfExists(source, target) {
  if (!existsSync(source) || existsSync(target)) return;
  symlinkSync(source, target, "dir");
}

function prepareWorktree(session) {
  if (!existsSync(path.join(session.workdir, ".git"))) {
    run("git", ["worktree", "add", "-B", session.branch, session.workdir, "HEAD"]);
  }
  run(
    "rsync",
    [
      "-a",
      "--exclude",
      ".git/",
      "--exclude",
      "node_modules/",
      "--exclude",
      "ui/node_modules/",
      "--exclude",
      "backend/.venv/",
      "--exclude",
      "backend/build/",
      "--exclude",
      "backend/dist/",
      "--exclude",
      "target/",
      "--exclude",
      "tauri/target/",
      "--exclude",
      "tauri/binaries/",
      "--exclude",
      "dist/",
      "--exclude",
      "ui/dist/",
      "--exclude",
      ".pytest_cache/",
      "--exclude",
      "__pycache__/",
      "--exclude",
      "x_scraper_ai/model/",
      `${REPO}/`,
      `${session.workdir}/`,
    ],
    { cwd: REPO },
  );
  linkIfExists(path.join(REPO, "node_modules"), path.join(session.workdir, "node_modules"));
  linkIfExists(path.join(REPO, "ui/node_modules"), path.join(session.workdir, "ui/node_modules"));
  linkIfExists(path.join(REPO, "backend/.venv"), path.join(session.workdir, "backend/.venv"));
  linkIfExists(path.join(REPO, "tauri/binaries"), path.join(session.workdir, "tauri/binaries"));
}

function launchSession(session) {
  const logFd = openSync(session.logPath, "a");
  const errFd = openSync(session.logPath, "a");
  const prompt = readFileSync(session.promptPath, "utf8");
  const child = spawn(
    CLAUDE_BIN,
    [
      "-p",
      "--output-format",
      "stream-json",
      "--verbose",
      "--model",
      "claude-opus-4-7[1m]",
      "--effort",
      "max",
      "--permission-mode",
      "bypassPermissions",
      "--allow-dangerously-skip-permissions",
      "--dangerously-skip-permissions",
      "--session-id",
      session.id,
      "--name",
      session.name,
      prompt,
    ],
    {
      cwd: session.workdir,
      detached: true,
      stdio: ["ignore", logFd, errFd],
      env: {
        ...process.env,
        CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1",
      },
    },
  );
  child.unref();
  writeFileSync(session.pidPath, `${child.pid}\n`, "utf8");
  return child.pid;
}

writePromptFiles();

if (shouldPrepareOnly) {
  console.log(`Prepared ${sessions.length} prompt files under ${promptDir}`);
  console.log(`Manifest: ${path.join(BASE_DIR, "manifest.json")}`);
}

if (shouldPrepareWorktrees) {
  for (const session of sessions) {
    prepareWorktree(session);
    console.log(
      `Prepared worktree ${String(session.number).padStart(2, "0")} path=${session.workdir} codes=${session.codes.join(",")}`,
    );
  }
}

if (shouldLaunch) {
  if (!existsSync(CLAUDE_BIN)) {
    throw new Error(`Claude Code binary not found: ${CLAUDE_BIN}`);
  }
  const launched = [];
  for (const session of sessions) {
    prepareWorktree(session);
    const pid = launchSession(session);
    launched.push({ number: session.number, pid, id: session.id, codes: session.codes });
    console.log(
      `Launched session ${String(session.number).padStart(2, "0")} pid=${pid} id=${session.id} codes=${session.codes.join(",")}`,
    );
  }
  writeFileSync(path.join(BASE_DIR, "launched.json"), JSON.stringify(launched, null, 2), "utf8");
  console.log(`Logs: ${logDir}`);
}
