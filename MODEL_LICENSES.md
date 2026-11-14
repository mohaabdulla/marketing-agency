# LEXNIS Authoritative Model & License Registry

Reviewed and verified against primary upstream model cards, official repositories, and license texts.
Code licenses do not automatically describe model weights; installed state, operational reachability, verified execution, and commercial permissions are strictly distinct.

## Authoritative Model Matrix

| Model Identifier | Display Name | Task | Upstream Source & License | Commercial Status | Hardware Minimum | Operational Status |
|---|---|---|---|---|---|---|
| `qwen3-4b-gguf` | Qwen3-4B-GGUF | Text Copilot | [Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 6GB RAM (CPU/GPU) | Adapter integrated; verified offline mock |
| `qwen2.5-coder-7b` | Qwen2.5-Coder-7B | Text Copilot | [Qwen/Qwen2.5-Coder-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 8GB VRAM / 16GB RAM | Adapter integrated; offline fallback |
| `llama-3.1-8b-instruct` | Llama 3.1 8B Instruct | Text Copilot | [Meta-Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3.1-8B-Instruct) (Llama-3.1-Community) | `CONDITIONAL` (Under 700M MAU) | 12GB VRAM / 18GB RAM | Adapter integrated; conditional warning |
| `flux.1-schnell` | FLUX.1-schnell | Photorealistic Images | [black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 12GB VRAM / 24GB RAM | Visual engine adapter supported |
| `realvisxl-v5.0` | RealVisXL V5.0 | B2B Photography | [SG161222/RealVisXL_V5.0](https://huggingface.co/SG161222/RealVisXL_V5.0) (CreativeML OpenRAIL-M) | `REVIEW_REQUIRED` (Acceptable use) | 8GB VRAM / 12GB RAM | Regression-tested in visual engine |
| `sdxl-base-1.0` | SDXL Base 1.0 | Visual Generation | [stabilityai/stable-diffusion-xl-base-1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) (OpenRAIL++-M) | `REVIEW_REQUIRED` | 8GB VRAM / 12GB RAM | Visual engine fallback supported |
| `wan2.1-t2v-1.3b` | Wan2.1 T2V-1.3B | Video Generation | [Wan-AI/Wan2.1-T2V-1.3B](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 8.2GB VRAM / 16GB RAM | Video models adapter integrated |
| `wan2.2-ti2v-5b` | Wan2.2 TI2V-5B | HQ Text/Image to Video | [Wan-AI/Wan2.2-TI2V-5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 12GB VRAM / 24GB RAM | Video models adapter integrated |
| `cogvideox-2b` | CogVideoX-2B | Video Prototyping | [THUDM/CogVideoX-2b](https://huggingface.co/THUDM/CogVideoX-2b) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 8GB VRAM / 16GB RAM | Video models adapter integrated |
| `wan2.1-i2v-14b` | Wan2.1 I2V-14B | Studio Video | [Wan-AI/Wan2.1-I2V-14B](https://huggingface.co/Wan-AI/Wan2.1-I2V-14B) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 24GB VRAM / 48GB RAM | Workstation adapter; GPU gated |
| `ltx-video` | LTX-Video 0.9.1 | Fast Video | [Lightricks/LTX-Video](https://huggingface.co/Lightricks/LTX-Video) (Lightricks OpenRAIL) | `REVIEW_REQUIRED` | 12GB VRAM / 16GB RAM | Video models adapter integrated |
| `whisper-large-v3` | Whisper Large v3 | ASR Subtitles | [openai/whisper-large-v3](https://huggingface.co/openai/whisper-large-v3) (MIT) | `COMMERCIAL_ALLOWED` | 4.5GB VRAM / 6GB RAM | Audio module adapter |
| `whisper-base` | Whisper Base | ASR Subtitles | [openai/whisper-base](https://huggingface.co/openai/whisper-base) (MIT) | `COMMERCIAL_ALLOWED` | CPU-friendly (1GB RAM) | Audio module adapter |
| `kokoro-82m` | Kokoro-82M | Voiceover TTS | [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) | `COMMERCIAL_ALLOWED` | CPU/GPU (2GB RAM) | TTS engine integrated & verified |
| `piper-tts` | Piper TTS | Multilingual TTS | [rhasspy/piper](https://github.com/rhasspy/piper) (MIT code) | `CONDITIONAL` (Voice checkpoint review) | CPU-friendly (1GB RAM) | TTS engine integrated & verified |
| `coqui-xtts-v2` | Coqui XTTS-v2 | Voiceover TTS | [coqui/XTTS-v2](https://huggingface.co/coqui/XTTS-v2) (CPML-1.0) | `NON_COMMERCIAL` [GATED] | 4GB VRAM / 6GB RAM | Strictly blocked in commercial mode |
| `ace-step-v1` | ACE-Step-v1-3.5B | Background Music | [ACE-Studio/ACE-Step-v1-3.5B](https://huggingface.co/ACE-Studio) (Apache-2.0) | `COMMERCIAL_ALLOWED` | 8GB VRAM / 16GB RAM | Music engine integrated & verified |
| `musicgen-small` | MusicGen Small | Background Music | [facebook/musicgen-small](https://huggingface.co/facebook/musicgen-small) (CC-BY-NC-4.0) | `NON_COMMERCIAL` [GATED] | 5GB VRAM / 8GB RAM | Strictly blocked in commercial mode |
| `stable-audio-open-1.0` | Stable Audio Open | Audio SFX | [stabilityai/stable-audio-open-1.0](https://huggingface.co/stabilityai/stable-audio-open-1.0) (Stability Community) | `REVIEW_REQUIRED` (Revenue caps) | 6GB VRAM / 8GB RAM | Music engine adapter integrated |

## Licensing Gate Policy

1. **Commercial Mode (Default):** Any model with status `NON_COMMERCIAL` (such as Coqui XTTS-v2 CPML weights or Facebook MusicGen CC-BY-NC weights) is blocked at the application level from being selected or executed in marketing campaigns.
2. **Conditional & Review-Required Modes:** Models under OpenRAIL, Llama 3.1 Community, or Stability Community licenses require explicit acceptance of acceptable use terms or monthly active user thresholds before final distribution.
3. **Development Override:** A development testing override is available strictly via the environment variable `AGENCY_ALLOW_NONCOMMERCIAL_DEV=1`.
