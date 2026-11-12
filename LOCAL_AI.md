# Optional local text AI

Manual agency planning works without a model or paid provider.

The CPU llama.cpp adapter uses a separately managed literal-loopback-IP server, never a
hosted fallback. Environment proxies are disabled. Approved claims and selected brief,
brand and glossary fields are untrusted context; the model receives no tools/actions.

Implemented: schema-constrained JSON and Pydantic validation; SSE streaming; actual
received-character counts; one concurrent generation; private client jobs/cancellation;
tokenizer-based context checks; 4096-token application budget; 64–1024 output tokens;
temperature/seed; 120-second overall and 10-second socket inactivity limits.

Each success creates a SEPARATE brief draft with source brief/version, model/revision/
license, instruction, exact input snapshot/hash, prompt-template version and settings. Human edits create
revisions. The source is retained. Run deterministic checks and human review afterward.

Start the external runtime with GPU layers disabled. The app does not manage unloading an
independently started server; stop it explicitly. Existing image/video GPU locking is unchanged.

## Model and explicit setup

[Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF), file
`Qwen3-4B-Q4_K_M.gguf`, is Apache-2.0. Official metadata checked 2026-11-12 reports
2,497,280,256 bytes; reviewed commit `bc640142c66e1fdd12af0bd68f40445458f3869b`.
The installer resolves/records the actual download commit, size and SHA-256.
Suggested RAM: 8 GB for this constrained CPU configuration, an estimate rather than a
measured peak. English/Arabic drafts require language review.

[llama.cpp is MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE).
[Official server docs](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
cover CPU serving, JSON schemas, tokenization and streaming.

No weights/runtime were installed or run in this task. Six real HTTP/SSE protocol tests
use a stub server; they do not establish Qwen inference success or quality. Installed,
reachable, available and verified are separate UI states.

```powershell
winget install llama.cpp
python scripts/setup_local_text.py --download --accept-license
llama-server -m ".model-cache/text/Qwen3-4B-Q4_K_M.gguf" --alias lexnis-qwen3-4b -c 4096 -ngl 0 -t 4 --host 127.0.0.1 --port 8081
```

Set in .env and restart:

```dotenv
LOCAL_TEXT_URL=http://127.0.0.1:8081
LOCAL_TEXT_MODEL=lexnis-qwen3-4b
```

Linux/macOS: install/build the official CPU runtime, then use the same model/server commands.
No Torch or image-worker environment changes are needed.

```powershell
python scripts/verify_local_text.py
python scripts/verify_local_text.py --run-inference
```

Only successful real schema-validated inference writes verification.json. The marker
records revision/hash, output, elapsed time, platform and system RAM; unmeasured peaks stay
null. The operator must serve the registered GGUF under the configured alias: alias
reachability alone is not verification. Use **Create a separate local-model draft** on a
saved brief when available. Full Copy/Script/Storyboard studios remain later phases.

Existing image/video model and verification records remain unchanged. See VIDEO_STUDIO.md,
VIDEO_VERIFICATION.md and REALISM_RESEARCH.md; no new GPU inference was performed here.
