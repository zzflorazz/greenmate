import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import tools


class ToolContractTests(unittest.TestCase):
    def check_envelope(self, result, status):
        self.assertEqual(set(result), {'status', 'source', 'time', 'data', 'error'})
        self.assertEqual(result['status'], status)
        self.assertIsInstance(result['data'], dict)
        self.assertIsNotNone(datetime.fromisoformat(result['time']).tzinfo)
        if status == 'ok':
            self.assertIsNone(result['error'])
        else:
            self.assertIsInstance(result['error'], str)

    def test_current_state_and_unavailable_use_same_contract(self):
        snapshot = {'temperature': 30, 'humidity': 65, 'light': 12000, 'source_type': 'MANUAL', 'timestamp': datetime.now(timezone.utc).isoformat()}
        with patch('tools.get_state', return_value=snapshot):
            result = tools.get_current_environment()
        self.check_envelope(result, 'ok')
        self.assertEqual(result['data'], snapshot)
        self.assertEqual(result['source'], 'MANUAL')
        with patch('tools.get_state', side_effect=RuntimeError()):
            self.check_envelope(tools.get_current_environment(), 'unavailable')

    def test_forecast_12_future_hours_and_no_current_state_write(self):
        def request(url, **kwargs):
            self.assertEqual(url, 'https://api.open-meteo.com/v1/forecast')
            self.assertEqual(kwargs['timeout'], 5)
            params = kwargs['params']
            start = datetime.fromisoformat(params['start_hour']).replace(tzinfo=timezone.utc)
            self.assertGreater(start, datetime.now(timezone.utc))
            end = datetime.fromisoformat(params['end_hour']).replace(tzinfo=timezone.utc)
            self.assertEqual(end - start, timedelta(hours=11))
            response = MagicMock()
            response.__enter__.return_value = response
            response.status_code = 200
            response.json.return_value = {'hourly': {
                'time': [(start + timedelta(hours=index)).strftime('%Y-%m-%dT%H:%M') for index in range(12)],
                'temperature_2m': [15.0] * 12, 'relative_humidity_2m': [55] * 12,
            }}
            return response
        with patch('tools.requests.get', side_effect=request):
            result = tools.get_weather_forecast('北京')
        self.check_envelope(result, 'ok')
        self.assertEqual(result['source'], 'OPEN_METEO')
        self.assertEqual(len(result['data']['items']), 12)

    def test_bad_forecast_and_location_are_distinct(self):
        with patch('tools.requests.get') as request:
            self.check_envelope(tools.get_weather_forecast('未配置城市'), 'error')
            request.assert_not_called()
        for status in (200, 503):
            response = MagicMock()
            response.__enter__.return_value = response
            response.status_code = status
            response.json.return_value = {'hourly': {}}
            with patch('tools.requests.get', return_value=response), patch('builtins.print'):
                self.check_envelope(tools.get_weather_forecast('北京'), 'unavailable')

    def test_knowledge_empty_is_ok_and_bad_query_is_error(self):
        with patch('tools.vector_search', return_value=[]):
            result = tools.search_plant_knowledge('未知植物')
        self.check_envelope(result, 'ok')
        self.assertEqual(result['data']['items'], [])
        self.check_envelope(tools.search_plant_knowledge(' '), 'error')


if __name__ == '__main__':
    unittest.main()
