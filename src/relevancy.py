"""Relevancy check: does a release make an earlier complaint outdated?

Four methods, one per answer to the research question, behind one flag:

  area        same product_area and dated before the release -> outdated
  similarity  cosine similarity between release and complaint >= SIMILARITY_THRESHOLD -> outdated
  llm         the RELEVANCY_CANDIDATES most similar earlier complaints go to an LLM, which
              judges whether the release fixes each one
  hybrid      metadata gates first (platform and plan must overlap), then the llm step on
              the complaints that pass

Releases are processed in date order. Only complaints dated strictly before a release can be
outdated by it, and once a complaint is outdated it stays outdated (no later release reopens it).

Judge versions (llm and hybrid only), chosen with --judge:
  v1    one yes/no answer per complaint: "does this release fully fix it?" (run openai-v1)
  v2    requirements checklist (run v2). The model lists what the customer needs (1 to 4 items,
        the core need first) and checks each one against the release: met, partly, or not met,
        quoting the release. Code, not the model, turns the checklist into a verdict:
          every item met                      -> fixed    (complaint becomes outdated)
          core need met or partly, not all    -> partial  (complaint stays open; a later release
                                                           can still fix it fully)
          core need not met                   -> not fixed
        Built from the v1 mistakes on train: C115 (a related feature for a different property
        type) and C014, C061 (partly fixed, which v1 could only call fixed).
  v2.1  (default) v2 with two changes, both from the v2 mistakes on train:
        - partial needs the core need fully met. The model marked a related feature for a
          different case as "partly" (C115), which v2 turned into partial; in v2.1 a core need
          that is only partly met means not fixed.
        - no extra requirement that the default experience changes. It made v2 call a fully
          fixed complaint partial (C077) and did not change C014 or C061.
  decisions  the OpenAI Decisions API (POST /v1/decisions, model gpt-6-luna). One call per
        release: the release is the input and each candidate complaint is one choice question
        (fixed, partial, not fixed) whose option descriptions carry the v2.1 rules. The API
        returns a choice with a confidence and probabilities but no text, so these checks have
        no quoted evidence or written reason. A separate version of the full agent, added
        2026-11-27 at Quinton's request; built and frozen without tuning rounds.

A judge call that still fails after retries does not stop the run: its candidates are logged as
checks with stage "error" (treated as not fixed), the failure is listed in the run's meta, and a
line is appended to data/status/failed_calls.jsonl.
"""

import json
from datetime import datetime, timezone

import numpy as np

from .config import Config
from .llm import decide, generate
from .status import StatusLog

METHODS = ("area", "similarity", "llm", "hybrid")

JUDGE_SYSTEM_PROMPT = """You check whether a product release fixes specific customer complaints for Tessera, an all-in-one workspace app.

For each complaint, decide whether this release FULLY fixes the specific problem that customer describes.
Be strict:
- A release in the same product area that leaves the customer's specific problem unsolved is NOT a fix.
- Check scope: platforms, plans, views, file types, limits, and anything the release says it does not cover or leaves for a future release.
- A feature request counts as fixed only if the release delivers what the customer asked for.
- If the release only partly addresses the complaint, answer false.
Quote the sentence from the release that supports a true answer. Use an empty string for evidence when the answer is false."""

# OpenAI strict structured output needs an object at the top level, so the verdicts sit under "results".
JUDGE_VERSIONS = ("v1", "v2", "v2.1", "decisions")
CHECKLIST_VERSIONS = ("v2", "v2.1")
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "fixes": {"type": "boolean"},
                    "evidence": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "fixes", "evidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


# v2 prompt. v2.1 is built from it below by dropping the two default-experience instructions.
JUDGE_V2_SYSTEM_PROMPT = """You check whether a product release fixes specific customer complaints for Tessera, an all-in-one workspace app.

Work through each complaint in two steps.

Step 1. List what this customer needs for their problem to be solved: 1 to 4 short requirements, in the customer's terms.
- The first requirement is the core need: the specific thing the customer asks for or the specific problem they hit, including the object it applies to (for example a property type, view, file type, or kind of page) and the situation they are in.
- Add a requirement for scope only when the customer states it or their record shows it: their platform, their plan, a limit or size they mention.
- If the complaint is about how the product behaves by default, include that the default experience changes.
- List only what the customer states or clearly implies. Do not add extras such as documentation, pricing, or polish.

Step 2. Check each requirement against the release text only.
- met: the release clearly delivers this for this customer's case.
- partly: the release delivers some of it, or only in some of the customer's cases.
- not met: the release does not deliver it. When a release lists what it supports (property types, views, platforms, plans, contexts), anything it does not list is not covered. A related feature for a different object, context, platform, or plan does not meet the requirement. An optional setting meets a request for an option, but only partly meets a requirement that the default experience changes.
- Quote the sentence from the release that shows met or partly. Use an empty string for not met.

Be strict and literal. A release in the same product area that sounds related is not enough.
Keep it short: each requirement under 15 words, each quote under 30 words, and the reason one sentence."""

DEFAULT_RULES = (
    "- If the complaint is about how the product behaves by default, include that the default experience changes.\n",
    " An optional setting meets a request for an option, but only partly meets a requirement that the default experience changes.",
)
JUDGE_V21_SYSTEM_PROMPT = JUDGE_V2_SYSTEM_PROMPT
for _rule in DEFAULT_RULES:
    assert _rule in JUDGE_V21_SYSTEM_PROMPT  # fails loudly if the v2 prompt is edited out of sync
    JUDGE_V21_SYSTEM_PROMPT = JUDGE_V21_SYSTEM_PROMPT.replace(_rule, "")

# v2 and v2.1: the model fills in the checklist; code derives the verdict (verdict_from_checklist).
JUDGE_V2_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "requirements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "need": {"type": "string"},
                                "met": {"type": "string", "enum": ["met", "partly", "not met"]},
                                "evidence": {"type": "string"},
                            },
                            "required": ["need", "met", "evidence"],
                            "additionalProperties": False,
                        },
                    },
                    "reason": {"type": "string"},
                },
                "required": ["id", "requirements", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

FIXED, PARTIAL, NOT_FIXED = "fixed", "partial", "not fixed"

# Judge "decisions": the instructions go in as a developer message and the release as the user
# message; each complaint is one choice question. The three options restate the v2.1 rule.
DECISIONS_INSTRUCTIONS = """You check whether a product release fixes specific customer complaints for Tessera, an all-in-one workspace app.
The user message is one release. Each question gives one customer complaint and asks whether this release fixes it.
Judge the customer's core need: the specific thing they ask for or the problem they hit, including the object it applies to (a property type, view, file type, or kind of page) and their situation, platform, and plan.
Be strict and literal. When a release lists what it supports (property types, views, platforms, plans, contexts), anything it does not list is not covered. A related feature for a different object, context, platform, or plan does not fix the complaint. A release in the same product area that sounds related is not enough."""

DECISION_CHOICES = [
    {"value": FIXED, "description": "The release fully delivers what this customer needs, for their case, platform, and plan."},
    {"value": PARTIAL, "description": "The release fully delivers the customer's core need, but a secondary part of what they asked for is missing."},
    {"value": NOT_FIXED, "description": "The release does not fully deliver the customer's core need. This includes a related feature for a different object, context, platform, or plan, and a release in the same area that leaves the problem unsolved."},
]


def verdict_from_checklist(requirements: list[dict], version: str = "v2.1") -> str:
    """Deterministic rule. All met -> fixed. Core need (first item) not met -> not fixed
    (v2.1: also when it is only partly met). Anything else -> partial."""
    if not requirements:
        return NOT_FIXED
    core = requirements[0]["met"]
    if core == "not met" or (version == "v2.1" and core != "met"):
        return NOT_FIXED
    if all(r["met"] == "met" for r in requirements):
        return FIXED
    return PARTIAL


# ---------- helpers ----------


def cosine_matrix(a: list[list[float]], b: list[list[float]]) -> np.ndarray:
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    return a @ b.T


def passes_gates(release: dict, complaint: dict) -> tuple[bool, str]:
    """Metadata gates for the hybrid method. Returns (passes, reason if it fails)."""
    if not set(complaint["platforms"]) & set(release["platforms"]):
        return False, f"platform gate: complaint on {complaint['platforms']}, release ships on {release['platforms']}"
    if not set(complaint["plan"]) & set(release["plan"]):
        return False, f"plan gate: complaint plan {complaint['plan']}, release available on {release['plan']}"
    return True, ""


def format_release(release: dict) -> str:
    return (
        f"id: {release['id']}\ndate: {release['date']}\nproduct_area: {release['product_area']}\n"
        f"platforms: {', '.join(release['platforms'])}\nplans: {', '.join(release['plan'])}\n"
        f"title: {release['title']}\ntext: {release['text']}"
    )


def format_complaint(complaint: dict) -> str:
    return (
        f"id: {complaint['id']}\ndate: {complaint['date']}\nproduct_area: {complaint['product_area']}\n"
        f"platforms: {', '.join(complaint['platforms'])}\nplan: {', '.join(complaint['plan'])}\n"
        f"title: {complaint['title']}\ntext: {complaint['text']}"
    )


def build_judge_prompt(release: dict, candidates: list[dict]) -> str:
    complaints = "\n\n---\n\n".join(format_complaint(c) for c in candidates)
    return (
        f"RELEASE\n\n{format_release(release)}\n\n=====\n\nCOMPLAINTS\n\n{complaints}\n\n=====\n\n"
        f"Return one result per complaint, using its id."
    )


def judge_decisions(cfg: Config, client, release: dict, candidates: list[dict],
                    usage: dict | None = None) -> dict[str, dict]:
    """One Decisions API call per release. Returns {complaint_id: {verdict, evidence, reason, confidence, probabilities}}."""
    questions = [
        {"type": "choice", "name": c["id"], "choices": DECISION_CHOICES,
         "instructions": f"COMPLAINT\n\n{format_complaint(c)}\n\nDoes this release fix this customer's specific problem?"}
        for c in candidates
    ]
    decision = decide(
        client, cfg.decisions_model,
        [{"role": "developer", "content": DECISIONS_INSTRUCTIONS},
         {"role": "user", "content": f"RELEASE\n\n{format_release(release)}"}],
        questions,
    )
    if usage is not None:
        usage["input_tokens"] = usage.get("input_tokens", 0) + decision.usage.input_tokens
        usage["output_tokens"] = usage.get("output_tokens", 0) + decision.usage.output_tokens
    verdicts = {}
    for c, answer in zip(candidates, decision.answers):  # answers come back in question order
        cid = answer.name or c["id"]
        if answer.type != "choice" or answer.choice not in (FIXED, PARTIAL, NOT_FIXED):
            verdicts[cid] = {"verdict": NOT_FIXED, "evidence": "", "reason": f"REFUSAL or unexpected answer: {answer.type}"}
            continue
        verdicts[cid] = {
            "verdict": answer.choice, "evidence": "",
            "reason": f"decisions API: {answer.choice} (confidence {answer.confidence:.2f})",
            "confidence": answer.confidence,
            "probabilities": {p.value: round(p.probability, 4) for p in answer.probabilities},
        }
    for c in candidates:  # a candidate with no answer is treated as "not fixed" and flagged
        verdicts.setdefault(c["id"], {"verdict": NOT_FIXED, "evidence": "", "reason": "MISSING: no answer returned"})
    return verdicts


def judge(cfg: Config, client, release: dict, candidates: list[dict], version: str = "v2.1",
          usage: dict | None = None) -> dict[str, dict]:
    """One model call per release. Returns {complaint_id: {verdict, evidence, reason, requirements?}}."""
    if not candidates:
        return {}
    if version == "decisions":
        return judge_decisions(cfg, client, release, candidates, usage)
    v2 = version in CHECKLIST_VERSIONS
    system = {"v1": JUDGE_SYSTEM_PROMPT, "v2": JUDGE_V2_SYSTEM_PROMPT, "v2.1": JUDGE_V21_SYSTEM_PROMPT}[version]
    text = generate(
        client, cfg.relevancy_model, system,
        build_judge_prompt(release, candidates), temperature=0.0,
        json_schema=JUDGE_V2_SCHEMA if v2 else JUDGE_SCHEMA,
        schema_name="judge_checklist" if v2 else "judge_verdicts",
    )
    results = json.loads(text or "{}").get("results", [])
    wanted = {c["id"] for c in candidates}
    verdicts = {}
    for r in results:
        if r.get("id") not in wanted:
            continue
        if v2:
            reqs = r["requirements"]
            evidence = " | ".join(q["evidence"] for q in reqs if q["met"] != "not met" and q["evidence"])
            verdicts[r["id"]] = {"verdict": verdict_from_checklist(reqs, version), "evidence": evidence,
                                 "reason": r.get("reason", ""), "requirements": reqs}
        else:
            verdicts[r["id"]] = {"verdict": FIXED if r["fixes"] else NOT_FIXED,
                                 "evidence": r.get("evidence", ""), "reason": r.get("reason", "")}
    # A candidate the model skipped is treated as "not fixed" and flagged in the log.
    for cid in wanted - verdicts.keys():
        verdicts[cid] = {"verdict": NOT_FIXED, "evidence": "", "reason": "MISSING: model returned no verdict"}
    return verdicts


# ---------- the update loop ----------


def log_failure(cfg: Config, entry: dict) -> None:
    path = cfg.status_dir / "failed_calls.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def run_relevancy(cfg: Config, records: list[dict], method: str, client=None, tag: str | None = None,
                  judge_version: str = "v2.1") -> StatusLog:
    """Process every release in date order and append a tagged run to data/status/<method>.jsonl.

    `records` are store records (with vectors). `client` is only needed for llm and hybrid.
    `judge_version` (v1, v2, v2.1, or decisions) only matters for llm and hybrid.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if judge_version not in JUDGE_VERSIONS:
        raise ValueError(f"judge_version must be one of {JUDGE_VERSIONS}")
    uses_judge = method in ("llm", "hybrid")
    if method in ("llm", "hybrid") and client is None:
        raise ValueError(f"method {method} needs an OpenAI client")

    complaints = [r for r in records if r["source_type"] == "complaint"]
    releases = sorted(
        (r for r in records if r["source_type"] == "changelog"), key=lambda r: (r["date"], r["id"])
    )
    sims = cosine_matrix([r["vector"] for r in releases], [c["vector"] for c in complaints])

    log = StatusLog(cfg.status_dir / f"{method}.json")
    log.start_run(
        {
            "method": method,
            "similarity_threshold": cfg.similarity_threshold if method == "similarity" else None,
            "candidates_per_release": cfg.relevancy_candidates if method in ("llm", "hybrid") else None,
            "relevancy_model": (cfg.decisions_model if judge_version == "decisions" else cfg.relevancy_model)
            if uses_judge else None,
            "judge": judge_version if uses_judge else None,
            "embedding_model": cfg.embedding_model,
            "complaints_checked": len(complaints),
        },
        tag,
    )
    outdated: set[str] = set()
    partial: set[str] = set()  # partly fixed; still open, so a later release can fix them fully
    # Counts of (release, complaint) pairs, for the hybrid gate-vs-model breakdown.
    counts = {"gated_all": 0, "gated_in_top": 0, "sent_to_llm": 0, "llm_calls": 0, "failed_calls": 0}
    usage: dict = {}  # token totals, filled by the decisions judge (for the cost comparison)
    failures: list[dict] = []

    for i, release in enumerate(releases):
        # Earlier complaints that are still current when this release ships.
        open_idx = [
            j for j, c in enumerate(complaints) if c["date"] < release["date"] and c["id"] not in outdated
        ]
        decisions: list[dict] = []  # {id, fixes, verdict, score, reason, evidence}

        if method == "area":
            for j in open_idx:
                c = complaints[j]
                if c["product_area"] == release["product_area"]:
                    decisions.append(
                        {"id": c["id"], "fixes": True, "score": float(sims[i, j]), "reason": "same product area", "evidence": ""}
                    )

        elif method == "similarity":
            for j in open_idx:
                score = float(sims[i, j])
                if score >= cfg.similarity_threshold:
                    decisions.append(
                        {"id": complaints[j]["id"], "fixes": True, "score": score,
                         "reason": f"similarity {score:.3f} >= {cfg.similarity_threshold}", "evidence": ""}
                    )

        else:  # llm or hybrid
            pool = open_idx
            if method == "hybrid":
                # Complaints the llm method would have judged; gate rejections among them are logged
                # so you can see which near misses the gates caught before any model call.
                would_judge = set(sorted(open_idx, key=lambda j: -sims[i, j])[: cfg.relevancy_candidates])
                pool = []
                for j in open_idx:
                    ok, why = passes_gates(release, complaints[j])
                    if ok:
                        pool.append(j)
                        continue
                    counts["gated_all"] += 1
                    if j in would_judge:
                        counts["gated_in_top"] += 1
                        decisions.append(
                            {"id": complaints[j]["id"], "fixes": False, "score": float(sims[i, j]),
                             "reason": why, "evidence": "", "stage": "gate"}
                        )
            top = sorted(pool, key=lambda j: -sims[i, j])[: cfg.relevancy_candidates]
            candidates = [complaints[j] for j in top]
            try:
                verdicts = judge(cfg, client, release, candidates, judge_version, usage)
                stage, error = "llm", ""
            except Exception as e:  # noqa: BLE001 - any failure is logged and the run continues
                error = f"{type(e).__name__}: {e}"[:500]
                verdicts = {c["id"]: {"verdict": NOT_FIXED, "reason": f"ERROR: {error}"} for c in candidates}
                stage = "error"
                entry = {"time": datetime.now(timezone.utc).isoformat(), "tag": log.meta["tag"], "method": method,
                         "release": release["id"], "complaints": [c["id"] for c in candidates], "error": error}
                failures.append(entry)
                log_failure(cfg, entry)
                counts["failed_calls"] += 1
                print(f"  FAILED {release['id']}: {error}")
            if candidates:
                counts["llm_calls"] += 1
                counts["sent_to_llm"] += len(candidates)
            for j in top:
                v = verdicts[complaints[j]["id"]]
                d = {"id": complaints[j]["id"], "fixes": v["verdict"] == FIXED, "verdict": v["verdict"],
                     "score": float(sims[i, j]), "reason": v.get("reason", ""), "evidence": v.get("evidence", ""),
                     "stage": stage}
                for key in ("requirements", "confidence", "probabilities"):
                    if key in v:
                        d[key] = v[key]
                decisions.append(d)

        for d in decisions:
            log.add_check({"release": release["id"], "release_date": release["date"], "complaint": d["id"], **d})
            if d["fixes"]:
                log.mark_outdated(d["id"], release["id"], release["date"], d["reason"], d["evidence"])
                outdated.add(d["id"])
            elif d.get("verdict") == PARTIAL and d["id"] not in partial:
                # First partial fix only; the complaint stays open for a later full fix.
                log.mark_partial(d["id"], release["id"], release["date"], d["reason"], d["evidence"])
                partial.add(d["id"])

        n_fixed = sum(d["fixes"] for d in decisions)
        n_partial = sum(d.get("verdict") == PARTIAL for d in decisions)
        note = f", {n_partial} partial" if n_partial else ""
        print(f"  {release['date']} {release['id']}: {n_fixed} outdated{note}", flush=True)  # flush: progress shows even when output goes to a file

    if method in ("llm", "hybrid"):
        log.meta["counts"] = {**counts, **usage}
        log.meta["failures"] = failures
    log.save()
    n_out = sum(e.get("status", "outdated") == "outdated" for e in log.events)
    print(f"{method} [{log.meta['tag']}]: {n_out} complaints marked outdated, {len(partial)} partial -> {log.path}")
    if failures:
        print(f"  {len(failures)} judge call(s) failed after retries; see {cfg.status_dir / 'failed_calls.jsonl'}")
    return log
