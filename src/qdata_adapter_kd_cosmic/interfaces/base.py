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

    async def invoke(
        self,
        method: str,
        object_type: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        统一的 API 调用方法（可选实现）

        对于拥有成百上千个 API 的平台，为每个 API 实现独立方法不现实。
        此方法提供统一的调用入口，让适配器灵活处理任意 API 调用。

        默认实现会根据 method 路由到 list_objects/get_object/create_object。
        子类可以覆盖此方法实现更灵活的调用逻辑。

        Args:
            method: API 方法名，如 "query", "get", "create", "update", "delete"
            object_type: 对象类型，如 "orders", "products"
            data: 请求体数据（用于 create/update 等）
            params: 查询参数（用于 query/get 等）

        Returns:
            API 响应数据

        Raises:
            KdCosmicAdapterAuthError: 认证失败
            KdCosmicAdapterAPIError: API 调用失败
            NotImplementedError: 方法不支持

        Example:
            >>> # 查询列表
            >>> result = await interface.invoke(
            ...     "query", "orders",
            ...     params={"status": "pending", "page": 1}
            ... )
            >>>
            >>> # 获取单条
            >>> result = await interface.invoke(
            ...     "get", "orders", params={"id": "ORD001"}
            ... )
            >>>
            >>> # 创建对象
            >>> result = await interface.invoke(
            ...     "create", "orders",
            ...     data={"customer": "张三", "amount": 100}
            ... )
        """
        # 默认路由到标准方法
        if method in ("list", "query"):
            # 收集所有结果到列表返回
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
                f"Please override invoke() in your interface class."
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
