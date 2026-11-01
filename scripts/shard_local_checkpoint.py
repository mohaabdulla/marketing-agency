"""Repack local Safetensors by streaming bytes; do not load tensors into RAM.

Small shards avoid multi-GB temporary allocations and Windows mmap failures.
Original downloaded checkpoints are retained unchanged.
"""
import json
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def shard_file(source, target, prefix, max_bytes=512 * 1024 * 1024):
    target.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as stream:
        header_length = struct.unpack('<Q', stream.read(8))[0]
        if header_length > 100_000_000:
            raise ValueError('Unexpected Safetensors header size')
        header = json.loads(stream.read(header_length))
        data_start = 8 + header_length
        tensors = sorted(((name, spec) for name, spec in header.items() if name != '__metadata__'),
                         key=lambda item: item[1]['data_offsets'][0])
        groups, current, size = [], [], 0
        for name, spec in tensors:
            start, end = spec['data_offsets']
            if start < 0 or end < start or data_start + end > source.stat().st_size:
                raise ValueError('Invalid tensor extent')
            length = end - start
            if current and size + length > max_bytes:
                groups.append(current)
                current, size = [], 0
            current.append((name, spec))
            size += length
        if current:
            groups.append(current)
        weight_map = {}
        total_size = 0
        for index, group in enumerate(groups, 1):
            filename = f'{prefix}-{index:05d}-of-{len(groups):05d}.safetensors'
            new_header = {'__metadata__': header.get('__metadata__', {'format': 'pt'})}
            offset = 0
            for name, spec in group:
                start, end = spec['data_offsets']
                length = end - start
                new_header[name] = {**spec, 'data_offsets': [offset, offset + length]}
                weight_map[name] = filename
                offset += length
            encoded = json.dumps(new_header, separators=(',', ':')).encode('utf-8')
            encoded += b' ' * ((-len(encoded)) % 8)
            temporary = target / (filename + '.tmp')
            with temporary.open('wb') as output:
                output.write(struct.pack('<Q', len(encoded)))
                output.write(encoded)
                for name, spec in group:
                    start, end = spec['data_offsets']
                    stream.seek(data_start + start)
                    remaining = end - start
                    while remaining:
                        block = stream.read(min(16 * 1024 * 1024, remaining))
                        if not block:
                            raise ValueError('Truncated tensor data')
                        output.write(block)
                        remaining -= len(block)
            temporary.replace(target / filename)
            total_size += offset
            print(f'{source.parent.name}: shard {index}/{len(groups)} complete', flush=True)
        result = {'metadata': {'total_size': total_size}, 'weight_map': weight_map}
        (target / f'{prefix}.safetensors.index.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result


def prepare_checkpoint():
    source = ROOT / '.model-cache' / 'realvisxl-v5'
    target = source / 'streamed'
    # Collect only the known top-level components before creating the destination.
    for component in ('scheduler', 'tokenizer', 'tokenizer_2', 'unet', 'vae', 'text_encoder', 'text_encoder_2'):
        destination = target / component
        destination.mkdir(parents=True, exist_ok=True)
        for path in (source / component).iterdir():
            if path.is_file() and path.suffix in ('.json', '.txt', '.model'):
                shutil.copyfile(path, destination / path.name)
        weights = list((source / component).glob('*.fp16.safetensors'))
        if weights:
            prefix = 'model' if component.startswith('text_encoder') else 'diffusion_pytorch_model'
            shard_file(weights[0], destination, prefix)
    shutil.copyfile(source / 'model_index.json', target / 'model_index.json')
    (target / '.download.json').write_text(json.dumps({'variant': None, 'source': 'SG161222/RealVisXL_V5.0', 'sharded': True}), encoding='utf-8')
    print('Streamed checkpoint ready:', target, flush=True)


if __name__ == '__main__':
    prepare_checkpoint()
