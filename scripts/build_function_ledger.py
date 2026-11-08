#!/usr/bin/env python3
"""Merge B1 (strict truth audit), the offline gate (T4/T5/T6/T9) and the B2
agent deep review into one ranked function ledger.

Inputs:
  --journal   journal.jsonl of the B2 workflow run (agent results by label)
  --b1        one or more strict-audit ledger.json files (later ones win)
Outputs:
  docs/audit/function-ledger.json and docs/audit/function-ledger.md

The B2 settlement rules are the workflow's own: a P0/P1 finding is
"confirmed" when the adversarial verifier did not refute it (its
real_severity wins), "upheld"/"rejected" when the arbiter ruled, and
"disputed" when no ruling exists; P2/P3 are single-reviewer "reported".
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ["GP", "HP", "FA", "DES", "TOP", "CN", "WATCH", "ECO", "PORT", "OMON", "CRVF", "WIRP", "MAP"]
SEV_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def load_journal(path: Path) -> dict[str, list[dict]]:
    labels: dict[str, str] = {}
    by_label: dict[str, list[dict]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") == "started":
            labels[rec["agentId"]] = rec.get("label", "")
        elif "result" in rec and rec.get("agentId") in labels:
            by_label[labels[rec["agentId"]]].append(rec["result"])
    return by_label


def settle_unit(unit: str, codes: list[str], by_label: dict[str, list[dict]]) -> dict:
    first = (by_label.get(f"review:{unit}") or [None])[-1] or {}
    by_code = {str(f.get("code", "")).upper(): f for f in first.get("functions", [])}
    for fu in by_label.get(f"followup:{unit}", []):
        for f in (fu or {}).get("functions", []):
            code = str(f.get("code", "")).upper()
            prev = by_code.get(code)
            if not prev or not prev.get("reviewed") or (f.get("reviewed") and not prev.get("independent_check")):
                by_code[code] = f
    functions = []
    for code in codes:
        f = dict(by_code.get(code) or {"code": code, "reviewed": False,
                                       "not_reviewed_reason": "no reviewer output", "findings": []})
        f["code"] = code
        f["findings"] = [dict(x, id=f"{code}#{i + 1}") for i, x in enumerate(f.get("findings") or [])]
        functions.append(f)
    verdicts = {}
    for v in by_label.get(f"verify:{unit}", []):
        for item in (v or {}).get("verdicts", []):
            verdicts[item["id"]] = item
    rulings = {}
    judged = bool(by_label.get(f"judge:{unit}"))
    for j in by_label.get(f"judge:{unit}", []):
        for item in (j or {}).get("rulings", []):
            rulings[item["id"]] = item
    for f in functions:
        for x in f["findings"]:
            x["final"], x["status"] = x["severity"], "reported"
            if x["severity"] in ("P0", "P1"):
                v, r = verdicts.get(x["id"]), rulings.get(x["id"])
                if v and not v.get("refuted"):
                    real = v.get("real_severity", x["severity"])
                    x["final"], x["status"] = (real, "confirmed") if real != "NONE" else ("REJECTED", "rejected")
                elif r:
                    x["final"] = r.get("final_severity", "REJECTED")
                    x["status"] = "upheld" if r.get("upheld") else "rejected"
                else:
                    x["status"] = "disputed" if judged or v else "unverified"
                x["verifier"] = v
                x["ruling"] = r
    return {"unit": unit, "functions": functions}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", required=True)
    ap.add_argument("--units", required=True, help="b2_units.json from the prep step")
    ap.add_argument("--b1", nargs="+", required=True)
    ap.add_argument("--critic", help="optional JSON file with the workflow's blind_spots")
    args = ap.parse_args()

    units = json.loads(Path(args.units).read_text(encoding="utf-8"))["units"]
    by_label = load_journal(Path(args.journal))
    b1: dict = {}
    for path in args.b1:
        b1.update(json.loads(Path(path).read_text(encoding="utf-8"))["functions"])

    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from showme.audit import gate, truth  # noqa: E402

    cfg = truth.load_config()
    sources, _ = gate.registry_sources()
    entries = {e["code"].upper(): e for e in gate.catalog_entries()}

    ledger = []
    for u in units:
        settled = settle_unit(u["unit"], [f["code"] for f in u["functions"]], by_label)
        meta = {f["code"]: f for f in u["functions"]}
        for f in settled["functions"]:
            code = f["code"]
            rec_b1 = b1.get(code, {})
            cases = rec_b1.get("cases", [])
            order = {"RED": 3, "NETWORK_FLAKE": 2, "AMBER": 1, "GREEN": 0}
            data_grade = max((c["grade"] for c in cases), key=lambda g: order.get(g, 0)) if cases else "NOT_AUDITED"
            offline = gate.offline_findings_for(entries.get(code, {"code": code}), sources.get(code), cfg)
            live_findings = [x for x in f["findings"] if x["status"] not in ("rejected",)]
            worst = min((SEV_RANK.get(x["final"], 9) for x in live_findings
                         if x["status"] in ("confirmed", "upheld", "reported")), default=9)
            ledger.append({
                "code": code,
                "name": meta[code]["name"],
                "unit": u["unit"],
                "category": u["category"],
                "core": code in CORE,
                "b1_data_grade": data_grade,
                "b1_cases": [{"case": c["case_id"], "grade": c["grade"], "status": c["status"],
                              "rules": sorted({x["rule"] for x in c["findings"]})} for c in cases],
                "offline": dict(Counter(f"{x.check}:{x.rule}" for x in offline)),
                "b2": {k: f.get(k) for k in ("reviewed", "not_reviewed_reason", "reference_method", "reference_url",
                                             "live_call", "independent_check", "check_passed")},
                "findings": f["findings"],
                "worst_severity": next((s for s, r in SEV_RANK.items() if r == worst), None),
            })

    def rank(rec):
        return (SEV_RANK.get(rec["worst_severity"] or "", 9), 0 if rec["core"] else 1,
                0 if rec["b1_data_grade"] == "RED" else 1, rec["code"])

    ledger.sort(key=rank)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {"journal": args.journal, "b1": args.b1},
        "functions": ledger,
        "blind_spots": json.loads(Path(args.critic).read_text(encoding="utf-8")) if args.critic else None,
    }
    docs = ROOT / "docs" / "audit"
    (docs / "function-ledger.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (docs / "function-ledger.md").write_text(render(out), encoding="utf-8")
    tally = Counter(f"{x['status']}:{x['final']}" for r in ledger for x in r["findings"])
    print(f"functions={len(ledger)} reviewed={sum(1 for r in ledger if r['b2']['reviewed'])} tally={dict(tally)}")
    return 0


def render(out: dict) -> str:
    fns = out["functions"]
    reviewed = sum(1 for r in fns if r["b2"]["reviewed"])
    checked = Counter(str(r["b2"]["check_passed"]) for r in fns)
    tally = Counter((x["status"], x["final"]) for r in fns for x in r["findings"])
    lines = [
        "# Function ledger — B1 + offline gate + B2 deep review",
        "",
        f"Generated: {out['generated_at']}",
        "",
        f"- Functions: {len(fns)}; B2 reviewed: {reviewed}; independent recomputation passed / failed / not done: "
        f"{checked.get('True', 0)} / {checked.get('False', 0)} / {checked.get('None', 0)}",
        "- Status: confirmed = verifier could not refute (its severity wins); upheld/rejected = arbiter ruling; "
        "disputed = no ruling; reported = P2/P3 single reviewer.",
        "",
        "## Findings by status and final severity",
        "",
        "| Status | P0 | P1 | P2 | P3 | REJECTED |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for status in ("confirmed", "upheld", "disputed", "unverified", "reported", "rejected"):
        lines.append(f"| {status} | " + " | ".join(str(tally.get((status, s), 0))
                                                  for s in ("P0", "P1", "P2", "P3", "REJECTED")) + " |")
    lines += ["", "## Confirmed / upheld P0–P1 (fix first)", "",
              "| Code | Core | Sev | Status | Finding | Where |", "|---|---|---|---|---|---|"]
    for r in fns:
        for x in r["findings"]:
            if x["status"] in ("confirmed", "upheld") and x["final"] in ("P0", "P1"):
                lines.append(f"| {r['code']} | {'yes' if r['core'] else ''} | {x['final']} | {x['status']} | "
                             f"{x['title'].replace('|', '/')} | {str(x.get('file_line', '')).replace('|', '/')[:80]} |")
    lines += ["", "## Suggested repair order per category (D)", ""]
    by_cat = defaultdict(list)
    for r in fns:
        by_cat[r["category"]].append(r)
    for cat in sorted(by_cat):
        order = [f"{r['code']}({r['worst_severity'] or '-'})" for r in by_cat[cat]]
        lines.append(f"- **{cat}**: " + ", ".join(order))
    lines += ["", "## Every function", "",
              "| Code | Category | B1 data | B2 reviewed | Recompute | Worst | Surviving findings |",
              "|---|---|---|---|---|---|---:|"]
    for r in fns:
        alive = [x for x in r["findings"] if x["status"] != "rejected"]
        lines.append(f"| {r['code']} | {r['category']} | {r['b1_data_grade']} | {r['b2']['reviewed']} | "
                     f"{r['b2']['check_passed']} | {r['worst_severity'] or '-'} | {len(alive)} |")
    if out.get("blind_spots"):
        lines += ["", "## Blind spots (completeness critic)", ""]
        for b in out["blind_spots"]:
            lines.append(f"- **{b['area']}** — {b['why']} → {b['suggestion']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
