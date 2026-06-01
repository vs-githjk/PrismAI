"""Replay the think_loop corpus against verb_gate. Pure-Python sanity check —
no LLM calls. Validates that the regex-level gate decisions match the
hand-labeled expectations. This is the v1 eval; the real test is running
the full path against Groq in a meeting.

Usage:
  cd backend
  python tests/run_think_loop_corpus.py

Prints accuracy + per-case results. Exits non-zero if accuracy < 95%.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import think_loop  # noqa: E402


def main() -> int:
    corpus_path = Path(__file__).resolve().parent / "think_loop_corpus.jsonl"
    cases = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    passed = 0
    failed: list[dict] = []
    for case in cases:
        with_artifact = bool(case.get("with_artifact", False))
        reason = think_loop.verb_gate(
            command=case["command"],
            tool_name=case["tool"],
            has_prior_artifact=with_artifact,
        )
        actual = "block" if reason else "allow"
        expected = case["expect"]
        ok = actual == expected
        if ok:
            passed += 1
        else:
            failed.append({**case, "actual": actual, "block_reason": reason})

    total = len(cases)
    accuracy = passed / total if total else 0.0
    print(f"\nthink_loop verb_gate corpus: {passed}/{total} = {accuracy:.1%}")

    if failed:
        print("\nFailures:")
        for f in failed:
            art_note = " (with_artifact)" if f.get("with_artifact") else ""
            print(f"  - tool={f['tool']!r:30s} expect={f['expect']:5s} actual={f['actual']:5s}{art_note}")
            print(f"      command: {f['command']!r}")
            print(f"      reason : {f['reason']}")

    return 0 if accuracy >= 0.95 else 1


if __name__ == "__main__":
    sys.exit(main())
