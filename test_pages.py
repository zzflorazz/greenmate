"""Presentation routing and local resources; never invokes LLM/network/training."""
import unittest
from pathlib import Path
import httpx2
from main import app

class PageTests(unittest.IsolatedAsyncioTestCase):
    async def test_six_pages_have_their_own_nav_scripts_and_content(self):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),base_url='http://test') as client:
            for page,marker in [('home','home'),('environment','environment'),('conversation','ask-form'),('knowledge','knowledge-form'),('prediction','prediction'),('analysis','s4-conflict')]:
                path='/' if page=='home' else '/'+page
                response=await client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertIn(f'id="{marker}"',response.text)
                self.assertIn(f'href="{path}" aria-current="page"',response.text)
                self.assertIn(f'/static/{page}.js',response.text)
            for path in ['/unknown-page','/unknown.html','/assets/../.env','/static/..%2F.env']:
                self.assertEqual((await client.get(path)).status_code,404)
    async def test_styles_scripts_and_all_six_sized_jpegs_served(self):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),base_url='http://test') as client:
            for asset in ['app.css','app.js','home.js','environment.js','conversation.js','knowledge.js','prediction.js','analysis.js','scene.js']:
                self.assertEqual((await client.get('/static/'+asset)).status_code,200)
            for image in Path('assets/img').glob('*.jpg'):
                response=await client.get('/assets/img/'+image.name)
                self.assertEqual(response.status_code,200)
                self.assertIn('image/jpeg',response.headers['content-type'])
                self.assertLessEqual(len(response.content),250000)
            self.assertEqual(len(list(Path('assets/img').glob('*.jpg'))),6)
