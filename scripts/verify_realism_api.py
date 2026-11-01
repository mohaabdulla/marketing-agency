"""Live local API check. No external inference service is called."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    from fastapi.testclient import TestClient
    from server import app
    from visual_engine import REALISM_MODEL

    with TestClient(app) as client:
        health = client.get('/api/health').json()
        print('Automatic default:', health['default_image_model'], flush=True)
        assert health['default_image_model'] == REALISM_MODEL
        result = client.post('/api/render', json={
            'visual_prompt': 'Advertising photograph of a deep blue Tesla Model 3 sedan on a winding coastal road at golden sunset, ocean cliffs, low front three quarter tracking shot, realistic reflections, entire car visible, 35mm lens, no text, no watermark',
            'seed': 42, 'image_model': REALISM_MODEL, 'headline': 'TESLA MODEL 3',
            'brand': 'TESLA', 'tagline': 'ACCELERATE THE FUTURE.', 'output_format': 'landscape',
        })
        data = result.json()
        (ROOT / 'output' / 'realism-api-verification.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
        print('Render response:', result.status_code, data, flush=True)
        assert data['image_status'] == 'ready', data
        assert client.get(data['image_url']).status_code == 200
        print('Live local API render and image download verified.', flush=True)
