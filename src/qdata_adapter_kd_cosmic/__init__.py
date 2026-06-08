"""
qdata-adapter-kd-cosmic

金蝶云星空旗舰版 (Kingdee Galaxy / kd-cosmic) 适配器

支持：
- OAuth2 Accesstoken 认证
- OpenAPI 查询操作（query）
- OpenAPI 保存操作（save）
- 自动分页处理

Example:
    >>> from qdata_adapter_kd_cosmic import KdCosmicAdapter
    >>> adapter = KdCosmicAdapter(context)
    >>> result = await adapter.test_connection()
"""

from qdata_adapter_kd_cosmic.adapter import KdCosmicAdapter

__version__ = "0.1.0"
__all__ = ["KdCosmicAdapter"]
