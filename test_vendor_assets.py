"""Only the new local JavaScript delivery boundary; no network/DB needed."""
import unittest
import httpx2
from main import app

class VendorAssetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),base_url='http://greenmate.test')
    async def asyncTearDown(self):
        await self.client.aclose()
    async def test_local_r160_and_cache_headers(self):
        result=await self.client.get('/vendor/three.module.min.js')
        self.assertEqual(result.status_code,200)
        self.assertIn('application/javascript',result.headers['content-type'])
        self.assertEqual(result.headers['cache-control'],'public, max-age=86400')
        self.assertIn('"160"',result.text[:300])
    async def test_no_non_js_missing_or_traversed_resources(self):
        for path in ['/vendor/.env','/vendor/THREE-LICENSE.txt','/vendor/missing.js','/vendor/..%2Fmain.py','/vendor/%2e%2e%2fmain.py','/vendor/%2e%2e%2findex.html','/vendor/sub/file.js']:
            self.assertEqual((await self.client.get(path)).status_code,404,path)
