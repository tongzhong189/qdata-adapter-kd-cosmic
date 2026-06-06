"""
适配器测试

测试 KdCosmicAdapter 的核心功能（仅查询，不涉及写入）
"""

from typing import Any

import pytest
from pytest_httpx import HTTPXMock
from qdata_adapter import ConnectorContext

from qdata_adapter_kd_cosmic import KdCosmicAdapter


class TestKdCosmicAdapter:
    """KdCosmicAdapter 测试类"""

    # -------------------------------------------------------------------------
    # 基础测试
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_adapter_initialization(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
    ) -> None:
        """测试适配器初始化"""
        adapter = KdCosmicAdapter(standard_context, mock_token_cache)

        assert adapter.app_code == "kd_cosmic"
        assert adapter.adapter_version == "0.1.0"
        assert adapter.context == standard_context

    @pytest.mark.asyncio
    async def test_get_interface_info(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
    ) -> None:
        """测试获取接口信息"""
        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        info = adapter.get_interface_info()

        assert info["interface_name"] == "standard"
        assert "standard" in info["available_interfaces"]
        assert info["adapter_version"] == "0.1.0"
        assert info["app_code"] == "kd_cosmic"

    # -------------------------------------------------------------------------
    # 认证测试
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_authenticate_standard(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试 standard 接口认证（金蝶 OAuth2 Accesstoken）"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {
                    "access_token": "test-token-123",
                    "refresh_token": "refresh-token-456",
                    "expires_in": 7200000,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.authenticate()

        assert result["access_token"] == "test-token-123"
        assert result["refresh_token"] == "refresh-token-456"
        assert result["expires_in"] == 7200  # 转换为秒

    @pytest.mark.asyncio
    async def test_authenticate_failure(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试认证失败场景"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "2501",
                "message": "不存在应用信息[网关]",
                "status": False,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.test_connection()

        assert result.success is False
        assert result.status == "auth_failed"

    @pytest.mark.asyncio
    async def test_refresh_token(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试刷新 Token"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/refreshToken",
            json={
                "errorCode": "0",
                "data": {
                    "access_token": "new-token-789",
                    "refresh_token": "new-refresh-abc",
                    "expires_in": 3600000,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.refresh_token()

        assert result["access_token"] == "new-token-789"

    # -------------------------------------------------------------------------
    # 查询测试（仅查询，不涉及写入）
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_objects_standard(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试 standard 接口列表查询（金蝶 OpenAPI 查询格式）"""
        # Mock 认证
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        # Mock 查询接口
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [
                        ["ORD001", "completed", 100.0],
                        ["ORD002", "pending", 200.0],
                    ],
                    "header": [
                        {"name": "number", "caption": "编号", "type": "String"},
                        {"name": "status", "caption": "状态", "type": "String"},
                        {"name": "amount", "caption": "金额", "type": "Decimal"},
                    ],
                    "count": 2,
                    "page": 1,
                    "pageSize": 50,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        records = []
        async for record in adapter.list_objects("sys.demo_form", page_size=50):
            records.append(record)

        assert len(records) == 2
        assert records[0]["number"] == "ORD001"
        assert records[0]["status"] == "completed"
        assert records[1]["number"] == "ORD002"
        assert records[1]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_objects_with_filter(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试带过滤条件的列表查询"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["ORD001", "completed"]],
                    "header": [
                        {"name": "number", "caption": "编号", "type": "String"},
                        {"name": "status", "caption": "状态", "type": "String"},
                    ],
                    "count": 1,
                    "page": 1,
                    "pageSize": 10,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        records = []
        async for record in adapter.list_objects(
            "sys.demo_form",
            filters={"filterString": "status = 'completed'"},
            page_size=10,
        ):
            records.append(record)

        assert len(records) == 1
        assert records[0]["number"] == "ORD001"
        assert records[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_objects_pagination(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试列表查询自动翻页"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        # 第一页
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["item1"], ["item2"]],
                    "header": [{"name": "name", "type": "String"}],
                    "count": 3,
                    "page": 1,
                    "pageSize": 2,
                },
                "status": True,
            },
        )
        # 第二页
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["item3"]],
                    "header": [{"name": "name", "type": "String"}],
                    "count": 3,
                    "page": 2,
                    "pageSize": 2,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        records = []
        async for record in adapter.list_objects("sys.demo_form", page_size=2):
            records.append(record)

        assert len(records) == 3
        assert records[0]["name"] == "item1"
        assert records[1]["name"] == "item2"
        assert records[2]["name"] == "item3"

    @pytest.mark.asyncio
    async def test_get_object_standard(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试单条查询"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["ORD001", "completed", 100.0]],
                    "header": [
                        {"name": "number", "caption": "编号", "type": "String"},
                        {"name": "status", "caption": "状态", "type": "String"},
                        {"name": "amount", "caption": "金额", "type": "Decimal"},
                    ],
                    "count": 1,
                    "page": 1,
                    "pageSize": 1,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.get_object("sys.demo_form", "ORD001")

        assert result["number"] == "ORD001"
        assert result["status"] == "completed"
        assert result["amount"] == 100.0

    @pytest.mark.asyncio
    async def test_get_object_not_found(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试单条查询 - 对象不存在"""
        from qdata_adapter.exceptions import NotFoundError

        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [],
                    "header": [{"name": "number", "type": "String"}],
                    "count": 0,
                    "page": 1,
                    "pageSize": 1,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        with pytest.raises(NotFoundError):
            await adapter.get_object("sys.demo_form", "NOT_EXIST")

    @pytest.mark.asyncio
    async def test_query_objects_standard(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试 query_objects 方法（工作流节点优先使用）"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["PROD001", "Product 1"], ["PROD002", "Product 2"]],
                    "header": [
                        {"name": "number", "type": "String"},
                        {"name": "name", "type": "String"},
                    ],
                    "count": 2,
                    "page": 1,
                    "pageSize": 50,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        records = []
        async for record in adapter.query_objects("sys.demo_form", page_size=50):
            records.append(record)

        assert len(records) == 2
        assert records[0]["number"] == "PROD001"
        assert records[1]["name"] == "Product 2"

    # -------------------------------------------------------------------------
    # invoke 方法测试（仅查询）
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_invoke_query(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试 invoke 方法 - query 操作"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["C001", "Customer 1"], ["C002", "Customer 2"]],
                    "header": [
                        {"name": "number", "type": "String"},
                        {"name": "name", "type": "String"},
                    ],
                    "count": 2,
                    "page": 1,
                    "pageSize": 50,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.invoke("query", "sys.demo_form", params={"status": "active"})

        assert "data" in result
        assert result["total"] == 2
        assert len(result["data"]) == 2
        assert result["data"][0]["number"] == "C001"

    @pytest.mark.asyncio
    async def test_invoke_get(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试 invoke 方法 - get 操作"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["ITEM001", "Test Item", 99.9]],
                    "header": [
                        {"name": "number", "type": "String"},
                        {"name": "name", "type": "String"},
                        {"name": "price", "type": "Decimal"},
                    ],
                    "count": 1,
                    "page": 1,
                    "pageSize": 1,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.invoke("get", "sys.demo_form", params={"id": "ITEM001"})

        assert "data" in result
        assert result["data"]["number"] == "ITEM001"
        assert result["data"]["price"] == 99.9

    # -------------------------------------------------------------------------
    # 连接测试
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_test_connection_success(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试连接测试 - 成功场景"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "token", "expires_in": 7200000},
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.test_connection()

        assert result.success is True
        assert result.status == "connected"
        assert result.metadata["interface"] == "standard"

    @pytest.mark.asyncio
    async def test_test_connection_auth_failure(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试连接测试 - 认证失败场景"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "2501",
                "message": "不存在应用信息[网关]",
                "status": False,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.test_connection()

        assert result.success is False
        assert result.status == "auth_failed"

    @pytest.mark.asyncio
    async def test_test_connection_network_error(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试连接测试 - 网络错误场景"""
        # HttpClient 会重试 3 次，所以 mock 需要可复用
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            status_code=500,
            json={"error": "Internal Server Error"},
            is_reusable=True,
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        result = await adapter.test_connection()

        assert result.success is False
        assert result.status == "network_error"

    # -------------------------------------------------------------------------
    # 工具方法测试
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_ensure_authenticated_sets_header(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
        httpx_mock: HTTPXMock,
    ) -> None:
        """测试认证后是否正确设置了 accesstoken header"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/oauth2/getToken",
            json={
                "errorCode": "0",
                "data": {"access_token": "my-token", "expires_in": 7200000},
                "status": True,
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.example.com/kapi/sys/demo_form/query",
            json={
                "errorCode": "0",
                "data": {
                    "rows": [["TEST001"]],
                    "header": [{"name": "number", "type": "String"}],
                    "count": 1,
                    "page": 1,
                    "pageSize": 10,
                },
                "status": True,
            },
        )

        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        await adapter.ensure_authenticated()

        # 验证接口的 token 已设置
        assert adapter._interface._token == "my-token"

        # 验证能正常调用查询
        records = []
        async for record in adapter.list_objects("sys.demo_form", page_size=10):
            records.append(record)
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_parse_object_type_with_dot(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
    ) -> None:
        """测试 object_type 带点号的解析"""
        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        app_id, form_id = adapter._interface._parse_object_type("sys.pm_purorderbill")
        assert app_id == "sys"
        assert form_id == "pm_purorderbill"

    @pytest.mark.asyncio
    async def test_parse_object_type_without_dot(
        self,
        standard_context: ConnectorContext,
        mock_token_cache: Any,
    ) -> None:
        """测试 object_type 不带点号的解析（使用默认 app_id）"""
        adapter = KdCosmicAdapter(standard_context, mock_token_cache)
        app_id, form_id = adapter._interface._parse_object_type("pm_purorderbill")
        assert app_id == "sys"  # 默认值
        assert form_id == "pm_purorderbill"
