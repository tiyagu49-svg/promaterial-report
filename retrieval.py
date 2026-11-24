"""Retrieve relevant past experiences to inject into an agent's prompt before a task.

Score = TF-IDF cosine(query, lesson text) x usefulness boost x failure weight + recency bonus.
Pure Python (no embedding API needed: DeepSeek/HKGAI have no embeddings endpoint).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .store import JsonMemoryStore, MemoryRecord

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are", "was", "then",
         "file", "files", "task", "use", "using", "make", "create", "write"}
FAILURE_WEIGHT = 1.15   # lessons from failures are slightly preferred: avoiding known mistakes matters


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP]


def _doc(r: MemoryRecord) -> str:
    return f"{r.task_goal} {r.lesson} {' '.join(r.tags)} {' '.join(r.tags)}"


def tfidf_scores(query: str, docs: list[str]) -> list[float]:
    toks = [Counter(tokenize(d)) for d in docs]
    n = len(docs)
    df = Counter(w for t in toks for w in t)
    idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}

    def vec(c: Counter) -> dict[str, float]:
        return {w: (1 + math.log(f)) * idf.get(w, math.log(n + 1) + 1) for w, f in c.items()}

    q = vec(Counter(tokenize(query)))
    qn = math.sqrt(sum(v * v for v in q.values())) or 1.0
    out = []
    for t in toks:
        d = vec(t)
        dn = math.sqrt(sum(v * v for v in d.values())) or 1.0
        out.append(sum(q[w] * d.get(w, 0.0) for w in q) / (qn * dn))
    return out


def retrieve(store: JsonMemoryStore, query: str, k: int = 5, min_score: float = 0.05) -> list[MemoryRecord]:
    records = store.all()
    if not records or k <= 0:
        return []
    sims = tfidf_scores(query, [_doc(r) for r in records])
    n = len(records)
    scored = []
    for i, (r, sim) in enumerate(zip(records, sims)):
        if sim < min_score:
            continue
        score = sim * (0.5 + r.usefulness) * (FAILURE_WEIGHT if not r.success else 1.0)
        score *= 1 + 0.1 * min(r.seen - 1, 5)          # repeatedly learned lessons are stronger
        score += 0.05 * (i / max(n - 1, 1))            # small recency bonus
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:k]]


def format_lessons(records: list[MemoryRecord]) -> str:
    if not records:
        return "(no relevant past experience yet)"
    lines = []
    for r in records:
        tag = "✅ worked" if r.success else "❌ failed"
        lines.append(f"- [{tag}, usefulness {r.usefulness:.2f}] task: {r.task_goal[:100]} → lesson: {r.lesson}")
    return "\n".join(lines)
