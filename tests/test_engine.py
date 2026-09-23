import copy
import json
import unittest
from pathlib import Path

from runproof.engine import benchmark_match, build, digest, estimate_memory, verify_benchmark
from runproof.render import render

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    return [json.loads((ROOT / "examples" / name).read_text()) for name in ("models.json", "hardware.json", "workload.json")]


def measured_receipt(model, device, workload):
    body = {
        "schema_version": "0.1.0", "provenance": "measured", "tool": "vllm",
        "context": {"model": model["id"], "model_revision": model["revision"],
                    "quantization": model["quantization"], "hardware": device["id"],
                    "input_tokens": workload["input_tokens"], "output_tokens": workload["output_tokens"],
                    "concurrency": workload["concurrent_sessions"], "cache_state": workload["cache_state"],
                    "dataset_hash": workload["dataset_hash"]},
        "metrics": {"success_rate": 0.995, "ttft_p99_ms": 400, "itl_p99_ms": 35},
        "economics": {"cost_per_successful_request_usd": 0.001}, "disclosure": "test-only fixture",
    }
    return {**body, "integrity": {"algorithm": "sha256", "digest": digest(body)}, "normalized_at": "2026-09-23T00:00:00Z"}


class RunProofTests(unittest.TestCase):
    def test_estimates_and_determinism(self):
        models, devices, work = fixtures()
        passport = build(models, devices, work)
        self.assertEqual(passport, build(models, devices, work))
        self.assertEqual(passport["candidate_count"], 6)
        self.assertTrue(any(c["status"] == "DOES_NOT_FIT_ESTIMATE" for c in passport["candidates"]))
        self.assertTrue(any(c["status"] == "ESTIMATED_FIT_NEEDS_MEASUREMENT" for c in passport["candidates"]))
        self.assertTrue(all(c["evidence"] == "estimate_only" for c in passport["candidates"]))

    def test_exact_match_required_for_measured_result(self):
        models, devices, work = fixtures()
        receipt = measured_receipt(models[0], devices[0], work)
        self.assertEqual(benchmark_match(receipt, models[0], devices[0], work), [])
        passport = build(models, devices, work, [receipt])
        match = next(c for c in passport["candidates"] if c["model"] == models[0]["id"] and c["hardware"] == devices[0]["id"])
        self.assertEqual(match["status"], "MEASURED_SERVING_PASS_QUALITY_UNVERIFIED")
        self.assertEqual(sum(c["benchmark_count"] for c in passport["candidates"]), 1)

    def test_tamper_detection(self):
        models, devices, work = fixtures()
        receipt = measured_receipt(models[0], devices[0], work)
        receipt["metrics"]["ttft_p99_ms"] = 200
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify_benchmark(receipt)

    def test_slo_failure_and_independent_quality(self):
        models, devices, work = fixtures()
        models[0]["quality"]["evidence"] = "independent"
        receipt = measured_receipt(models[0], devices[0], work)
        receipt["metrics"]["ttft_p99_ms"] = 600
        receipt["integrity"]["digest"] = digest({k: v for k, v in receipt.items() if k not in {"integrity", "normalized_at"}})
        status = next(c["status"] for c in build(models, devices, work, [receipt])["candidates"] if c["model"] == models[0]["id"] and c["hardware"] == devices[0]["id"])
        self.assertEqual(status, "MEASURED_SLO_FAIL")

    def test_html_escapes_untrusted_names(self):
        models, devices, work = fixtures()
        work["name"] = "<script>alert(1)</script>"
        page = render(build(models, devices, work))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_invalid_numbers_rejected(self):
        models, devices, work = fixtures()
        devices[0]["usable_memory_gb"] = float("nan")
        with self.assertRaises(ValueError):
            build(models, devices, work)


if __name__ == "__main__":
    unittest.main()
