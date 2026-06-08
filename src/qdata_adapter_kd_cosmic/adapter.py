"""
KdCosmicAdapter

适配器主类 - 支持完全自定义 API 调用
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

    支持完全自定义的 API 调用：
    - 自定义 API 路径（相对路径，自动拼接 base_url）
    - 自定义 HTTP 方法（POST/GET/PUT/DELETE）
    - 自定义请求参数（完全透传，不强制包装）

    认证配置 (auth_config)：
        {
            "client_id": "应用 ID",
            "client_secret": "应用密钥",
            "username": "用户名",
            "accountId": "数据中心 ID",
            "language": "zh_CN",
            "x_acgw_identity": "第三方应用身份标识",
        }

    使用示例：
        >>> context = ConnectorContext(
        ...     connector_id="my-connector",
        ...     app_software_code="kd_cosmic",
        ...     base_url="https://yifanni.kdgalaxy.com",
        ...     auth_config={...},
        ... )
        >>> adapter = KdCosmicAdapter(context)
        >>>
        >>> # 方式1: 完全自定义调用
        >>> result = await adapter.execute_custom_api(
        ...     path="/v2/null/basedata/bd_material/qeasyadd",
        ...     method="POST",
        ...     body={"data": [{"number": "Item-001", "name": "test"}]},
        ... )
        >>>
        >>> # 方式2: 通过 invoke 调用
        >>> result = await adapter.invoke(
        ...     "create", "bd_material",
        ...     data={"data": [{"number": "Item-001"}]},
        ...     params={
        ...         "_api_path": "/v2/null/basedata/bd_material/qeasyadd",
        ...         "_custom_body": True,
        ...     }
        ... )
    """

    app_code = "kd_cosmic"
    adapter_version = "0.2.0"

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
        """
        access_token = token.get("access_token")
        if access_token:
            self.http_client.set_header("accesstoken", access_token)
            if hasattr(self._interface, "_token"):
                self._interface._token = access_token

        auth_config = self.context.auth_config
        identity = auth_config.get("x_acgw_identity") or auth_config.get("x-acgw-identity", "")
        if identity:
            self.http_client.set_header("x-acgw-identity", identity)

    async def authenticate(self) -> dict[str, Any]:
        """获取认证凭证"""
        result = await self._interface.authenticate()
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

    # -------------------------------------------------------------------------
    # 标准 CRUD 方法
    # -------------------------------------------------------------------------

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
        """查询对象列表"""
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

    # -------------------------------------------------------------------------
    # 自定义 API 方法（核心）
    # -------------------------------------------------------------------------

    async def raw_request(
        self,
        path: str,
        method: str = "POST",
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        原始 HTTP 请求

        直接拼接 base_url + path，自动带上认证头，
        body/params/headers 完全透传，**不做响应状态检查**。

        Args:
            path: API 相对路径，如 "/v2/null/basedata/bd_material/qeasyadd"
            method: HTTP 方法，默认 POST
            body: 请求体，完全透传
            params: URL 查询参数
            headers: 额外请求头

        Returns:
            原始 API 响应字典
        """
        await self.ensure_authenticated()
        return await self._interface.raw_request(
            path=path,
            method=method,
            body=body,
            params=params,
            headers=headers,
        )

    async def execute_custom_api(
        self,
        path: str,
        method: str = "POST",
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        执行自定义 API

        与 raw_request 的区别：会自动检查响应中的 errorCode。

        Args:
            path: API 相对路径
            method: HTTP 方法
            body: 请求体
            params: URL 查询参数
            headers: 额外请求头

        Returns:
            API 响应中的 data 字段
        """
        await self.ensure_authenticated()
        return await self._interface.execute_custom_api(
            path=path,
            method=method,
            body=body,
            params=params,
            headers=headers,
        )

    async def invoke(
        self,
        method: str,
        object_type: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        统一的 API 调用方法

        通过 params 中的控制参数实现完全自定义：
        - _api_path: 自定义 API 相对路径
        - _http_method: HTTP 方法，如 "POST", "GET", "PUT", "DELETE"
        - _custom_body: 为 True 时 data 直接作为请求体，不包装
        - _raw_response: 为 True 时返回原始响应，不做 errorCode 检查

        Args:
            method: API 方法名
            object_type: 对象类型
            data: 请求体数据
            params: 查询参数 + 控制参数

        Returns:
            API 响应数据
        """
        await self.ensure_authenticated()
        return await self._interface.invoke(method, object_type, data, params)

    # -------------------------------------------------------------------------
    # 连接测试
    # -------------------------------------------------------------------------

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
