"""Deterministic fit, benchmark matching, and decision labeling."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

ENGINE_VERSION = "runproof-v0.1"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def positive(value: Any, name: str, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} must be {'nonnegative' if allow_zero else 'positive'}")
    return float(value)


def validate(models: list[dict], hardware: list[dict], workload: dict) -> None:
    if not models or not hardware or len(models) * len(hardware) > 5000:
        raise ValueError("catalog must be nonempty and within the 5000-candidate work budget")
    for collection, label in ((models, "model"), (hardware, "hardware")):
        ids = [item.get("id") for item in collection]
        if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"{label} IDs must be unique nonempty strings")
    for model in models:
        if not isinstance(model.get("revision"), str) or not model["revision"]:
            raise ValueError("model revision is required")
        for key in ("parameters_b", "bytes_per_parameter", "kv_gb_per_1k_tokens", "runtime_overhead_gb"):
            positive(model.get(key), key, allow_zero=key == "kv_gb_per_1k_tokens")
        quality = model.get("quality", {})
        positive(quality.get("score"), "quality.score", allow_zero=True)
        if quality["score"] > 1 or quality.get("evidence") not in {"illustrative", "self_reported", "independent"}:
            raise ValueError("quality score must be 0..1 with a valid evidence label")
    for device in hardware:
        positive(device.get("usable_memory_gb"), "usable_memory_gb")
        positive(device.get("hourly_usd"), "hourly_usd", allow_zero=True)
        if device.get("evidence") not in {"illustrative", "provider_quote", "measured"}:
            raise ValueError("hardware requires an evidence label")
    for key in ("context_tokens", "concurrent_sessions", "input_tokens", "output_tokens", "max_ttft_p99_ms", "max_itl_p99_ms", "monthly_requests"):
        positive(workload.get(key), key)
    positive(workload.get("min_success_rate"), "min_success_rate", allow_zero=True)
    positive(workload.get("min_quality"), "min_quality", allow_zero=True)
    if workload["min_success_rate"] > 1 or workload["min_quality"] > 1:
        raise ValueError("rate and quality floors must be 0..1")
    if not workload.get("task") or not workload.get("cache_state"):
        raise ValueError("workload task and cache_state are required")


def estimate_memory(model: dict, workload: dict) -> dict:
    """Conservative full-context, all-sessions-active budget; not a speed prediction."""
    weights = model["parameters_b"] * model["bytes_per_parameter"]
    kv = model["kv_gb_per_1k_tokens"] * workload["context_tokens"] / 1000 * workload["concurrent_sessions"]
    overhead = model["runtime_overhead_gb"]
    return {"weights_gb": round(weights, 3), "kv_budget_gb": round(kv, 3),
            "runtime_overhead_gb": round(overhead, 3), "total_gb": round(weights + kv + overhead, 3)}


def verify_benchmark(receipt: dict) -> None:
    """Validate the existing llm-inference-benchmark content digest, not identity."""
    if receipt.get("schema_version") != "0.1.0" or not isinstance(receipt.get("integrity"), dict):
        raise ValueError("unsupported canonical benchmark receipt")
    if receipt["integrity"].get("algorithm") != "sha256":
        raise ValueError("unsupported benchmark digest algorithm")
    body = {k: v for k, v in receipt.items() if k not in {"integrity", "normalized_at"}}
    if digest(body) != receipt["integrity"].get("digest"):
        raise ValueError("benchmark content digest mismatch")
    if receipt.get("provenance") not in {"measured", "vendor-reported", "modeled", "unverified"}:
        raise ValueError("invalid benchmark provenance")


def benchmark_match(receipt: dict, model: dict, device: dict, workload: dict) -> list[str]:
    context = receipt.get("context", {})
    expected = {
        "model": model["id"], "model_revision": model["revision"],
        "quantization": model["quantization"], "hardware": device["id"],
        "input_tokens": workload["input_tokens"], "output_tokens": workload["output_tokens"],
        "concurrency": workload["concurrent_sessions"], "cache_state": workload["cache_state"],
        "dataset_hash": workload["dataset_hash"],
    }
    return [key for key, value in expected.items() if context.get(key) != value]


def build(models: list[dict], hardware: list[dict], workload: dict, benchmarks: list[dict] | None = None) -> dict:
    validate(models, hardware, workload)
    benchmarks = benchmarks or []
    for receipt in benchmarks:
        verify_benchmark(receipt)
    candidates = []
    for model in models:
        for device in hardware:
            memory = estimate_memory(model, workload)
            fit = memory["total_gb"] <= device["usable_memory_gb"]
            quality = model["quality"]
            matches = [b for b in benchmarks if not benchmark_match(b, model, device, workload)]
            measured = [b for b in matches if b["provenance"] == "measured"]
            result = {
                "model": model["id"], "revision": model["revision"],
                "quantization": model["quantization"], "hardware": device["id"],
                "memory": memory, "available_memory_gb": device["usable_memory_gb"],
                "fit": fit, "quality": quality, "hardware_evidence": device["evidence"],
                "benchmark_count": len(matches), "status": "ESTIMATED_FIT_NEEDS_MEASUREMENT",
                "reasons": [], "cost_per_successful_request_usd": None,
                "evidence": "estimate_only", "benchmark_digest": None,
            }
            if not fit:
                result["status"] = "DOES_NOT_FIT_ESTIMATE"
                result["reasons"].append("estimated memory exceeds declared usable memory")
            if quality.get("task") != workload["task"] or quality["score"] < workload["min_quality"]:
                if fit:
                    result["status"] = "QUALITY_FLOOR_NOT_SHOWN"
                result["reasons"].append("task-specific quality floor not shown")
            if measured and fit and quality.get("task") == workload["task"] and quality["score"] >= workload["min_quality"]:
                # Latest normalized receipt is not inherently best; use first supplied and expose digest.
                b = measured[0]
                metrics = b["metrics"]
                success = metrics.get("success_rate")
                ttft = metrics.get("ttft_p99_ms")
                itl = metrics.get("itl_p99_ms")
                if all(isinstance(x, (int, float)) and math.isfinite(x) for x in (success, ttft, itl)):
                    result["status"] = "SELF_REPORTED_MEASURED_PASS" if (
                        success >= workload["min_success_rate"] and ttft <= workload["max_ttft_p99_ms"]
                        and itl <= workload["max_itl_p99_ms"]
                    ) else "MEASURED_SLO_FAIL"
                    result["evidence"] = "measured_self_reported_not_independently_verified"
                    result["benchmark_digest"] = b["integrity"]["digest"]
                    result["cost_per_successful_request_usd"] = b.get("economics", {}).get("cost_per_successful_request_usd")
                    result["metrics"] = {"success_rate": success, "ttft_p99_ms": ttft, "itl_p99_ms": itl}
                else:
                    result["reasons"].append("measured receipt lacks finite SLO metrics")
            if quality["evidence"] != "independent" and result["status"] == "SELF_REPORTED_MEASURED_PASS":
                result["status"] = "MEASURED_SERVING_PASS_QUALITY_UNVERIFIED"
                result["reasons"].append("quality score lacks independent evidence")
            candidates.append(result)
    order = {"SELF_REPORTED_MEASURED_PASS": 0, "MEASURED_SERVING_PASS_QUALITY_UNVERIFIED": 1,
             "ESTIMATED_FIT_NEEDS_MEASUREMENT": 2, "MEASURED_SLO_FAIL": 3,
             "QUALITY_FLOOR_NOT_SHOWN": 4, "DOES_NOT_FIT_ESTIMATE": 5}
    candidates.sort(key=lambda c: (order[c["status"]], c["cost_per_successful_request_usd"]
                                   if isinstance(c["cost_per_successful_request_usd"], (int, float)) else float("inf"),
                                   c["model"], c["hardware"]))
    passport = {
        "schema_version": "0.1.0", "engine_version": ENGINE_VERSION,
        "authority": "ADVISORY_ONLY_NOT_AUTHORIZED", "claim_boundary": "No bundled hardware measurements or verified quality claims",
        "input_digest": digest({"models": models, "hardware": hardware, "workload": workload,
                                "benchmark_digests": [b["integrity"]["digest"] for b in benchmarks]}),
        "workload": workload, "candidate_count": len(candidates), "candidates": candidates,
        "definitions": {"measured": "author-supplied receipt with intact content digest; not independent attestation",
                        "estimated": "formula-based fit with user-supplied assumptions; no runtime SLO prediction",
                        "verified": "reserved for independent replay or signed attestation; not implemented"},
    }
    passport["passport_digest"] = digest(passport)
    return passport
