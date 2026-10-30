"""Single configuration boundary: .env is resolved relative to this project."""
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / '.env'
load_dotenv(ENV_PATH, override=False)  # Explicit shell variables take precedence.


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    weather_lat: str
    weather_lon: str
    db_path: str

    def validate(self) -> None:
        url = urlparse(self.base_url)
        if url.scheme not in {'https', 'http'} or not url.hostname:
            raise ValueError('配置错误：GREENMATE_BASE_URL 必须是有效的 http/https 地址。')
        if not self.model:
            raise ValueError('配置错误：GREENMATE_MODEL 不能为空。')
        try:
            lat, lon = float(self.weather_lat), float(self.weather_lon)
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except ValueError:
            raise ValueError('配置错误：WEATHER_LAT/WEATHER_LON 必须是有效经纬度。') from None
        if not self.db_path:
            raise ValueError('配置错误：DB_PATH 不能为空。')

    def report_startup(self) -> None:
        self.validate()
        if not self.api_key:
            print('[配置] 未设置 GREENMATE_API_KEY：联网问答不可用；请在项目 .env 填写后重启。本地状态、知识和预测仍可演示。', flush=True)
        else:
            print('[配置] 已读取模型配置与 API key（密钥不显示）。', flush=True)
        if not ENV_PATH.is_file():
            print('[配置] 未找到项目 .env，当前使用环境变量及默认值；可复制 .env.example。', flush=True)


def get_settings() -> Settings:
    # Modules never read os.environ themselves. Fresh reads also support explicit
    # environment overrides by CLI/tests without re-loading .env or caching keys.
    return Settings(
        api_key=os.environ.get('GREENMATE_API_KEY', '').strip(),
        base_url=os.environ.get('GREENMATE_BASE_URL', 'https://api.deepseek.com').strip(),
        model=os.environ.get('GREENMATE_MODEL', 'deepseek-chat').strip(),
        weather_lat=os.environ.get('WEATHER_LAT', '39.9').strip(),
        weather_lon=os.environ.get('WEATHER_LON', '116.4').strip(),
        db_path=os.environ.get('DB_PATH', 'greenmate.db').strip(),
    )


_config = get_settings()
LLM_BASE_URL, LLM_MODEL = _config.base_url, _config.model
WEATHER_LAT, WEATHER_LON = _config.weather_lat, _config.weather_lon
DB_PATH = _config.db_path


if __name__ == '__main__':
    try:
        get_settings().report_startup()
    except ValueError as error:
        raise SystemExit(str(error)) from None
