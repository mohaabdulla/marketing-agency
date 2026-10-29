"""Install an isolated CUDA image runtime and download only Vega's fp16 weights."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv-image' / 'Scripts' / 'python.exe'

def run(*args):
    subprocess.run([str(PYTHON), *args], cwd=ROOT, check=True)

if __name__ == '__main__':
    run('-m', 'pip', 'install', '--no-cache-dir', 'torch==2.6.0', 'torchvision==0.21.0',
        '--index-url', 'https://download.pytorch.org/whl/cu124')
    run('-m', 'pip', 'install', '--no-cache-dir', 'diffusers==0.36.0',
        'transformers>=4.57,<5', 'accelerate>=1.2,<2', 'Pillow>=10,<13',
        'huggingface_hub>=0.34,<1', 'hf_xet>=1.1,<2', 'safetensors>=0.4')
    run('-c', "from huggingface_hub import snapshot_download; "
        "snapshot_download('segmind/Segmind-Vega', local_dir='.model-cache/segmind-vega', "
        "allow_patterns=['*.json','*.txt','*.model','*.fp16.safetensors','tokenizer/*','tokenizer_2/*'])")
    run('-c', "import torch; print('Local CUDA ready:', torch.cuda.is_available()); "
        "assert torch.cuda.is_available(), 'CUDA is not available in the isolated runtime'")
    # The normal server Python owns composition; this command verifies actual
    # inference before enabling the model in the dashboard.
    import sys
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'verify_local_images.py')], cwd=ROOT, check=True)
