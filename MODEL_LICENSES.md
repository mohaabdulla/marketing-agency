# Model and dependency register

Reviewed 2026-11-12 against primary model/repository sources. Code licenses do not describe
every weight variant; installed, reachable, verified and commercial permission are distinct.

| Component | License/source | This iteration |
| --- | --- | --- |
| Qwen3-4B Q4_K_M | [Official weights](https://huggingface.co/Qwen/Qwen3-4B-GGUF), Apache-2.0 | Adapter only; weights absent/inference unverified |
| llama.cpp | [Official license](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE), MIT | External CPU adapter, no vendored runtime |
| CogVideoX-2B | [Weights](https://huggingface.co/zai-org/CogVideoX-2b), Apache-2.0 | Existing adapter retained; not installed/run here |
| Wan2.1 I2V 14B 480p | [Weights](https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P-Diffusers), Apache-2.0 | Existing adapter; unsupported laptop configuration |
| Existing RealVisXL/Vega | Existing per-model docs/manifests | Not changed/rerun; no new license interpretation |
| FFmpeg/FFprobe | Build-dependent LGPL/GPL; Gyan build includes GPL/libx264 | Existing real CPU exports regression-tested |

Retain applicable licenses/notices when redistributing. Apache/MIT do not grant trademark
rights. The text installer records the weight source/revision/hash and available model-card/
license files. Client/source asset rights remain separate from model licensing.
No stock assets, TTS voices or external self-hosted application code are bundled.

The optional [faster-whisper engine](https://github.com/SYSTRAN/faster-whisper) is MIT and
uses CTranslate2. No Whisper weights are bundled or downloaded by startup/transcription.
Review the exact separately installed weight source/license; a local directory is not an
inference verification. CPU ASR was not run because runtime and weights are absent.

LTX/Wan2.2 evaluation remains in VIDEO_STUDIO.md. Matomo, Mautic, listmonk, Postiz,
ComfyUI and Twenty are not integrated; no current usable-configuration/license claim is made.

The pinned Lucide 1.72.0 browser runtime is served locally for offline operation under ISC;
its full publisher license and version/source metadata are in static/vendor/.
