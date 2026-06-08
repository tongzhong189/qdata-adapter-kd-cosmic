"""
kd-cosmic standard 接口实现

基于金蝶云星空旗舰版 OpenAPI 标准接口：
- 认证：OAuth2 Accesstoken (/kapi/oauth2/getToken)
- 支持完全自定义 API 路径、请求方法和请求体
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

    完全自定义 API 调用：
    - 通过 invoke() 的 params._api_path 指定任意相对路径
    - 通过 params._http_method 指定任意 HTTP 方法
    - 通过 params._custom_body 控制请求体是否包装
    - 通过 execute_custom_api() / raw_request() 直接调用

    Example:
        >>> # 完全自定义接口调用
        >>> result = await interface.execute_custom_api(
        ...     path="/v2/null/basedata/bd_material/qeasyadd",
        ...     method="POST",
        ...     body={"data": [{"number": "Item-001", "name": "test"}]},
        ... )
        >>>
        >>> # 通过 invoke 调用
        >>> result = await interface.invoke(
        ...     "create", "bd_material",
        ...     data={"data": [{"number": "Item-001"}]},
        ...     params={
        ...         "_api_path": "/v2/null/basedata/bd_material/qeasyadd",
        ...         "_custom_body": True,
        ...     }
        ... )
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
        获取标准 API 路径

        支持通过 settings 自定义路径格式：
        - api_path_prefix: 路径前缀，如 "/kapi/openapi"
        - api_path_template: 完整路径模板

        Args:
            app_id: 应用标识
            form_id: 表单标识
            operation: 操作类型
            api_version: API 版本前缀

        Returns:
            API 路径，如 "/kapi/sys/isc_demo_basedata_1/query"
        """
        has_kapi = "/kapi" in self._base_url

        path_prefix = self.context.settings.get("api_path_prefix", "")
        if path_prefix:
            prefix = path_prefix
        else:
            prefix = "" if has_kapi else "/kapi"

        path_template = self.context.settings.get("api_path_template", "")
        if path_template:
            version_part = api_version if api_version else ""
            return path_template.format(
                prefix=prefix,
                version=version_part,
                app_id=app_id,
                form_id=form_id,
                operation=operation,
            )

        version_part = f"/{api_version}" if api_version else ""
        return f"{prefix}{version_part}/{app_id}/{form_id}/{operation}"

    def _parse_object_type(self, object_type: str) -> tuple[str, str]:
        """
        解析 object_type 为 app_id 和 form_id

        支持格式：
        - "app_id.form_id"
        - 纯 form_id，此时 app_id 从 settings 获取（默认 "sys"）

        Returns:
            (app_id, form_id)
        """
        if "." in object_type:
            app_id, form_id = object_type.split(".", 1)
            return app_id, form_id

        app_id = self.context.settings.get("app_id", "sys")
        return app_id, object_type

    def _build_request_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """
        构建请求头

        Args:
            extra: 额外请求头

        Returns:
            请求头字典
        """
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

        if extra:
            headers.update(extra)

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

        if str(error_code) == "0" and status is True:
            return response.get("data", {})

        message = response.get("message", "")
        if not message and "data" in response and isinstance(response["data"], dict):
            error_info = response["data"].get("errorInfo", [])
            if isinstance(error_info, list) and error_info:
                message = "; ".join(
                    str(item.get("msg", "")) for item in error_info if item.get("msg")
                )

        if not message:
            message = response.get("description", "Unknown API error")

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
        body/params/headers 完全透传，**不做 errorCode 检查**。

        Args:
            path: API 相对路径，如 "/v2/null/basedata/bd_material/qeasyadd"
            method: HTTP 方法，默认 POST
            body: 请求体，完全透传
            params: URL 查询参数
            headers: 额外请求头

        Returns:
            原始 API 响应字典
        """
        # 确保 path 以 / 开头
        if not path.startswith("/"):
            path = "/" + path

        headers = self._build_request_headers(extra=headers)

        try:
            method_upper = method.upper()
            if method_upper == "POST":
                response = await self.http_client.post(
                    path,
                    json=body,
                    params=params,
                    headers=headers,
                )
            elif method_upper == "GET":
                response = await self.http_client.get(
                    path,
                    params=params or body,
                    headers=headers,
                )
            elif method_upper == "PUT":
                response = await self.http_client.put(
                    path,
                    json=body,
                    params=params,
                    headers=headers,
                )
            elif method_upper == "DELETE":
                response = await self.http_client.delete(
                    path,
                    params=params or body,
                    headers=headers,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return response if isinstance(response, dict) else {"response": response}

        except ValueError:
            raise
        except Exception as e:
            logger.error("raw_request failed for %s: %s", path, e)
            raise KdCosmicAdapterAPIError(
                f"Failed to execute raw request {path}",
                details={"path": path, "method": method, "error": str(e)},
            ) from e

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
        # 确保 path 以 / 开头
        if not path.startswith("/"):
            path = "/" + path

        headers = self._build_request_headers(extra=headers)

        try:
            method_upper = method.upper()
            if method_upper == "POST":
                response = await self.http_client.post(
                    path,
                    json=body,
                    params=params,
                    headers=headers,
                )
            elif method_upper == "GET":
                response = await self.http_client.get(
                    path,
                    params=params or body,
                    headers=headers,
                )
            elif method_upper == "PUT":
                response = await self.http_client.put(
                    path,
                    json=body,
                    params=params,
                    headers=headers,
                )
            elif method_upper == "DELETE":
                response = await self.http_client.delete(
                    path,
                    params=params or body,
                    headers=headers,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return self._check_response(response)

        except (KdCosmicAdapterAPIError, KdCosmicAdapterAuthError, ValueError):
            raise
        except Exception as e:
            logger.error("execute_custom_api failed for %s: %s", path, e)
            raise KdCosmicAdapterAPIError(
                f"Failed to execute custom API {path}",
                details={"path": path, "method": method, "error": str(e)},
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

        Args:
            object_type: 对象类型
            filters: 过滤条件
            page_size: 每页大小

        Yields:
            单条记录字典
        """
        filters = dict(filters) if filters else {}
        app_id, form_id = self._parse_object_type(object_type)

        api_version = filters.pop("_api_version", "")
        operation = filters.pop("_operation", "query")

        page = 1
        has_more = True

        while has_more:
            if operation == "query":
                query_data: dict[str, Any] = {
                    "formId": form_id,
                    "pageSize": page_size,
                    "pageNo": page,
                }

                if "filterString" in filters:
                    query_data["filterString"] = filters["filterString"]
                if "filter_string" in filters:
                    query_data["filterString"] = filters["filter_string"]
                if "orderString" in filters:
                    query_data["orderString"] = filters["orderString"]
                if "fieldKeys" in filters:
                    query_data["fieldKeys"] = filters["fieldKeys"]

                for key, value in filters.items():
                    if key not in query_data and key not in ("app_id", "filter_string"):
                        query_data[key] = value

                request_body = {"data": query_data}
            else:
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

                header_names = [h.get("name", f"col_{i}") for i, h in enumerate(headers_info)]

                for row in rows:
                    if isinstance(row, list):
                        record = {}
                        for i, name in enumerate(header_names):
                            record[name] = row[i] if i < len(row) else None
                        yield record
                    elif isinstance(row, dict):
                        yield row
                    else:
                        yield {"value": row}

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

        Args:
            object_type: 对象类型
            object_id: 对象 ID

        Returns:
            对象数据字典
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

        Args:
            object_type: 对象类型
            data: 对象数据

        Returns:
            创建后的对象数据
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

    async def health_check(self) -> bool:
        """
        健康检查

        Returns:
            True: 连接正常
        """
        await self.authenticate()
        return True


__all__ = ["KdCosmicAdapterStandardInterface"]
