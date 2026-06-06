"""
kd-cosmic enterprise 接口实现（预留）

当前未实现，仅保留文件结构。如有需要可扩展：
- 增强型 Token 认证
- JWT 认证
- 摘要认证 / 签名认证 / 基本认证

详见 reference/KingdeeAI/ 下的认证指南文档。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from qdata_adapter_kd_cosmic.interfaces.base import BaseInterface

if TYPE_CHECKING:
    from qdata_adapter.client import HttpClient
    from qdata_adapter.context import ConnectorContext

logger = logging.getLogger(__name__)


class KdCosmicAdapterEnterpriseInterface(BaseInterface):
    """
    kd-cosmic enterprise 接口预留实现

    当前未实现具体逻辑，调用任何方法都会抛出 NotImplementedError。
    """

    interface_name = "enterprise"

    def __init__(self, context: ConnectorContext, http_client: HttpClient) -> None:
        super().__init__(context, http_client)

    async def authenticate(self) -> dict[str, Any]:
        """未实现"""
        raise NotImplementedError("Enterprise interface is not implemented yet")

    async def list_objects(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """未实现"""
        raise NotImplementedError("Enterprise interface is not implemented yet")
        yield {}  # type: ignore[misc]

    async def get_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        """未实现"""
        raise NotImplementedError("Enterprise interface is not implemented yet")

    async def create_object(self, object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """未实现"""
        raise NotImplementedError("Enterprise interface is not implemented yet")

    async def health_check(self) -> bool:
        """未实现"""
        logger.warning("Enterprise interface health check is not implemented")
        return False


__all__ = ["KdCosmicAdapterEnterpriseInterface"]
