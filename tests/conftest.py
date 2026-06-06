"""
Pytest 配置和 Fixtures

支持：
1. 从 .env 文件加载测试配置
2. Mock 和真实 API 测试切换
3. HTTP 流量录制（用于调试）
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from qdata_adapter import ConnectorContext

# 尝试加载 python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()  # 加载 .env 文件
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass


# =============================================================================
# 配置常量
# =============================================================================

ADAPTER_NAME = "kd_cosmic"
BASE_URL = os.getenv(f"{ADAPTER_NAME.upper()}_BASE_URL", "https://api.example.com")
ENVIRONMENT = os.getenv(f"{ADAPTER_NAME.upper()}_ENVIRONMENT", "sandbox")
USE_REAL_API = os.getenv("USE_REAL_API", "false").lower() == "true"
RECORD_TRAFFIC = os.getenv("RECORD_HTTP_TRAFFIC", "false").lower() == "true"
TEST_DATA_DIR = Path(os.getenv("TEST_DATA_DIR", "tests/data"))


# =============================================================================
# 辅助函数
# =============================================================================

def save_http_recording(
    test_name: str,
    request_data: dict,
    response_data: dict,
    interface: str = "standard",
) -> None:
    """保存 HTTP 请求/响应记录"""
    if not RECORD_TRAFFIC:
        return

    recording_dir = TEST_DATA_DIR / "recordings" / datetime.now().strftime("%Y%m%d")
    recording_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{interface}_{test_name}_{timestamp}.json"
    filepath = recording_dir / filename

    record = {
        "timestamp": datetime.now().isoformat(),
        "test_name": test_name,
        "interface": interface,
        "request": request_data,
        "response": response_data,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    print(f"\n[录制] HTTP 记录已保存: {filepath}")


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def test_config() -> dict[str, Any]:
    """测试配置 fixture"""
    return {
        "use_real_api": USE_REAL_API,
        "record_traffic": RECORD_TRAFFIC,
        "test_data_dir": TEST_DATA_DIR,
        "base_url": BASE_URL,
        "environment": ENVIRONMENT,
    }


@pytest.fixture
def standard_auth_config() -> dict[str, str]:
    """
    standard 接口认证配置（金蝶云星空 Accesstoken 认证）

    优先从环境变量读取，使用默认值作为 fallback。
    """
    prefix = ADAPTER_NAME.upper()
    return {
        "client_id": os.getenv(f"{prefix}_CLIENT_ID", "test-client-id"),
        "client_secret": os.getenv(f"{prefix}_CLIENT_SECRET", "test-client-secret"),
        "username": os.getenv(f"{prefix}_USERNAME", "test-username"),
        "accountId": os.getenv(f"{prefix}_ACCOUNT_ID", "test-account-id"),
        "language": os.getenv(f"{prefix}_LANGUAGE", "zh_CN"),
        "x_acgw_identity": os.getenv(f"{prefix}_X_ACGW_IDENTITY", ""),
        "refresh_token": os.getenv(f"{prefix}_REFRESH_TOKEN", "test-refresh-token"),
    }


@pytest.fixture
def base_context() -> ConnectorContext:
    """基础上下文 fixture"""
    return ConnectorContext(
        connector_id="test-connector",
        app_software_code=ADAPTER_NAME,
        base_url=BASE_URL,
        auth_config={},
    )


@pytest.fixture
def standard_context(standard_auth_config: dict) -> ConnectorContext:
    """standard 接口上下文 fixture"""
    return ConnectorContext(
        connector_id="test-connector-standard",
        app_software_code=ADAPTER_NAME,
        base_url=BASE_URL,
        auth_config=standard_auth_config,
        settings={"interface": "standard"},
        environment=ENVIRONMENT,
    )


@pytest.fixture
def mock_token_cache() -> Any:
    """Mock Token 缓存 fixture"""
    class MockTokenCache:
        _cache: dict[str, Any] = {}

        async def get(self, key: str) -> Any:
            return self._cache.get(key)

        async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
            self._cache[key] = value

        async def delete(self, key: str) -> None:
            self._cache.pop(key, None)

    return MockTokenCache()


# =============================================================================
# Pytest 钩子
# =============================================================================

def pytest_configure(config):
    """Pytest 配置钩子"""
    config.addinivalue_line(
        "markers", "real_api: 标记需要真实 API 的测试"
    )
    config.addinivalue_line(
        "markers", "record_http: 标记需要录制 HTTP 流量的测试"
    )


def pytest_runtest_setup(item):
    """测试前设置"""
    if "real_api" in item.keywords and not USE_REAL_API:
        pytest.skip("跳过真实 API 测试 (USE_REAL_API=false)")
