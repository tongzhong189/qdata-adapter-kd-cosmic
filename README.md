# qdata-adapter-kd-cosmic

<p align="center">
  <strong>QDataV2 金蝶云星瀚适配器</strong>
</p>

<p align="center">
  由 <a href="https://www.qeasy.cloud">广东轻亿云软件科技有限公司</a> 开发<br>
  「轻易云数据集成平台」官方适配器
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://pypi.org/project/qdata-adapter-kd-cosmic/"><img src="https://img.shields.io/pypi/v/qdata-adapter-kd-cosmic.svg" alt="PyPI version"></a>
</p>

---

## 📖 简介

`qdata-adapter-kd-cosmic` 是 QDataV2 数据集成平台的官方适配器，用于连接 **金蝶云·星瀚**（原金蝶云·苍穹）企业数字化平台。

### 平台说明

| 产品 | 说明 | 适配器 |
|------|------|--------|
| **金蝶云·星瀚**（原苍穹） | 面向大型企业的 SaaS/PaaS 平台 | `qdata-adapter-kd-cosmic`（本适配器） |
| **金蝶云·星空**（K/3 Cloud） | 面向中小型企业的 ERP | [`qdata-adapter-kd-galaxy`](https://github.com/vincent067/qdata-adapter-kd-galaxy) |
| **金蝶云·星辰** | 面向小微企业的 SaaS | 独立适配器 |

### 多版本支持

本适配器通过 `api_version` 参数支持金蝶星瀚多个版本：

| 版本 | 说明 | 支持状态 |
|------|------|----------|
| `15.x` | 星瀚标准版（默认） | ✅ 已支持 |
| `14.x` | 苍穹 4.0 | 🔄 开发中 |

### 核心能力

- **版本自动路由**: 根据 `api_version` 自动选择对应版本的 API 实现
- **Session 认证**: 支持账套ID + 用户名 + 密码认证
- **完整 CRUD**: 支持查询、创建、更新、删除操作
- **批量操作**: 支持 BatchSave 等批量接口
- **异步迭代**: 分页查询返回 `AsyncIterator`，内存友好

---

## 🚀 快速开始

### 安装

```bash
pip install qdata-adapter-kd-cosmic
```

### 基础用法

```python
import asyncio
from qdata_adapter_kd_cosmic import KdCosmicAdapter
from qdata_adapter import ConnectorContext

async def main():
    context = ConnectorContext(
        connector_id="kd-cosmic-001",
        app_software_code="kd_cosmic",
        base_url="https://your-domain.kingdee.com/kdcosmic",
        auth_config={
            "acct_id": "账套ID",
            "username": "用户名",
            "password": "密码",
            "lcid": 2052,  # 语言代码：2052=简体中文
        },
        api_version="9.0",  # 默认 9.0
    )

    adapter = KdCosmicAdapter(context)

    # 测试连接
    result = await adapter.test_connection()
    print(f"连接状态: {result.status}")

    # 分页查询物料
    async for batch in adapter.execute_query(
        form_id="BD_Material",
        field_keys=["FMaterialId", "FNumber", "FName", "F Specification"],
        filter_string="FDocumentStatus = 'C'",
        page_size=500,
    ):
        for item in batch:
            print(item)

asyncio.run(main())
```

---

## ⚙️ 配置说明

### auth_config 格式

```python
{
    "acct_id": "账套ID",        # 必须，金蝶云星瀚账套唯一标识
    "username": "用户名",       # 必须，登录用户名
    "password": "密码",         # 必须，登录密码
    "lcid": 2052,               # 可选，语言代码，默认 2052（简体中文）
}
```

### settings 配置

```python
{
    "api_version": "9.0",      # 可选，默认 "9.0"，支持 "7.x", "8.x", "9.x"
    "locale": "zh_CN",          # 可选，默认 "zh_CN"
}
```

### ConnectorContext 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `api_version` | 金蝶版本路由 | `"9.0"`, `"8.x"`, `"7.x"` |

---

## 📚 API 文档

### KdCosmicAdapter

适配器主类，继承自 `BaseAppAdapter`。

#### 核心方法

| 方法 | 说明 |
|------|------|
| `authenticate()` | 执行 Session 登录认证 |
| `refresh_token()` | 刷新 Token（金蝶不支持 refresh，重新登录） |
| `list_objects(type, filters, page, page_size)` | 分页查询对象 |
| `get_object(type, id)` | 获取单个对象 |
| `create_object(type, data)` | 创建对象 |
| `update_object(type, id, data)` | 更新对象 |
| `delete_object(type, id)` | 删除对象 |
| `test_connection()` | 连接测试 |

#### 金蝶特有方法

| 方法 | 说明 |
|------|------|
| `execute_api(form_id, operation, data)` | 执行任意金蝶 WebAPI |
| `execute_query(form_id, field_keys, filter_string, ...)` | 分页查询，返回 AsyncIterator |
| `execute_batch(form_id, operation, data_list)` | 批量操作 |

#### 使用示例

```python
# 视图查询（查看单个物料）
material = await adapter.execute_api(
    form_id="BD_Material",
    operation="View",
    data={"Number": "M001"},
)

# 保存操作（创建/更新）
result = await adapter.execute_api(
    form_id="BD_Material",
    operation="Save",
    data={
        "FNumber": "M002",
        "FName": "新物料",
        "F Specification": "规格型号",
    },
)

# 批量保存
results = await adapter.execute_batch(
    form_id="BD_Material",
    operation="BatchSave",
    data_list=[
        {"FNumber": "M003", "FName": "物料3"},
        {"FNumber": "M004", "FName": "物料4"},
    ],
)
```

---

## 🧪 测试

```bash
# 安装开发依赖
make install-dev

# 运行测试（Mock 模式）
make test

# 运行测试（带覆盖率）
make test-cov

# 代码检查
make check
```

---

## 📄 许可与商业政策

本项目采用 **MIT** 开源协议。

---

## 🏢 关于轻易云数据集成平台

**广东轻亿云软件科技有限公司**
专注数据集成与处理，提供企业级 ETL/ELT 解决方案
🌐 官网：[https://www.qeasy.cloud](https://www.qeasy.cloud)
📧 开源项目：opensource@qeasy.cloud
📧 商业咨询：vincent@qeasy.cloud

---

*Powered by [广东轻亿云软件科技有限公司](https://www.qeasy.cloud)*