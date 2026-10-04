"""Offline API/performance receipt; no subscriptions, messages, or external feeds."""
import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['FLOODSIGHT_ENV'] = 'development'
from floodsight import config
# Exercise the packaged deployment, not a developer's raw boundary downloads.
config.RAW_DIR = config.PROCESSED_DIR / '_raw_not_packaged'
from fastapi.testclient import TestClient
from api.main import app


def main():
    client = TestClient(app)
    results = []
    for path, expected in (
        ('/risk/grid',200), ('/risk/grid',200),
        ('/risk/streets?bbox=3.35,6.51,3.38,6.54',200),
        ('/risk/point?lat=6.52&lon=3.37',200),
        ('/risk/point?lat=6.52&lon=3.37',200),
        ('/risk/point?lat=51.5&lon=-0.1',422),
        ('/risk/point?lat=999&lon=999',422),
        ('/forecast/rainfall?lat=51.5&lon=-0.1',422),
        ('/floodsight.html',200), ('/privacy.html',200), ('/product-status',200),
    ):
        start = perf_counter()
        response = client.get(path)
        assert response.status_code == expected, (path,response.status_code)
        results.append({'path':path, 'status':response.status_code,
                        'seconds':round(perf_counter()-start,3),
                        'transfer_bytes':int(response.headers.get('content-length',len(response.content)))})
    import re
    inline_scripts = re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', Path('floodsight.html').read_text(encoding='utf-8'), re.S)
    checked = subprocess.run(['node','--check'], input='\n'.join(inline_scripts), text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
    report = {'verification':'offline_only_packaged_data', 'api_checks':results, 'landing_script_syntax':'passed'}
    Path('reports').mkdir(exist_ok=True)
    Path('reports/release_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
