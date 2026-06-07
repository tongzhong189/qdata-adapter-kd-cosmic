"""
kd-cosmic standard 接口实现

基于金蝶云星空旗舰版 OpenAPI 标准接口：
- 认证：OAuth2 Accesstoken (/kapi/oauth2/getToken)
- 查询：POST /kapi/{appId}/{formId}/query
- 保存：POST /kapi/{appId}/{formId}/save
- 响应格式：{errorCode: "0", data: {...}, status: true}
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, Any

from qdata_adapter.exceptions import NotFoundError, ValidationError

from qdata_adapter_kd_cosmic.exceptions import KdCosmicAdapterAPIError, KdCosmicAdapterAuthError
from qdata_adapter_kd_cosmic.interfaces.base import BaseInterface

if TYPE_CHECKING:
    from qdata_adapter.client import HttpClient
    from qdata_adapter.context import ConnectorContext

logger = logging.getLogger(__name__)


class KdCosmicAdapterStandardInterface(BaseInterface):
    """
    金蝶云星空旗舰版标准接口实现

    认证方式：OAuth2 Accesstoken
    - 获取 Token：POST /kapi/oauth2/getToken
    - 刷新 Token：POST /kapi/oauth2/refreshToken
    - 请求头：accesstoken: {token}

    Example:
        >>> context = ConnectorContext(
        ...     connector_id="test",
        ...     app_software_code="kd_cosmic",
        ...     base_url="https://yifanni.kdgalaxy.com",
        ...     auth_config={
        ...         "client_id": "xxx",
        ...         "client_secret": "yyy",
        ...         "username": "admin",
        ...         "accountId": "123456",
        ...         "language": "zh_CN",
        ...     },
        ... )
        >>> interface = KdCosmicAdapterStandardInterface(context, http_client)
        >>> token = await interface.authenticate()
    """

    interface_name = "standard"

    def __init__(self, context: ConnectorContext, http_client: HttpClient) -> None:
        super().__init__(context, http_client)
        self._base_url = self.context.base_url.rstrip("/")
        self._token: str | None = None

    def _get_oauth_path(self, path: str) -> str:
        """
        获取 OAuth 路径，自动处理 /kapi 前缀

        金蝶的 base_url 可能已包含 /kapi，也可能不包含。
        """
        has_kapi = "/kapi" in self._base_url
        if has_kapi:
            return f"/oauth2/{path}"
        return f"/kapi/oauth2/{path}"

    def _get_api_path(
        self,
        app_id: str,
        form_id: str,
        operation: str,
        api_version: str = "",
    ) -> str:
        """
        获取 API 路径

        Args:
            app_id: 应用标识，如 "sys"
            form_id: 表单标识，如 "isc_demo_basedata_1"，支持层级如 "ar/ar_finarbill"
            operation: 操作类型，如 "query", "save", "queryBi"
            api_version: API 版本前缀，如 "v2"

        Returns:
            API 路径，如 "/kapi/sys/isc_demo_basedata_1/query"
            或 "/kapi/v2/ju06/ar/ar_finarbill/queryBi"
        """
        has_kapi = "/kapi" in self._base_url
        prefix = "" if has_kapi else "/kapi"
        version_part = f"/{api_version}" if api_version else ""
        return f"{prefix}{version_part}/{app_id}/{form_id}/{operation}"

    def _parse_object_type(self, object_type: str) -> tuple[str, str]:
        """
        解析 object_type 为 app_id 和 form_id

        支持格式：
        - "app_id.form_id"，如 "sys.isc_demo_basedata_1"
        - 纯 form_id，此时 app_id 从 settings 获取（默认 "sys"）

        Returns:
            (app_id, form_id)
        """
        if "." in object_type:
            app_id, form_id = object_type.split(".", 1)
            return app_id, form_id

        app_id = self.context.settings.get("app_id", "sys")
        return app_id, object_type

    def _build_request_headers(self) -> dict[str, str]:
        """构建请求头，包含 accesstoken 和 x-acgw-identity"""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["accesstoken"] = self._token

        auth_config = self.get_auth_config()
        identity = auth_config.get("x_acgw_identity") or auth_config.get("x-acgw-identity", "")
        if identity:
            headers["x-acgw-identity"] = identity

        return headers

    @staticmethod
    def _check_response(response: dict[str, Any]) -> dict[str, Any]:
        """
        检查金蝶 API 响应状态

        金蝶响应格式：
        - 成功：{errorCode: "0", data: {...}, status: true}
        - 失败：{errorCode: "xxx", message: "...", status: false}

        Returns:
            响应中的 data 字段

        Raises:
            KdCosmicAdapterAuthError: 认证相关错误
            KdCosmicAdapterAPIError: API 调用失败
        """
        if not isinstance(response, dict):
            raise KdCosmicAdapterAPIError(
                "Invalid response format",
                response_body=response,
            )

        error_code = response.get("errorCode")
        status = response.get("status")

        # 错误码为 "0" 或 0 表示成功
        if str(error_code) == "0" and status is True:
            return response.get("data", {})

        # 提取错误信息
        message = response.get("message", "")
        if not message and "data" in response and isinstance(response["data"], dict):
            error_info = response["data"].get("errorInfo", [])
            if isinstance(error_info, list) and error_info:
                message = "; ".join(
                    str(item.get("msg", "")) for item in error_info if item.get("msg")
                )

        if not message:
            message = response.get("description", "Unknown API error")

        # 认证相关错误码
        auth_error_codes = {"2501", "2551", "401", "403"}
        if str(error_code) in auth_error_codes:
            raise KdCosmicAdapterAuthError(
                message,
                details={"error_code": error_code, "response": response},
            )

        raise KdCosmicAdapterAPIError(
            message,
            api_code=str(error_code) if error_code is not None else None,
            response_body=response,
            details={"error_code": error_code},
        )

    async def authenticate(self) -> dict[str, Any]:
        """
        OAuth2 Accesstoken 认证

        Returns:
            {"access_token": "...", "refresh_token": "...", "expires_in": 3600}

        Raises:
            KdCosmicAdapterAuthError: 认证失败
        """
        auth_config = self.get_auth_config()

        client_id = auth_config.get("client_id")
        client_secret = auth_config.get("client_secret")
        username = auth_config.get("username")
        account_id = auth_config.get("accountId") or auth_config.get("account_id")

        missing = []
        if not client_id:
            missing.append("client_id")
        if not client_secret:
            missing.append("client_secret")
        if not username:
            missing.append("username")
        if not account_id:
            missing.append("accountId")

        if missing:
            raise KdCosmicAdapterAuthError(
                f"Missing required credentials: {', '.join(missing)}",
                details={"missing": missing},
            )

        request_body = {
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "accountId": account_id,
            "language": auth_config.get("language", "zh_CN"),
            "nonce": secrets.token_hex(16),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        url = self._get_oauth_path("getToken")

        try:
            response = await self.http_client.post(
                url,
                json=request_body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )

            data = self._check_response(response)
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 7200)

            if not access_token:
                raise KdCosmicAdapterAuthError(
                    "access_token not found in response",
                    details={"response": response},
                )

            self._token = access_token

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": (
                    int(expires_in) // 1000
                    if isinstance(expires_in, (int, float)) and expires_in > 10000
                    else int(expires_in)
                ),
            }

        except KdCosmicAdapterAuthError:
            raise
        except Exception as e:
            from qdata_adapter.exceptions import ResponseError
            if isinstance(e, ResponseError):
                raise
            raise KdCosmicAdapterAuthError(
                f"Authentication failed: {e}",
                details={"error": str(e)},
            ) from e

    async def refresh_token(self) -> dict[str, Any]:
        """
        刷新 OAuth2 Token

        Returns:
            新的认证凭证字典
        """
        auth_config = self.get_auth_config()
        client_id = auth_config.get("client_id")
        refresh_token_value = auth_config.get("refresh_token")
        account_id = auth_config.get("accountId") or auth_config.get("account_id")

        if not refresh_token_value:
            logger.warning("No refresh_token available, falling back to authenticate")
            return await self.authenticate()

        request_body = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_value,
            "accountId": account_id,
            "nonce": secrets.token_hex(16),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        url = self._get_oauth_path("refreshToken")

        try:
            response = await self.http_client.post(
                url,
                json=request_body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )

            data = self._check_response(response)
            access_token = data.get("access_token")
            new_refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 7200)

            if not access_token:
                raise KdCosmicAdapterAuthError(
                    "access_token not found in refresh response",
                    details={"response": response},
                )

            self._token = access_token

            return {
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "expires_in": (
                    int(expires_in) // 1000
                    if isinstance(expires_in, (int, float)) and expires_in > 10000
                    else int(expires_in)
                ),
            }

        except KdCosmicAdapterAuthError:
            raise
        except Exception as e:
            from qdata_adapter.exceptions import ResponseError
            if isinstance(e, ResponseError):
                raise
            raise KdCosmicAdapterAuthError(
                f"Token refresh failed: {e}",
                details={"error": str(e)},
            ) from e

    async def list_objects(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        列表查询（自动翻页）

        调用金蝶 OpenAPI 查询接口：POST /kapi/{appId}/{formId}/query
        支持自定义 API 版本和操作类型。

        Args:
            object_type: 对象类型，格式 "app_id.form_id" 或纯 "form_id"
                form_id 支持层级路径，如 "ju06.ar/ar_finarbill"
            filters: 过滤条件，支持：
                - filterString: 过滤字符串
                - _api_version: API 版本前缀，如 "v2"
                - _operation: 操作类型，如 "queryBi"，默认 "query"
                - 其他字段会放入 data 中
            page_size: 每页大小

        Yields:
            单条记录字典
        """
        filters = dict(filters) if filters else {}
        app_id, form_id = self._parse_object_type(object_type)

        # 提取控制参数（不参与请求体）
        api_version = filters.pop("_api_version", "")
        operation = filters.pop("_operation", "query")

        page = 1
        has_more = True

        while has_more:
            if operation == "query":
                # 标准 query 接口请求体格式
                query_data: dict[str, Any] = {
                    "formId": form_id,
                    "pageSize": page_size,
                    "pageNo": page,
                }

                # 提取 filterString 和其他参数
                if "filterString" in filters:
                    query_data["filterString"] = filters["filterString"]
                if "filter_string" in filters:
                    query_data["filterString"] = filters["filter_string"]
                if "orderString" in filters:
                    query_data["orderString"] = filters["orderString"]
                if "fieldKeys" in filters:
                    query_data["fieldKeys"] = filters["fieldKeys"]

                # 其他自定义参数
                for key, value in filters.items():
                    if key not in query_data and key not in ("app_id", "filter_string"):
                        query_data[key] = value

                request_body = {"data": query_data}
            else:
                # 非标准操作（如 queryBi），分页参数放根级，过滤条件放 data 内
                request_body = {
                    "data": dict(filters),
                    "pageSize": str(page_size),
                    "pageNo": page,
                }

            api_path = self._get_api_path(app_id, form_id, operation, api_version)

            try:
                response = await self.http_client.post(
                    api_path,
                    json=request_body,
                    headers=self._build_request_headers(),
                )

                result_data = self._check_response(response)
                rows = result_data.get("rows", [])
                headers_info = result_data.get("header", [])

                # 将 header 信息附加到每条记录
                header_names = [h.get("name", f"col_{i}") for i, h in enumerate(headers_info)]

                for row in rows:
                    if isinstance(row, list):
                        # 金蝶返回的是列表形式，按 header 转换为字典
                        record = {}
                        for i, name in enumerate(header_names):
                            record[name] = row[i] if i < len(row) else None
                        yield record
                    elif isinstance(row, dict):
                        yield row
                    else:
                        yield {"value": row}

                # 判断是否还有更多数据
                # 兼容 totalCount / count / lastPage 等多种分页字段
                total = result_data.get("count") or result_data.get("totalCount", 0)
                last_page = result_data.get("lastPage")
                if last_page is not None:
                    has_more = not last_page and len(rows) == page_size
                else:
                    current_count = page * page_size
                    has_more = current_count < total and len(rows) == page_size
                page += 1

            except Exception as e:
                logger.error("Failed to fetch %s list: %s", object_type, e)
                raise KdCosmicAdapterAPIError(
                    f"Failed to list {object_type}",
                    details={"object_type": object_type, "page": page, "error": str(e)},
                ) from e

    async def get_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        """
        获取单个对象

        通过查询接口获取单条记录，使用 ID 作为过滤条件

        Args:
            object_type: 对象类型
            object_id: 对象 ID

        Returns:
            对象数据字典

        Raises:
            NotFoundError: 对象不存在
        """
        app_id, form_id = self._parse_object_type(object_type)

        query_data = {
            "formId": form_id,
            "pageSize": 1,
            "pageNo": 1,
            "filterString": f"id = '{object_id}'",
        }

        request_body = {"data": query_data}
        api_path = self._get_api_path(app_id, form_id, "query")

        try:
            response = await self.http_client.post(
                api_path,
                json=request_body,
                headers=self._build_request_headers(),
            )

            result_data = self._check_response(response)
            rows = result_data.get("rows", [])
            headers_info = result_data.get("header", [])

            if not rows:
                raise NotFoundError(
                    f"{object_type} not found",
                    resource_type=object_type,
                    resource_id=object_id,
                )

            header_names = [h.get("name", f"col_{i}") for i, h in enumerate(headers_info)]
            row = rows[0]

            if isinstance(row, list):
                return {
                    name: row[i] if i < len(row) else None
                    for i, name in enumerate(header_names)
                }
            elif isinstance(row, dict):
                return row
            return {"value": row}

        except NotFoundError:
            raise
        except Exception as e:
            raise KdCosmicAdapterAPIError(
                f"Failed to get {object_type}",
                details={"object_type": object_type, "object_id": object_id, "error": str(e)},
            ) from e

    async def create_object(self, object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        创建对象（保存操作）

        调用金蝶 OpenAPI 保存接口：POST /kapi/{appId}/{formId}/save

        Args:
            object_type: 对象类型
            data: 对象数据

        Returns:
            创建后的对象数据

        Raises:
            ValidationError: 数据验证失败
        """
        app_id, form_id = self._parse_object_type(object_type)

        request_body = {"data": data}
        api_path = self._get_api_path(app_id, form_id, "save")

        try:
            response = await self.http_client.post(
                api_path,
                json=request_body,
                headers=self._build_request_headers(),
            )

            result_data = self._check_response(response)
            return result_data

        except ValidationError:
            raise
        except KdCosmicAdapterAPIError as e:
            if e.api_code and str(e.api_code).startswith("4"):
                raise ValidationError(
                    f"Invalid data for {object_type}: {e.message}",
                    details={"object_type": object_type, "data": data},
                ) from e
            raise
        except Exception as e:
            raise KdCosmicAdapterAPIError(
                f"Failed to create {object_type}",
                details={"object_type": object_type, "data": data, "error": str(e)},
            ) from e

    async def execute_api(
        self,
        api_path: str,
        data: dict[str, Any] | None = None,
        method: str = "POST",
    ) -> dict[str, Any]:
        """
        执行任意 API 接口

        支持直接调用自定义路径的 API，如 /kapi/v2/ju06/ar/ar_finarbill/queryBi

        Args:
            api_path: API 路径，如 "/kapi/v2/ju06/ar/ar_finarbill/queryBi"
            data: 请求体数据
            method: HTTP 方法，默认 POST

        Returns:
            API 响应中的 data 字段

        Raises:
            KdCosmicAdapterAPIError: API 调用失败
        """
        headers = self._build_request_headers()

        try:
            if method.upper() == "POST":
                response = await self.http_client.post(
                    api_path,
                    json=data,
                    headers=headers,
                )
            elif method.upper() == "GET":
                response = await self.http_client.get(
                    api_path,
                    params=data,
                    headers=headers,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return self._check_response(response)

        except (KdCosmicAdapterAPIError, KdCosmicAdapterAuthError, ValueError):
            raise
        except Exception as e:
            logger.error("execute_api failed for %s: %s", api_path, e)
            raise KdCosmicAdapterAPIError(
                f"Failed to execute API {api_path}",
                details={"api_path": api_path, "error": str(e)},
            ) from e

    async def invoke(
        self,
        method: str,
        object_type: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        覆盖基类 invoke，支持自定义 API 路径

        通过 params._api_path 可直接调用任意 API，绕过标准路径构造。

        Args:
            method: API 方法名
            object_type: 对象类型
            data: 请求体数据
            params: 查询参数，支持：
                - _api_path: 自定义 API 路径，如 "/kapi/v2/ju06/ar/ar_finarbill/queryBi"
                - _api_version: API 版本前缀
                - _operation: 自定义操作类型

        Returns:
            API 响应数据
        """
        params = dict(params) if params else {}

        # 如果指定了 _api_path，直接调用 execute_api
        api_path = params.pop("_api_path", None)
        if api_path:
            http_method = "POST"
            if method in ("get", "query"):
                http_method = "POST"
            elif method in ("create", "save", "update"):
                http_method = "POST"
            return await self.execute_api(
                api_path=api_path,
                data=data,
                method=http_method,
            )

        # 如果指定了 _api_version 或 _operation，传递给 list_objects
        if method in ("list", "query"):
            results = []
            async for item in self.list_objects(
                object_type, filters=params, page_size=100
            ):
                results.append(item)
            return {"data": results, "total": len(results)}

        if method == "get":
            object_id = params.get("id")
            if not object_id:
                raise ValueError("'get' method requires params['id']")
            result = await self.get_object(object_type, object_id)
            return {"data": result}

        if method == "create":
            if not data:
                raise ValueError("'create' method requires data")
            result = await self.create_object(object_type, data)
            return {"data": result}

        raise NotImplementedError(
            f"Method '{method}' not implemented. "
            f"Please use execute_api() for custom API calls."
        )

    async def health_check(self) -> bool:
        """
        健康检查

        尝试认证来判断连接是否正常

        Returns:
            True: 连接正常

        Raises:
            KdCosmicAdapterAuthError: 认证失败
            KdCosmicAdapterAPIError: API 调用失败
        """
        await self.authenticate()
        return True


__all__ = ["KdCosmicAdapterStandardInterface"]
