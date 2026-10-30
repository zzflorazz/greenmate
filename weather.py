"""Fetch current temperature and air humidity from Open-Meteo."""
import math

import requests


WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_weather(lat=39.9, lon=116.4) -> dict | None:
    try:
        lat, lon = float(lat), float(lon)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            print("[weather] 经纬度无效，未获取天气。")
            return None
        with requests.get(
            WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m",
                "temperature_unit": "celsius",
            },
            timeout=5,
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                print(f"[weather] API 返回非 200 状态：HTTP {response.status_code}。")
                return None
            try:
                payload = response.json()
            except ValueError:
                print("[weather] JSON 解析失败，未获取有效天气。")
                return None
            current = payload["current"]
        temperature = current["temperature_2m"]
        humidity = current["relative_humidity_2m"]
        # Reject incomplete/error responses before touching the stored state.
        if any(type(value) not in (int, float) for value in (temperature, humidity)):
            print("[weather] 天气数值缺失或类型无效。")
            return None
        if not math.isfinite(temperature) or not math.isfinite(humidity) or not 0 <= humidity <= 100:
            print("[weather] 天气数值超出有效范围。")
            return None
        return {"temperature": temperature, "humidity": humidity, "source_type": "REAL_WEATHER"}
    except requests.Timeout:
        print("[weather] 网络请求超时（5 秒）。")
        return None
    except requests.RequestException as error:
        print(f"[weather] 网络请求失败：{type(error).__name__}。")
        return None
    except (ValueError, TypeError, KeyError, OverflowError):
        print("[weather] 经纬度或天气响应格式无效。")
        return None
