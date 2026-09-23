# Evidence and submission contract

## Status language

- `DOES_NOT_FIT_ESTIMATE`: declared memory need exceeds declared usable memory. The arithmetic is reproducible; the inputs may be wrong.
- `ESTIMATED_FIT_NEEDS_MEASUREMENT`: declared memory fits. No runtime SLO is inferred.
- `QUALITY_FLOOR_NOT_SHOWN`: task-specific quality evidence is absent or below the floor.
- `MEASURED_SLO_FAIL`: an exact-match author-supplied measured receipt misses at least one serving SLO.
- `MEASURED_SERVING_PASS_QUALITY_UNVERIFIED`: the serving receipt passes, but the quality score lacks independently supported evidence.
- `SELF_REPORTED_MEASURED_PASS`: serving and declared quality floors pass, but the serving receipt is still author supplied and has not been independently replayed.

`VERIFIED` is reserved for a later independent replay or identity attestation. v0.1 never emits it. A content digest detects modification after normalization; it does not prove who ran a benchmark or that hardware, model or metric claims were truthful.

## Required benchmark match

All of the following must match exactly: model ID, model revision, quantization, hardware ID, input tokens, output tokens, concurrency, cache state and dataset hash. The comparator rejects missing fields. This follows the comparability intent of [LLM Inference Benchmark](https://github.com/AAH20/llm-inference-benchmark) and adds revision/hardware binding for a passport.

A prospective public submission should also disclose the benchmark command, engine version and flags, tokenizer, hardware topology, GPU driver, CUDA/ROCm stack, warmup, request arrival process, cache configuration, prompt distribution, error handling, run duration, energy method, price source, region, date, and whether the raw trace can be shared. Publish redacted or synthetic prompts when necessary; do not submit secrets, private prompts or customer topology.

## Verification roadmap

1. Re-run the receipt parser from preserved raw results.
2. Bind benchmark artifacts to an identity and code revision using signed attestations.
3. Independently replay a sample of submissions on declared hardware.
4. Display disagreement, uncertainty and stale-result warnings instead of silently replacing results.
5. Separate measured serving from independently evaluated task quality and measured facility economics.

At every stage, reject benchmark gaming and undisclosed conflicts. A public ranking must group by workload and comparison conditions; incompatible results stay visible but are never ranked as if they were equivalent.
