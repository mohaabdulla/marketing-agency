import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient
import campaign_generator as engine
from server import app, render_path
from visual_engine import photo_direction, open_model_image, cloudflare_image, model_setup, LOCAL_MODEL, REALISM_MODEL, local_render_dimensions, photography_conditioning


class CampaignTests(unittest.TestCase):
    def test_checkpoint_sharding_preserves_tensor_bytes(self):
        import json
        import struct
        from scripts.shard_local_checkpoint import shard_file
        payload = bytes(range(32))
        header = {'__metadata__': {'format': 'pt'},
                  'a': {'dtype': 'F16', 'shape': [8], 'data_offsets': [0, 16]},
                  'b': {'dtype': 'F16', 'shape': [8], 'data_offsets': [16, 32]}}
        encoded = json.dumps(header).encode()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.safetensors'
            source.write_bytes(struct.pack('<Q', len(encoded)) + encoded + payload)
            destination = Path(directory) / 'shards'
            result = shard_file(source, destination, 'model', max_bytes=16)
            self.assertEqual(result['metadata']['total_size'], 32)
            self.assertEqual(set(result['weight_map']), {'a', 'b'})
            for key, expected in [('a', payload[:16]), ('b', payload[16:])]:
                raw = (destination / result['weight_map'][key]).read_bytes()
                size = struct.unpack('<Q', raw[:8])[0]
                shard_header = json.loads(raw[8:8+size])
                self.assertEqual(shard_header[key]['shape'], [8])
                self.assertEqual(raw[8+size:], expected)
            self.assertEqual(source.read_bytes(), struct.pack('<Q', len(encoded)) + encoded + payload)

    def test_windows_tensor_reader_overrides_explicit_mmap(self):
        from scripts.windows_tensor_reader import pread_reader
        from unittest.mock import Mock
        original = Mock(return_value='safe tensor context')
        wrapped = pread_reader(original)
        self.assertEqual(wrapped('model.safetensors', framework='pt', backend='mmap'), 'safe tensor context')
        original.assert_called_once_with('model.safetensors', framework='pt', backend='pread')

    def test_health_recommends_verified_local_engine(self):
        with patch.dict(os.environ, {'IMAGE_MODEL': ''}), patch('server.preferred_local_model', return_value=LOCAL_MODEL), TestClient(app) as client:
            self.assertEqual(client.get('/api/health').json()['default_image_model'], LOCAL_MODEL)

    def test_realism_render_uses_sdxl_native_sizes(self):
        self.assertEqual(local_render_dimensions(1536, 864, REALISM_MODEL), (1344, 768))
        self.assertEqual(local_render_dimensions(1080, 1350, REALISM_MODEL), (896, 1152))
        self.assertEqual(local_render_dimensions(1080, 1080, REALISM_MODEL), (1024, 1024))
        self.assertEqual(local_render_dimensions(1536, 864, LOCAL_MODEL), (1024, 576))

    def test_long_prompt_keeps_product_and_photographic_direction(self):
        class Tokenizer:
            model_max_length = 77
            def encode(self, text, add_special_tokens=False):
                return text.split()
        primary, secondary, negative, compacted = photography_conditioning('Tesla Model 3 blue sedan ' + 'coastal road ' * 120, Tokenizer(), Tokenizer())
        self.assertTrue(primary.startswith('Tesla Model 3'))
        self.assertIn('balanced exposure', primary)
        self.assertTrue(compacted)
        for text in (primary, secondary, negative):
            self.assertLessEqual(len(text.split()), 75)

    def test_local_model_requires_verified_weights(self):
        with patch('visual_engine.local_model_ready', return_value=False):
            self.assertFalse(model_setup(LOCAL_MODEL)['configured'])
        with patch('visual_engine.local_model_ready', return_value=True):
            self.assertTrue(model_setup(LOCAL_MODEL)['configured'])

    def test_local_model_uses_isolated_runtime(self):
        studio = engine.LexnisCampaignStudio()
        with patch('campaign_generator.local_image', return_value=(b'local image', True)) as render:
            self.assertEqual(studio._fetch_image_bytes('Blue Tesla', 42, LOCAL_MODEL), (b'local image', True))
            render.assert_called_once()

    def test_compiled_stylesheet_is_served(self):
        with TestClient(app) as client:
            response = client.get('/static/tailwind.css')
            self.assertEqual(response.status_code, 200)
            self.assertIn('text/css', response.headers['content-type'])
            self.assertIn('.bg-obsidian-950', response.text)
            self.assertNotIn('cdn.tailwindcss.com', client.get('/').text)

    def test_cloudflare_requires_both_credentials(self):
        with patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID': '', 'CLOUDFLARE_API_TOKEN': 'token'}):
            self.assertFalse(model_setup('cf:flux-schnell')['configured'])

    def test_expected_render_failure_is_not_http_500(self):
        with TestClient(app) as client, patch.object(engine.LexnisCampaignStudio, 'render_image', side_effect=RuntimeError('Set Cloudflare credentials')):
            response = client.post('/api/render', json={'visual_prompt': 'Car on coastal road', 'seed': 1})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['image_status'], 'unavailable')
            self.assertEqual(response.json()['warnings'], ['Set Cloudflare credentials'])
            self.assertEqual(response.json()['image_url'], '')

    def test_requested_product_is_preserved(self):
        self.assertEqual(engine.detect_brand_and_product('Tesla Model 3 coastal ad')[1], 'Tesla Model 3')
        self.assertEqual(engine.clean_product_headline('Cybercab', 'Tesla Model 3', 'Tesla'), 'TESLA MODEL 3')
        self.assertEqual(engine.detect_brand_and_product('Research Tesla')[1], '')

    def test_scene_is_preserved(self):
        prompt = photo_direction('blue Tesla Model 3', 'coastal sunset', 'Tesla')
        self.assertIn('blue Tesla Model 3', prompt)
        self.assertIn('35mm', prompt)
        self.assertNotIn('Cybercab', prompt)
        self.assertNotIn('macro', prompt)

    def test_image_failure_keeps_copy_and_export(self):
        studio = engine.LexnisCampaignStudio()
        with patch.object(studio, 'build_brief', return_value={'product_name': 'Tesla Model 3'}), \
             patch.object(studio, 'collaborative_generation', return_value=({'hook': 'Take the scenic route.', 'caption': 'Explore the coast.', 'image_headline': 'Model 3'}, [], [])), \
             patch.object(studio, '_fetch_image_bytes', side_effect=RuntimeError('Provider unavailable')):
            asset = studio.generate_campaign('Blue Tesla Model 3 coastal sunset', use_search=False, seed=1)
        self.assertEqual(asset.hook, 'Take the scenic route.')
        self.assertEqual(asset.image_status, 'unavailable')
        self.assertEqual(asset.image_url, '')
        self.assertTrue(asset.warnings)
        with tempfile.TemporaryDirectory() as directory:
            files = studio.export_campaign(asset, directory)
            self.assertIn('caption', files)
            self.assertNotIn('image', files)

    def test_render_formats_and_cache(self):
        buffer = io.BytesIO()
        Image.new('RGB', (1536, 1024), '#647d92').save(buffer, 'JPEG')
        studio = engine.LexnisCampaignStudio()
        with tempfile.TemporaryDirectory() as directory, patch.object(studio, '_fetch_image_bytes', return_value=(buffer.getvalue(), True)) as fetch:
            paths = []
            for name, dimensions in engine.FORMATS.items():
                post, clean, watermark_free = studio.render_image('Blue sedan on coastal road', 42,
                    headline='TESLA MODEL 3', brand='Tesla', out_dir=Path(directory), output_format=name)
                with Image.open(post) as image:
                    self.assertEqual(image.size, dimensions)
                paths.append(clean)
                self.assertTrue(watermark_free)
            studio.render_image('Blue sedan on coastal road', 42, headline='TESLA MODEL 3', brand='Tesla', out_dir=Path(directory), output_format='square')
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(len(set(paths)), 3)

    def test_missing_credentials_are_actionable(self):
        with patch.dict(os.environ, {'IMAGE_PROVIDER': 'huggingface', 'HF_TOKEN': '', 'CLOUDFLARE_ACCOUNT_ID': '', 'CLOUDFLARE_API_TOKEN': ''}):
            with self.assertRaisesRegex(RuntimeError, 'HF_TOKEN'):
                open_model_image('photograph', 1, 'hf:Tongyi-MAI/Z-Image-Turbo', 1024, 1024)
            with self.assertRaisesRegex(RuntimeError, 'CLOUDFLARE_ACCOUNT_ID'):
                cloudflare_image('photograph', 1)

    def test_provider_selection_does_not_fall_through(self):
        studio = engine.LexnisCampaignStudio()
        with patch('campaign_generator.open_model_image', side_effect=RuntimeError('Unavailable')), patch('campaign_generator.requests.get') as fetch:
            with self.assertRaises(RuntimeError):
                studio._fetch_image_bytes('photograph', 1, 'hf:Tongyi-MAI/Z-Image-Turbo')
            fetch.assert_not_called()

    def test_cloudflare_response(self):
        import base64
        from unittest.mock import Mock
        response = Mock(ok=True)
        response.json.return_value = {'success': True, 'result': {'image': base64.b64encode(b'image').decode()}}
        with patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID': 'test', 'CLOUDFLARE_API_TOKEN': 'test'}), patch('requests.post', return_value=response) as request:
            self.assertEqual(cloudflare_image('photograph', 1), (b'image', True))
            self.assertEqual(request.call_args.kwargs['json']['steps'], 4)

    def test_api_partial_success_and_validation(self):
        asset = engine.CampaignAsset(prompt='Model 3', hook='Scenic route', caption='Coastal drive',
            highlights=[], hashtags='', visual_prompt='Blue car', image_url='', raw_response='', seed=1,
            image_status='unavailable', warnings=['Configure provider'])
        with TestClient(app) as client, patch.object(engine.LexnisCampaignStudio, 'generate_campaign', return_value=asset):
            response = client.post('/api/generate', json={'prompt': 'Model 3', 'output_format': 'landscape'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['image_url'], '')
            self.assertEqual(response.json()['image_status'], 'unavailable')
            self.assertEqual(client.post('/api/generate', json={'prompt': 'Model 3', 'output_format': 'invalid'}).status_code, 422)

    def test_invalid_image_is_not_cached(self):
        studio = engine.LexnisCampaignStudio()
        with tempfile.TemporaryDirectory() as directory, patch.object(studio, '_fetch_image_bytes', return_value=(b'not a photo', True)):
            with self.assertRaisesRegex(RuntimeError, 'invalid image'):
                studio.render_image('photograph', 1, out_dir=Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_export_resolves_browser_absolute_render_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'render.jpg'
            image.touch()
            with patch('server.RENDERS_DIR', Path(directory)):
                self.assertEqual(render_path('http://localhost:8000/renders/render.jpg?v=1'), str(image))


if __name__ == '__main__':
    unittest.main()
