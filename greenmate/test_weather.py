import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import requests

import db
import llm
import rag
import state
import weather
from main import app


class WeatherFetchTests(unittest.TestCase):
    def setUp(self):
        log_patch = patch('builtins.print')
        self.log = log_patch.start()
        self.addCleanup(log_patch.stop)

    def response(self, payload):
        response = MagicMock()
        response.status_code = 200
        response.__enter__.return_value = response
        response.json.return_value = payload
        return response

    def test_current_weather_parameters_and_mapping(self):
        response = self.response({"current": {"temperature_2m": 13.7, "relative_humidity_2m": 59}})
        with patch("weather.requests.get", return_value=response) as get:
            result = weather.fetch_weather()
        self.assertEqual(result, {"temperature": 13.7, "humidity": 59, "source_type": "REAL_WEATHER"})
        self.assertEqual(get.call_args.args, (weather.WEATHER_URL,))
        self.assertEqual(get.call_args.kwargs["params"], {
            "latitude": 39.9, "longitude": 116.4,
            "current": "temperature_2m,relative_humidity_2m", "temperature_unit": "celsius",
        })
        self.assertEqual(get.call_args.kwargs["timeout"], 5)

    def test_network_and_http_failures_return_none(self):
        for error in (requests.Timeout(), requests.ConnectionError(), requests.HTTPError()):
            with self.subTest(error=type(error).__name__), patch("weather.requests.get", side_effect=error):
                self.assertIsNone(weather.fetch_weather())
        response = self.response({})
        response.status_code = 503
        with patch("weather.requests.get", return_value=response):
            self.assertIsNone(weather.fetch_weather())

    def test_timeout_non_200_and_json_failure_are_logged(self):
        with patch('weather.requests.get', side_effect=requests.Timeout()):
            self.assertIsNone(weather.fetch_weather())
        self.log.assert_called_with('[weather] 网络请求超时（5 秒）。')
        for status in (201, 204, 302, 429, 500):
            response = self.response({})
            response.status_code = status
            with patch('weather.requests.get', return_value=response):
                self.assertIsNone(weather.fetch_weather())
            self.log.assert_called_with(f'[weather] API 返回非 200 状态：HTTP {status}。')
            response.json.assert_not_called()
        response = self.response(None)
        response.json.side_effect = ValueError('invalid JSON')
        with patch('weather.requests.get', return_value=response):
            self.assertIsNone(weather.fetch_weather())
        self.log.assert_called_with('[weather] JSON 解析失败，未获取有效天气。')

    def test_invalid_weather_data_returns_none(self):
        payloads = [{}, {"current": None}, {"current": {"temperature_2m": 18}}]
        for temperature, humidity in [(None, 60), (True, 60), (18, 101), (float('nan'), 60), (18, '60')]:
            payloads.append({"current": {"temperature_2m": temperature, "relative_humidity_2m": humidity}})
        for payload in payloads:
            with self.subTest(payload=payload), patch("weather.requests.get", return_value=self.response(payload)):
                self.assertIsNone(weather.fetch_weather())
        response = self.response(None)
        response.json.side_effect = ValueError("invalid JSON")
        with patch("weather.requests.get", return_value=response):
            self.assertIsNone(weather.fetch_weather())

    def test_invalid_coordinates_do_not_make_request(self):
        with patch("weather.requests.get") as get:
            for lat, lon in [(91, 116.4), (39.9, 181), ('invalid', 116.4), (None, None), (float('nan'), 116.4)]:
                self.assertIsNone(weather.fetch_weather(lat, lon))
            get.assert_not_called()


class WeatherEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for target, options in (
            ('main.build_knowledge_index', {'return_value': {}}),
            ('main.vector_search', {'side_effect': rag.simple_search}),
        ):
            mock_patch = patch(target, **options)
            mock_patch.start()
            self.addCleanup(mock_patch.stop)
        self.previous = state._current_state
        self.temp_dir = TemporaryDirectory()
        self.db_patch = patch("db.DB_PATH", str(Path(self.temp_dir.name) / 'weather-test.db'))
        self.db_patch.start()
        self.lifespan = app.router.lifespan_context(app)
        await self.lifespan.__aenter__()
        self.client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://greenmate.test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        state._current_state = self.previous
        self.db_patch.stop()
        self.temp_dir.cleanup()

    async def test_weather_saved_and_restored_after_restart(self):
        old = state.update_state({"light": 9000})
        incoming = {"temperature": 13.7, "humidity": 59, "source_type": "REAL_WEATHER"}
        with patch('main.fetch_weather', return_value=incoming) as fetch, patch('main.WEATHER_LAT', '39.9'), patch('main.WEATHER_LON', '116.4'):
            response = await self.client.post('/api/fetch-weather')
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with('39.9', '116.4')
        saved = response.json()
        self.assertEqual(saved['source_type'], 'REAL_WEATHER')
        self.assertEqual(saved['temperature'], 13.7)
        self.assertEqual(saved['humidity'], 59)
        self.assertEqual(saved['light'], old['light'])
        self.assertNotEqual(saved['timestamp'], old['timestamp'])
        self.assertEqual(db.get_state_from_db(), saved)
        self.assertEqual((await self.client.get('/api/state')).json(), saved)
        await self.lifespan.__aexit__(None, None, None)
        state._current_state = None
        self.lifespan = app.router.lifespan_context(app)
        await self.lifespan.__aenter__()
        self.assertEqual(state.get_state(), saved)

    async def test_fetch_failure_keeps_both_simulated_and_weather_state(self):
        for source in ['SIMULATED', 'REAL_WEATHER']:
            before = state.update_state({'temperature': 18, 'humidity': 55}, source_type=source)
            with patch('main.fetch_weather', return_value=None):
                response = await self.client.post('/api/fetch-weather')
            self.assertEqual(response.status_code, 502)
            self.assertEqual(db.get_state_from_db(), before)
            self.assertEqual(state.get_state(), before)

    async def test_ask_uses_real_weather_context_and_manual_update_resets_source(self):
        with patch('main.fetch_weather', return_value={'temperature': 15, 'humidity': 53, 'source_type': 'REAL_WEATHER'}):
            saved = (await self.client.post('/api/fetch-weather')).json()
        generate = AsyncMock(return_value='离线测试回答')
        with patch('main.generate_answer', generate):
            response = await self.client.post('/api/ask', json={'question': '需要浇水吗？'})
        self.assertEqual(response.json()['source_type'], 'REAL_WEATHER')
        self.assertEqual(generate.await_args.args[0], saved)
        messages = llm.build_messages(saved, '需要浇水吗？')
        self.assertIn('REAL_WEATHER', messages[-1]['content'])
        self.assertIn('light 只是保留的原状态值', messages[0]['content'])
        result = await self.client.post('/api/state', json={'temperature': 24})
        self.assertEqual(result.json()['source_type'], 'SIMULATED')

    async def test_source_switch_round_trip_and_reset_all_defaults(self):
        state.update_state({'temperature': 35, 'humidity': 22, 'light': 500})
        with patch('main.fetch_weather', return_value={'temperature': 16, 'humidity': 48, 'source_type': 'REAL_WEATHER'}):
            response = await self.client.post('/api/set-source', json={'source': 'REAL_WEATHER'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['source_type'], 'REAL_WEATHER')
        self.assertEqual(response.json()['temperature'], 16)
        self.assertEqual(response.json()['humidity'], 48)
        with patch('main.fetch_weather') as fetch:
            response = await self.client.post('/api/set-source', json={'source': 'SIMULATED'})
        fetch.assert_not_called()
        saved = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual({key: saved[key] for key in ('temperature', 'humidity', 'light', 'source_type')}, {
            'temperature': 24, 'humidity': 65, 'light': 12000, 'source_type': 'SIMULATED',
        })
        self.assertEqual(db.get_state_from_db(), saved)
        self.assertEqual(state.get_state(), saved)

    async def test_disconnected_source_switch_does_not_change_state(self):
        for source in ('SIMULATED', 'REAL_WEATHER'):
            before = state.update_state({'temperature': 19, 'humidity': 50}, source_type=source)
            with patch('weather.requests.get', side_effect=requests.ConnectionError()), patch('builtins.print') as log:
                response = await self.client.post('/api/set-source', json={'source': 'REAL_WEATHER'})
            self.assertEqual(response.status_code, 502)
            self.assertIn('现有状态未改变', response.json()['detail'])
            log.assert_called_once()
            self.assertEqual(state.get_state(), before)
            self.assertEqual(db.get_state_from_db(), before)
            self.assertEqual((await self.client.get('/api/state')).json(), before)

    async def test_source_validation_rejects_unknown_values(self):
        before = state.get_state()
        for payload in ({}, {'source': 'OTHER'}, {'source': None}, {'source': 'SIMULATED', 'temperature': 99}):
            with patch('main.fetch_weather') as fetch:
                response = await self.client.post('/api/set-source', json=payload)
            self.assertEqual(response.status_code, 422)
            fetch.assert_not_called()
            self.assertEqual(state.get_state(), before)


if __name__ == '__main__':
    unittest.main()
