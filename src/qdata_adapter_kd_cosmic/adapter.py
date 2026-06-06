"""
KdCosmicAdapter

适配器主类 - 组合器模式实现
根据 settings.interface 自动路由到对应的接口实现：
- "standard": 主接口（默认），金蝶云星空旗舰版 OpenAPI
- "enterprise": 备用接口（预留）
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from qdata_adapter import BaseAppAdapter
from qdata_adapter.context import ConnectorContext
from qdata_adapter.results import TestConnectionResult

from qdata_adapter_kd_cosmic.interfaces.base import BaseInterface
from qdata_adapter_kd_cosmic.interfaces.standard import KdCosmicAdapterStandardInterface

logger = logging.getLogger(__name__)


class KdCosmicAdapter(BaseAppAdapter):
    """
    金蝶云星空旗舰版 (kd-cosmic) 适配器

    组合器模式，支持多接口切换：
    - settings.interface = "standard"（默认）
      → 使用 KdCosmicAdapterStandardInterface（OpenAPI Accesstoken 认证）

    认证配置 (auth_config)：
        {
            "client_id": "应用 ID",
            "client_secret": "应用密钥",
            "username": "用户名",
            "accountId": "数据中心 ID",
            "language": "zh_CN",  # 可选，默认 zh_CN
            "x_acgw_identity": "第三方应用身份标识",  # 可选
        }

    查询示例：
        >>> context = ConnectorContext(
        ...     connector_id="my-connector",
        ...     app_software_code="kd_cosmic",
        ...     base_url="https://yifanni.kdgalaxy.com",
        ...     auth_config={...},
        ...     settings={"interface": "standard"},
        ... )
        >>> adapter = KdCosmicAdapter(context)
        >>> result = await adapter.test_connection()
        >>> async for item in adapter.list_objects("sys.isc_demo_basedata_1"):
        ...     print(item)
    """

    app_code = "kd_cosmic"
    adapter_version = "0.1.0"

    def __init__(self, context: ConnectorContext, token_cache: Any = None) -> None:
        super().__init__(context, token_cache)
        self._interface = self._resolve_interface()
        logger.debug(
            "Initialized KdCosmicAdapter with %s interface",
            self._interface.interface_name
        )

    def _resolve_interface(self) -> BaseInterface:
        """根据 settings 路由到对应的接口实现"""
        interface_type = self.context.settings.get("interface", "standard")

        if interface_type == "standard":
            logger.debug("Using standard interface")
            return KdCosmicAdapterStandardInterface(self.context, self.http_client)
        else:
            logger.warning(
                "Unknown interface '%s', falling back to 'standard'",
                interface_type
            )
            return KdCosmicAdapterStandardInterface(self.context, self.http_client)

    def _apply_token(self, token: dict[str, Any]) -> None:
        """
        将 Token 应用到 HTTP 客户端

        金蝶云星空使用自定义请求头 "accesstoken" 而不是标准的 Bearer Token。
        同时支持 "x-acgw-identity" 身份标识。
        """
        access_token = token.get("access_token")
        if access_token:
            self.http_client.set_header("accesstoken", access_token)
            # 同时更新当前接口的 token
            if hasattr(self._interface, "_token"):
                self._interface._token = access_token

        auth_config = self.context.auth_config
        identity = auth_config.get("x_acgw_identity") or auth_config.get("x-acgw-identity", "")
        if identity:
            self.http_client.set_header("x-acgw-identity", identity)

    async def authenticate(self) -> dict[str, Any]:
        """获取认证凭证"""
        result = await self._interface.authenticate()
        # 同步 token 到 http_client
        self._apply_token(result)
        return result

    async def refresh_token(self) -> dict[str, Any]:
        """刷新认证凭证"""
        if hasattr(self._interface, "refresh_token"):
            result = await self._interface.refresh_token()
        else:
            result = await self._interface.authenticate()
        self._apply_token(result)
        return result

    async def list_objects(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """列表查询"""
        await self.ensure_authenticated()
        async for item in self._interface.list_objects(object_type, filters, page_size):
            yield item

    async def query_objects(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """查询对象列表（工作流节点优先使用此方法）"""
        await self.ensure_authenticated()
        async for item in self._interface.list_objects(object_type, filters, page_size):
            yield item

    async def get_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        """获取单个对象"""
        await self.ensure_authenticated()
        return await self._interface.get_object(object_type, object_id)

    async def create_object(self, object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """创建对象"""
        await self.ensure_authenticated()
        return await self._interface.create_object(object_type, data)

    async def invoke(
        self,
        method: str,
        object_type: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        统一的 API 调用方法

        Args:
            method: API 方法名，如 "query", "get", "create", "update", "delete"
            object_type: 对象类型，如 "sys.pm_purorderbill"
            data: 请求体数据（用于 create/update 等）
            params: 查询参数（用于 query/get 等）

        Returns:
            API 响应数据
        """
        await self.ensure_authenticated()

        if hasattr(self._interface, "invoke"):
            return await self._interface.invoke(method, object_type, data, params)

        if method in ("list", "query"):
            results = []
            async for item in self._interface.list_objects(
                object_type, filters=params, page_size=100
            ):
                results.append(item)
            return {"data": results, "total": len(results)}

        if method == "get":
            object_id = params.get("id") if params else None
            if not object_id:
                raise ValueError("'get' method requires params['id']")
            result = await self._interface.get_object(object_type, object_id)
            return {"data": result}

        if method == "create":
            if not data:
                raise ValueError("'create' method requires data")
            result = await self._interface.create_object(object_type, data)
            return {"data": result}

        raise NotImplementedError(
            f"Method '{method}' not implemented in interface."
        )

    async def test_connection(self) -> TestConnectionResult:
        """测试连接"""
        start_time = time.time()

        try:
            if await self._interface.health_check():
                return TestConnectionResult.connected(
                    message="kd-cosmic 连接成功",
                    duration_ms=int((time.time() - start_time) * 1000),
                    metadata={
                        "interface": self._interface.interface_name,
                        "base_url": self.context.base_url,
                    },
                )
            else:
                return TestConnectionResult.network_error(
                    message="健康检查失败",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

        except Exception as e:
            logger.error("Connection test failed: %s", e)
            error_msg = str(e)
            duration_ms = int((time.time() - start_time) * 1000)
            # 根据异常类型判断错误类别
            from qdata_adapter.exceptions import AuthenticationError, ResponseError

            from qdata_adapter_kd_cosmic.exceptions import KdCosmicAdapterAuthError
            if isinstance(e, (AuthenticationError, KdCosmicAdapterAuthError)):
                return TestConnectionResult.auth_failed(
                    message=error_msg,
                    duration_ms=duration_ms,
                    error_details={"error": error_msg},
                )
            if isinstance(e, ResponseError):
                return TestConnectionResult.network_error(
                    message=error_msg,
                    duration_ms=duration_ms,
                    error_details={"error": error_msg},
                )
            return TestConnectionResult.network_error(
                message=error_msg,
                duration_ms=duration_ms,
                error_details={"error": error_msg},
            )

    def get_interface_info(self) -> dict[str, Any]:
        """获取当前接口信息"""
        return {
            "interface_name": self._interface.interface_name,
            "available_interfaces": ["standard"],
            "adapter_version": self.adapter_version,
            "app_code": self.app_code,
        }


__all__ = ["KdCosmicAdapter"]
