"""
BaseInterface 抽象基类

所有 kd-cosmic 接口实现必须继承此类
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qdata_adapter.client import HttpClient
    from qdata_adapter.context import ConnectorContext


class BaseInterface(ABC):
    """
    kd-cosmic 接口抽象基类

    定义所有接口实现必须遵循的契约。
    子类需要实现具体的 API 调用逻辑。

    Attributes:
        interface_name: 接口标识名称
        context: 连接器上下文
        http_client: HTTP 客户端实例

    Example:
        >>> class MyInterface(BaseInterface):
        ...     interface_name = "my_interface"
        ...
        ...     async def authenticate(self) -> dict:
        ...         # 实现认证逻辑
        ...         pass
    """

    interface_name: str = ""

    def __init__(self, context: ConnectorContext, http_client: HttpClient) -> None:
        """
        初始化接口

        Args:
            context: 连接器上下文
            http_client: HTTP 客户端实例
        """
        self.context = context
        self.http_client = http_client

    @abstractmethod
    async def authenticate(self) -> dict[str, Any]:
        """
        获取认证凭证

        Returns:
            认证凭证字典

        Raises:
            KdCosmicAdapterAuthError: 认证失败
        """
        pass

    @abstractmethod
    async def list_objects(
        self,
        object_type: str,
        filters: dict[str, Any] | None,
        page_size: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        列表查询，自动处理翻页

        Args:
            object_type: 对象类型
            filters: 过滤条件
            page_size: 每页大小

        Yields:
            单条记录字典

        Raises:
            KdCosmicAdapterAuthError: 认证失败
            KdCosmicAdapterAPIError: API 调用失败
        """
        pass

    @abstractmethod
    async def get_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        """
        获取单个对象

        Args:
            object_type: 对象类型
            object_id: 对象 ID

        Returns:
            对象数据字典

        Raises:
            KdCosmicAdapterAuthError: 认证失败
            KdCosmicAdapterAPIError: API 调用失败
            NotFoundError: 对象不存在
        """
        pass

    @abstractmethod
    async def create_object(self, object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        创建对象

        Args:
            object_type: 对象类型
            data: 对象数据

        Returns:
            创建后的对象数据

        Raises:
            KdCosmicAdapterAuthError: 认证失败
            KdCosmicAdapterAPIError: API 调用失败
            ValidationError: 数据验证失败
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        健康检查

        Returns:
            True: 连接正常
            False: 连接异常
        """
        pass

    @abstractmethod
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

        最底层的请求方法，直接拼接 base_url + path，
        自动带上认证头，body/params/headers 完全透传。

        Args:
            path: API 相对路径，如 "/v2/null/basedata/bd_material/qeasyadd"
            method: HTTP 方法，默认 POST
            body: 请求体，完全透传
            params: URL 查询参数
            headers: 额外请求头

        Returns:
            API 响应数据（已检查 errorCode）
        """
        pass

    @abstractmethod
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

        与 raw_request 类似，但支持通过 settings 配置默认参数。

        Args:
            path: API 相对路径
            method: HTTP 方法
            body: 请求体
            params: URL 查询参数
            headers: 额外请求头

        Returns:
            API 响应数据
        """
        pass

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
        - _api_path: 自定义 API 相对路径，如 "/v2/null/basedata/bd_material/qeasyadd"
        - _http_method: HTTP 方法，如 "POST", "GET", "PUT", "DELETE"
        - _custom_body: 为 True 时 data 直接作为请求体，不包装
        - _raw_response: 为 True 时返回原始响应，不做 errorCode 检查

        Args:
            method: API 方法名，如 "query", "get", "create", "update", "delete"
            object_type: 对象类型标识
            data: 请求体数据
            params: 查询参数 + 控制参数

        Returns:
            API 响应数据
        """
        params = dict(params) if params else {}

        # 提取控制参数
        api_path = params.pop("_api_path", None)
        http_method = params.pop("_http_method", "POST")
        custom_body = params.pop("_custom_body", False)
        raw_response = params.pop("_raw_response", False)

        # 如果指定了自定义路径，使用 execute_custom_api
        if api_path:
            body = data if custom_body else ({"data": data} if data is not None else None)
            if raw_response:
                # 绕过响应检查，直接返回原始响应
                return await self.raw_request(
                    path=api_path,
                    method=http_method,
                    body=body,
                    params=params if params else None,
                )
            return await self.execute_custom_api(
                path=api_path,
                method=http_method,
                body=body,
                params=params if params else None,
            )

        # 默认路由到标准方法
        if method in ("list", "query"):
            results = []
            async for item in self.list_objects(object_type, filters=params, page_size=100):
                results.append(item)
            return {"data": results, "total": len(results)}

        elif method == "get":
            object_id = params.get("id") if params else None
            if not object_id:
                raise ValueError("'get' method requires params['id']")
            result = await self.get_object(object_type, object_id)
            return {"data": result}

        elif method == "create":
            if not data:
                raise ValueError("'create' method requires data")
            result = await self.create_object(object_type, data)
            return {"data": result}

        else:
            raise NotImplementedError(
                f"Method '{method}' not implemented. "
                f"Please use params['_api_path'] for custom API calls."
            )

    def get_auth_config(self) -> dict[str, Any]:
        """
        获取认证配置

        Returns:
            auth_config 字典
        """
        return self.context.auth_config

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        获取扩展配置

        Args:
            key: 配置键名
            default: 默认值

        Returns:
            配置值
        """
        return self.context.settings.get(key, default)


__all__ = ["BaseInterface"]
