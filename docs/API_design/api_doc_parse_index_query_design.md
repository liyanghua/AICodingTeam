# API 文档解析、索引与精准查询系统设计

> 版本：v1.0  
> 目标：把内部/外部 API 文档解析成可查询、可验证、可编排、可被 Agent Runtime 调用的 API 资产库。  
> 适用对象：OpenAPI / Swagger、Markdown API 文档、HTML API 文档、Postman Collection、内部接口说明文档、数据 API 文档。

---

## 0. 一句话定义

本系统不是普通 RAG 知识库，而是一个：

```text
API Document Compiler
+ API Asset Index
+ Precision API Query Engine
+ ToolSpec Generator
```

它的核心任务是：

```text
API 文档
  → 结构化解析
  → 标准化 API Asset Card
  → 多索引
  → 精准查询
  → 可执行 ToolSpec / API 调用建议 / 缺口检查
```

普通 RAG 的核心对象是 `chunk`。  
本系统的核心对象是：

```text
ApiService
EndpointOperation
Parameter
RequestBody
ResponseBody
SchemaObject
AuthScheme
ErrorCode
Example
RateLimit
ToolSpec
SourceSpan
```

### 0.1 当前 P0：数仓 API 双文档匹配独立能力包

当前先把通用架构收敛成一个可闭环验证的独立能力包：

```text
db-archaeologist 两份数仓 API 文档
  → parse
  → index
  → 业务语言匹配 API
  → 业务输出字段匹配 API 返回字段
  → 字段覆盖评价
  → CLI smoke
```

P0 输入固定为：

- `智能体数仓完整接口文档_修复后逐接口完整格式版.md`：请求参数、curl、返回示例、返回字段说明来源。
- `智能体数仓完整接口文档_全量验证版.md`：接口序号、接口名称、业务模块、分析域、修复后可用 URL、修复后入参、验证状态来源。

P0 独立实现目录为 `api_doc_matcher/`。它不依赖 `app_generation`，不调用真实 API，不读取 `.env`，不做 live probe。后续 Agent 只消费该能力包暴露的稳定函数或 CLI 输出。

P0 的业务文档验证入口是 `match-section`：从业务文档中抽取指定流程段落，结构化提取标题、目的、数据来源、执行动作和输出字段，再分别运行 `title_only`、`enriched_context`、`field_coverage_rerank` 三种策略。默认推荐 `field_coverage_rerank`，它先召回候选 API，再用输出字段覆盖率重排并生成多 API 覆盖方案；字段如“功能 / 风格 / 主图元素 / 爆款原因”若不能由 API 原生返回字段稳定提供，应标记为 `derived_or_manual_required`，不得强行误配。

#### P0 核心评价指标：`business_field_coverage_score`

这个指标衡量“业务文档要求的输出字段”被一个或多个数仓 API 返回字段支撑的程度，而不是只看 API top-k 是否命中。

```text
business_field_coverage_score =
  0.5 * required_field_coverage_rate
+ 0.3 * high_confidence_mapping_rate
+ 0.2 * confirmed_or_reviewable_rate
```

字段定义：

- `required_field_coverage_rate`：必填业务字段中，能找到 API 字段候选的比例。
- `high_confidence_mapping_rate`：匹配置信度 `>= 0.85` 的字段比例。
- `confirmed_or_reviewable_rate`：状态为 `matched` 或 `suggested_needs_review` 的字段比例。

CLI smoke 输出必须包含：

```json
{
  "business_field_coverage_score": 0.82,
  "required_total": 10,
  "covered_required": 8,
  "high_confidence": 6,
  "missing_required_fields": ["支付买家数", "交易指数"]
}
```

验收门槛：

```text
P0 smoke >= 0.60
可进入人工工作台 >= 0.75
可推荐为默认映射 >= 0.85
```

所有字段映射结果都只是建议，不能自动变成 confirmed；人工确认仍由后续工作台或 Agent 协作流程完成。

---

## 1. 需要解决的核心问题

### 1.1 业务问题

企业内部 API 文档通常存在以下问题：

1. 文档格式不统一：OpenAPI、Markdown、HTML、Word、Postman、飞书文档、接口表格混杂。
2. 接口描述不完整：有 URL，但缺参数；有参数，但缺字段类型；有返回样例，但缺 schema。
3. 接口相似但语义不同：例如“商品列表”“商品详情”“商品搜索”“商品画像”容易混淆。
4. 文档和真实接口不一致：文档写了字段，但实际响应没有；或者实际接口新增字段但文档没更新。
5. Agent 难以准确选工具：仅靠文本 embedding 很容易选错 API 或漏掉必要参数。
6. 查询结果不可验证：用户问“哪个接口能查商品销量”，系统必须返回接口、参数、示例、来源位置和置信度。

### 1.2 技术目标

系统要支持：

```text
1. API 文档自动解析
2. OpenAPI / Swagger 标准解析
3. Markdown / HTML 非标准文档抽取
4. API Asset Card 标准化
5. Endpoint / 参数 / schema / auth / 示例多粒度索引
6. 精准查询：接口定位、字段解释、调用方式、参数补全
7. Agent ToolSpec 生成
8. 缺口检查：缺 auth、缺参数、缺 response schema、缺示例、缺错误码
9. 可追溯引用：source_doc / heading_path / line_start / line_end / snippet
10. 可持续增量更新：版本 diff / re-index / 变更影响分析
```

---

## 2. 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│                    API Document Sources                       │
│ OpenAPI YAML/JSON | Markdown | HTML | Postman | Internal Docs │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 1. Ingestion Layer                                            │
│ - 文件接入 / URL 接入 / Git 接入 / 文档库接入                  │
│ - 文件类型识别                                                │
│ - 版本 hash / metadata / source snapshot                       │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. Parser Layer                                               │
│ - OpenAPI Parser: YAML/JSON/$ref/bundle/validate               │
│ - Markdown Parser: heading/table/code/curl/json block          │
│ - HTML Parser: DOM/section/table/code extraction               │
│ - Postman Parser: collection/item/request/response             │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. API Semantic Compiler                                      │
│ - endpoint candidate extraction                               │
│ - parameter extraction                                        │
│ - request/response schema extraction                          │
│ - auth/rate-limit/error-code extraction                       │
│ - examples extraction                                         │
│ - confidence + source span                                    │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. Canonical API Asset Store                                  │
│ - ApiService                                                  │
│ - EndpointOperation                                           │
│ - Parameter / Schema / Example                                │
│ - AuthScheme / ErrorCode / RateLimit                          │
│ - SourceSpan                                                  │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. Multi-Index Layer                                          │
│ - Structure Index: service/tag/path/method/section             │
│ - Lexical Index: BM25/exact phrase/path/field                  │
│ - Vector Index: endpoint intent/schema/example/business text   │
│ - Entity Index: domain entity/field/tool/auth/platform         │
│ - Graph Index: service-endpoint-param-schema-tool relation     │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 6. Query Orchestrator                                         │
│ - query classification                                        │
│ - query planning                                              │
│ - hybrid retrieval                                            │
│ - endpoint card hydration                                     │
│ - rerank                                                      │
│ - grounding validation                                        │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ 7. Output Layer                                               │
│ - API 精准问答                                                │
│ - API Asset Card                                              │
│ - curl / Python / TypeScript 调用示例                          │
│ - Agent ToolSpec / Function Schema                            │
│ - API 缺口检查报告                                            │
│ - source citation                                             │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 输入文档类型与解析策略

### 3.1 OpenAPI / Swagger

优先级最高。只要存在 OpenAPI YAML/JSON，就应作为主数据源。

处理步骤：

```text
1. load yaml/json
2. validate spec
3. resolve $ref
4. bundle multi-file spec
5. normalize OpenAPI 2.0 / 3.0 / 3.1 difference
6. extract service / endpoints / schemas / auth / examples
7. preserve source pointer
```

适配对象：

```text
openapi
info
tags
servers
paths
components.schemas
components.parameters
components.responses
components.securitySchemes
security
examples
requestBody
responses
```

### 3.2 Markdown API 文档

典型结构：

```md
# 商品 API

## 获取商品详情

GET /api/v1/products/{id}

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | string | 是 | 商品 ID |

### 返回示例

```json
{
  "id": "p_001",
  "name": "桌布",
  "sales": 1200
}
```
```

解析策略：

```text
1. Markdown AST
2. heading tree
3. code block classification: json / curl / http / bash / yaml
4. table classification: params / response fields / error codes
5. endpoint regex extraction: METHOD + PATH
6. section context binding
7. LLM schema repair
8. source span preservation
```

### 3.3 HTML API 文档

处理步骤：

```text
1. fetch/save HTML snapshot
2. DOM parse
3. extract headings / anchors / tables / code blocks
4. normalize to intermediate Markdown-like blocks
5. run Markdown-like API extraction pipeline
```

### 3.4 Postman Collection

处理步骤：

```text
1. parse collection json
2. extract item/request/response
3. map to EndpointOperation
4. infer auth/header/body/examples
5. optional convert to OpenAPI-like structure
```

### 3.5 内部接口表格

很多企业内部接口文档是表格：

```text
接口名称 | URL | 方法 | 请求参数 | 返回字段 | 负责人 | 备注
```

处理策略：

```text
1. table header semantic classification
2. row-level endpoint candidate extraction
3. parameter cell parsing
4. response field cell parsing
5. owner / domain / permission extraction
6. confidence scoring
```

---

## 4. 标准化数据模型：API Asset Card

### 4.1 顶层对象

```python
from typing import Any, Literal
from pydantic import BaseModel, Field

class SourceSpan(BaseModel):
    source_id: str
    source_type: Literal["openapi", "markdown", "html", "postman", "table", "manual"]
    source_uri: str | None = None
    heading_path: list[str] = []
    line_start: int | None = None
    line_end: int | None = None
    json_pointer: str | None = None
    html_selector: str | None = None
    snippet: str | None = None

class ApiService(BaseModel):
    service_id: str
    name: str
    title: str | None = None
    description: str | None = None
    version: str | None = None
    base_urls: list[str] = []
    domain: str | None = None
    owner: str | None = None
    tags: list[str] = []
    source_spans: list[SourceSpan] = []
```

### 4.2 EndpointOperation

```python
class Parameter(BaseModel):
    name: str
    location: Literal["path", "query", "header", "cookie", "body"]
    required: bool = False
    type: str | None = None
    format: str | None = None
    description: str | None = None
    enum: list[Any] | None = None
    default: Any | None = None
    example: Any | None = None
    source_spans: list[SourceSpan] = []

class SchemaField(BaseModel):
    name: str
    path: str
    type: str | None = None
    required: bool = False
    description: str | None = None
    enum: list[Any] | None = None
    example: Any | None = None
    source_spans: list[SourceSpan] = []

class SchemaObject(BaseModel):
    schema_id: str
    name: str | None = None
    type: str | None = None
    description: str | None = None
    fields: list[SchemaField] = []
    raw_schema: dict[str, Any] | None = None
    source_spans: list[SourceSpan] = []

class RequestBody(BaseModel):
    content_type: str | None = None
    required: bool = False
    schema_ref: str | None = None
    schema: SchemaObject | None = None
    example: Any | None = None
    source_spans: list[SourceSpan] = []

class ResponseBody(BaseModel):
    status_code: str
    description: str | None = None
    content_type: str | None = None
    schema_ref: str | None = None
    schema: SchemaObject | None = None
    example: Any | None = None
    source_spans: list[SourceSpan] = []

class AuthRequirement(BaseModel):
    type: Literal["apiKey", "http", "oauth2", "openIdConnect", "none", "unknown"]
    name: str | None = None
    location: Literal["header", "query", "cookie", "none", "unknown"] | None = None
    scheme: str | None = None
    scopes: list[str] = []
    description: str | None = None

class ErrorCode(BaseModel):
    code: str
    http_status: str | None = None
    message: str | None = None
    reason: str | None = None
    solution: str | None = None
    source_spans: list[SourceSpan] = []

class Example(BaseModel):
    example_id: str
    example_type: Literal["curl", "http", "python", "typescript", "request_json", "response_json"]
    content: str
    description: str | None = None
    source_spans: list[SourceSpan] = []

class EndpointOperation(BaseModel):
    operation_id: str
    service_id: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str
    summary: str | None = None
    description: str | None = None
    tags: list[str] = []
    business_intents: list[str] = []
    domain_entities: list[str] = []
    parameters: list[Parameter] = []
    request_body: RequestBody | None = None
    responses: list[ResponseBody] = []
    auth: list[AuthRequirement] = []
    error_codes: list[ErrorCode] = []
    examples: list[Example] = []
    rate_limit: str | None = None
    deprecated: bool = False
    confidence: float = 1.0
    source_spans: list[SourceSpan] = []
```

### 4.3 ToolSpec

用于 Agent Runtime 调用。

```python
class ToolSpec(BaseModel):
    tool_id: str
    name: str
    description: str
    operation_id: str
    method: str
    url_template: str
    auth_required: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    required_params: list[str] = []
    examples: list[Example] = []
    source_operation_id: str
```

ToolSpec 设计原则：

```text
1. 一个 ToolSpec 对应一个稳定的 EndpointOperation
2. input_schema 只暴露 Agent 必须填写的字段
3. auth / base_url / headers 不应该让 Agent 自由生成，应由 runtime 注入
4. response_schema 应该尽可能简化，避免把完整 OpenAPI schema 直接塞给模型
5. 每个 ToolSpec 必须反向引用 source_operation_id 和 source_spans
```

---

## 5. Parser Layer 详细设计

### 5.1 文件类型识别

```python
def detect_doc_type(file_path: str, content: str) -> str:
    if file_path.endswith((".yaml", ".yml", ".json")):
        if "openapi" in content or "swagger" in content:
            return "openapi"
        if "info" in content and "item" in content and "request" in content:
            return "postman"
    if file_path.endswith(".md"):
        return "markdown"
    if file_path.endswith((".html", ".htm")):
        return "html"
    return "unknown"
```

### 5.2 OpenAPI Parser

核心职责：

```text
1. parse YAML/JSON
2. validate OpenAPI spec
3. resolve $ref
4. normalize paths and methods
5. extract components.schemas
6. extract securitySchemes
7. extract endpoint operations
8. preserve JSON pointer source
```

伪代码：

```python
def parse_openapi_spec(file_path: str) -> list[EndpointOperation]:
    raw = load_yaml_or_json(file_path)
    validate_openapi(raw)
    bundled = resolve_refs(raw)

    service = extract_service(bundled)
    schemas = extract_components_schemas(bundled)
    security_schemes = extract_security_schemes(bundled)

    operations = []
    for path, path_item in bundled.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() not in ["get", "post", "put", "patch", "delete", "head", "options"]:
                continue
            operations.append(
                build_endpoint_operation(
                    service=service,
                    method=method.upper(),
                    path=path,
                    operation=operation,
                    path_item=path_item,
                    schemas=schemas,
                    security_schemes=security_schemes,
                    source_pointer=f"/paths/{escape_json_pointer(path)}/{method}"
                )
            )
    return operations
```

### 5.3 Markdown Parser

核心职责：

```text
1. Markdown AST
2. heading path
3. line range
4. table extraction
5. code block extraction
6. endpoint candidate extraction
7. section-to-endpoint binding
```

Endpoint 候选识别规则：

```regex
\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[A-Za-z0-9_{}:\-./?=&]+)
```

Curl 识别规则：

```regex
curl\s+(-X\s+)?(GET|POST|PUT|PATCH|DELETE)?\s+['\"]?https?://
```

路径识别规则：

```regex
(/[A-Za-z0-9_{}:\-./]+)
```

表格分类规则：

```text
如果表头包含：参数 / 参数名 / 字段 / name / type / required / 必填 / description
  → parameter_table 或 schema_table

如果表头包含：状态码 / code / message / 错误码 / 原因 / 解决方案
  → error_code_table

如果表头包含：字段 / 类型 / 说明 / 示例
  → response_schema_table
```

Markdown section 到 Endpoint 的绑定策略：

```text
1. 如果当前 section 标题或正文包含 METHOD + PATH，创建 EndpointOperation
2. 当前 section 下的参数表、请求示例、返回示例、错误码表默认绑定到该 endpoint
3. 如果子 section 中出现新 METHOD + PATH，则创建新的 endpoint，不继承父 endpoint 的参数表
4. 如果多个 endpoint 共用一个“认证方式”章节，则通过 graph edge 共享 AuthRequirement
```

### 5.4 HTML Parser

建议先转成统一 block：

```python
class DocBlock(BaseModel):
    block_id: str
    block_type: str  # heading/table/code/paragraph/list
    text: str
    html: str | None = None
    heading_path: list[str] = []
    source_span: SourceSpan
```

处理流程：

```text
HTML
  → DOM parse
  → heading/table/code/pre extraction
  → DocBlock stream
  → API Semantic Compiler
```

### 5.5 LLM Extraction Repair

对于非标准文档，规则抽取后要用 LLM 修复，但不能让 LLM 自由发挥。

LLM 只做：

```text
1. 补齐字段类型
2. 判断表格属于请求参数还是返回字段
3. 从自然语言描述中抽取业务意图
4. 从示例 JSON 推断 schema
5. 合并同一个 endpoint 的分散描述
```

LLM 禁止做：

```text
1. 发明不存在的接口
2. 发明不存在的参数
3. 发明不存在的返回字段
4. 修改 source span
5. 不带证据地生成认证方式
```

LLM 输出必须符合 Pydantic schema，并通过 validator。

---

## 6. API Semantic Compiler

### 6.1 编译流程

```text
Parsed Blocks / OpenAPI Objects
  ↓
Endpoint Candidate Extraction
  ↓
Endpoint Deduplication
  ↓
Parameter Binding
  ↓
Request / Response Schema Inference
  ↓
Auth / Error / RateLimit Extraction
  ↓
Example Binding
  ↓
Business Intent Tagging
  ↓
Validation & Confidence Scoring
  ↓
Canonical API Asset Card
```

### 6.2 Endpoint 去重

同一接口可能在多个位置出现：

```text
GET /products/{id}
GET /api/v1/products/{product_id}
```

去重 key：

```text
service_id + method + normalized_path
```

path normalization：

```text
/products/{id}              → /products/{param}
/products/:id               → /products/{param}
/products/{product_id}      → /products/{param}
/api/v1/products/{id}       → /api/v1/products/{param}
```

合并策略：

```text
1. OpenAPI 来源优先级最高
2. 文档越新的 source 优先级更高
3. 参数信息取并集，但冲突字段标记 conflict
4. 示例可以保留多个
5. description 可以合并，但必须保留 source span
```

### 6.3 Schema 推断

从 JSON 示例推断 schema：

```json
{
  "id": "p_001",
  "name": "桌布",
  "sales": 1200,
  "tags": ["防水", "防油"]
}
```

推断为：

```json
{
  "type": "object",
  "properties": {
    "id": {"type": "string"},
    "name": {"type": "string"},
    "sales": {"type": "integer"},
    "tags": {
      "type": "array",
      "items": {"type": "string"}
    }
  }
}
```

注意：示例推断的 schema 置信度低于 OpenAPI schema。

### 6.4 置信度评分

```text
confidence =
  0.30 * endpoint_confidence
+ 0.20 * parameter_confidence
+ 0.20 * schema_confidence
+ 0.10 * auth_confidence
+ 0.10 * example_confidence
+ 0.10 * source_quality
```

来源权重：

```text
OpenAPI validated spec        1.00
Postman Collection            0.85
Markdown with tables/examples 0.75
HTML docs                     0.70
Free-form text                0.45
LLM inferred only             0.30
```

---

## 7. 存储设计

### 7.1 关系型表

MVP 可用 SQLite，生产建议 PostgreSQL。

```sql
CREATE TABLE api_services (
  service_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  title TEXT,
  description TEXT,
  version TEXT,
  domain TEXT,
  owner TEXT,
  tags_json TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE endpoint_operations (
  operation_id TEXT PRIMARY KEY,
  service_id TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  normalized_path TEXT NOT NULL,
  summary TEXT,
  description TEXT,
  tags_json TEXT,
  business_intents_json TEXT,
  domain_entities_json TEXT,
  deprecated INTEGER DEFAULT 0,
  confidence REAL DEFAULT 1.0,
  raw_json TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE api_parameters (
  parameter_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  name TEXT NOT NULL,
  location TEXT NOT NULL,
  required INTEGER DEFAULT 0,
  type TEXT,
  format TEXT,
  description TEXT,
  enum_json TEXT,
  default_json TEXT,
  example_json TEXT,
  raw_json TEXT
);

CREATE TABLE api_schemas (
  schema_id TEXT PRIMARY KEY,
  service_id TEXT,
  operation_id TEXT,
  name TEXT,
  type TEXT,
  description TEXT,
  raw_schema_json TEXT
);

CREATE TABLE schema_fields (
  field_id TEXT PRIMARY KEY,
  schema_id TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  type TEXT,
  required INTEGER DEFAULT 0,
  description TEXT,
  enum_json TEXT,
  example_json TEXT
);

CREATE TABLE api_examples (
  example_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  example_type TEXT NOT NULL,
  content TEXT NOT NULL,
  description TEXT
);

CREATE TABLE api_auth_requirements (
  auth_id TEXT PRIMARY KEY,
  operation_id TEXT,
  service_id TEXT,
  type TEXT NOT NULL,
  name TEXT,
  location TEXT,
  scheme TEXT,
  scopes_json TEXT,
  description TEXT
);

CREATE TABLE api_error_codes (
  error_id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  code TEXT NOT NULL,
  http_status TEXT,
  message TEXT,
  reason TEXT,
  solution TEXT
);

CREATE TABLE source_spans (
  span_id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_uri TEXT,
  heading_path_json TEXT,
  line_start INTEGER,
  line_end INTEGER,
  json_pointer TEXT,
  html_selector TEXT,
  snippet TEXT
);
```

### 7.2 FTS 表

```sql
CREATE VIRTUAL TABLE endpoint_fts USING fts5(
  operation_id UNINDEXED,
  service_id UNINDEXED,
  method,
  path,
  summary,
  description,
  tags,
  business_intents,
  domain_entities,
  parameter_names,
  schema_field_names,
  examples
);
```

### 7.3 Graph Edge 表

```sql
CREATE TABLE graph_edges (
  edge_id TEXT PRIMARY KEY,
  src_type TEXT NOT NULL,
  src_id TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  dst_type TEXT NOT NULL,
  dst_id TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  metadata_json TEXT
);
```

常见关系：

```text
Service HAS_ENDPOINT EndpointOperation
Endpoint HAS_PARAMETER Parameter
Endpoint HAS_REQUEST_SCHEMA SchemaObject
Endpoint HAS_RESPONSE_SCHEMA SchemaObject
Schema HAS_FIELD SchemaField
Endpoint REQUIRES_AUTH AuthRequirement
Endpoint HAS_EXAMPLE Example
Endpoint RETURNS_ERROR ErrorCode
Endpoint SUPPORTS_INTENT BusinessIntent
Endpoint USES_ENTITY DomainEntity
Endpoint COMPILES_TO ToolSpec
```

---

## 8. 索引设计

### 8.1 Structure Index

用于：

```text
1. 按 service/tag/path/method 定位
2. endpoint card hydration
3. source citation
4. 文档结构回溯
```

### 8.2 Lexical Index

用于：

```text
1. 精确 path 查询：/products/{id}
2. method 查询：GET product detail
3. field 查询：sales_volume / 销量
4. API 名称查询：商品详情接口
5. exact phrase 查询：付费竞争强度
```

### 8.3 Vector Index

建议建 4 类向量。

#### endpoint_intent_vector

文本：

```text
接口名称 + summary + description + business_intents + domain_entities
```

用于：

```text
“哪个接口可以查商品销量？”
“如何获取订单支付状态？”
```

#### endpoint_schema_vector

文本：

```text
参数名 + 参数说明 + 返回字段名 + 字段说明
```

用于：

```text
“哪个接口返回 buyer_id？”
“哪个接口需要 category_id？”
```

#### example_vector

文本：

```text
curl / request example / response example
```

用于：

```text
“有没有调用示例？”
“这个接口怎么传 body？”
```

#### tool_usage_vector

文本：

```text
面向 Agent 的工具用途描述
```

用于：

```text
“Agent 要查商品库存应该用哪个工具？”
```

### 8.4 Entity Index

实体类型：

```text
api_service
endpoint
method
path
parameter
schema_field
domain_entity
business_intent
auth_scheme
error_code
owner
platform
```

### 8.5 Graph Index

用于：

```text
1. 找依赖：某个字段来自哪个接口？
2. 找替代：哪些接口都能查商品信息？
3. 找调用链：先查 token，再查商品列表
4. 找缺口：endpoint 没有 auth / 没有 response schema / 没有 examples
```

---

## 9. 查询系统设计

### 9.1 查询类型

```text
1. endpoint_locate
   例：GET /products/{id} 在哪里？

2. api_capability_search
   例：哪个接口可以查询商品销量？

3. parameter_question
   例：商品列表接口需要哪些参数？

4. response_field_question
   例：哪个接口返回 sales 字段？

5. usage_question
   例：如何调用商品详情接口？

6. tool_generation
   例：把商品详情接口生成 Agent ToolSpec

7. comparison_question
   例：商品搜索和商品列表接口有什么区别？

8. dependency_question
   例：订单详情接口依赖哪些认证和参数？

9. gap_check
   例：哪些接口缺少返回 schema？

10. source_trace
    例：这个参数是从文档哪里来的？
```

### 9.2 Query Classifier

```python
class QueryPlan(BaseModel):
    query_type: str
    entities: list[dict]
    use_exact: bool = False
    use_bm25: bool = True
    use_vector: bool = True
    use_entity: bool = True
    use_graph: bool = False
    filters: dict = {}
    hydration_level: str = "endpoint_card"
    output_format: str = "answer"
```

分类规则：

```text
如果 query 包含 HTTP method + path：endpoint_locate
如果 query 包含“哪个接口/用哪个 API/查什么”：api_capability_search
如果 query 包含“参数/必填/怎么传”：parameter_question
如果 query 包含“返回/字段/response”：response_field_question
如果 query 包含“curl/调用/示例/怎么用”：usage_question
如果 query 包含“生成 Tool/函数/Agent 工具”：tool_generation
如果 query 包含“缺少/不完整/检查”：gap_check
如果 query 包含“哪里来的/来源/文档位置”：source_trace
```

### 9.3 查询链路

```text
User Query
  ↓
Query Classifier
  ↓
Entity Extractor
  ↓
Query Planner
  ↓
Multi Retrieval
  - exact path/method search
  - BM25 search
  - vector search
  - entity lookup
  - graph traversal
  ↓
Candidate EndpointOperation
  ↓
Endpoint Card Hydration
  ↓
Rerank
  ↓
Grounding Validation
  ↓
Answer Builder
```

### 9.4 Endpoint Card Hydration

检索时不要只返回 chunk，要返回完整 API 卡。

```text
operation_id
method
path
summary
description
parameters
request_body
responses
auth
examples
error_codes
source_spans
```

Hydration 伪代码：

```python
def hydrate_endpoint_card(operation_id: str) -> dict:
    op = load_operation(operation_id)
    params = load_parameters(operation_id)
    req = load_request_body(operation_id)
    res = load_responses(operation_id)
    auth = load_auth(operation_id)
    examples = load_examples(operation_id)
    errors = load_error_codes(operation_id)
    spans = load_source_spans("EndpointOperation", operation_id)
    return {
        "operation": op,
        "parameters": params,
        "request_body": req,
        "responses": res,
        "auth": auth,
        "examples": examples,
        "error_codes": errors,
        "source_spans": spans,
    }
```

### 9.5 Retrieval Fusion

```text
final_score =
  0.30 * exact_score
+ 0.25 * bm25_score
+ 0.20 * vector_score
+ 0.15 * entity_score
+ 0.10 * graph_score
```

不同查询类型动态调整：

```text
endpoint_locate:
  exact 0.50, bm25 0.25, entity 0.20, vector 0.05

api_capability_search:
  vector 0.35, bm25 0.25, entity 0.20, graph 0.20

parameter_question:
  entity 0.35, bm25 0.30, graph 0.20, vector 0.15

response_field_question:
  entity 0.40, bm25 0.25, graph 0.20, vector 0.15

usage_question:
  exact 0.20, bm25 0.20, vector 0.20, graph 0.20, examples 0.20

tool_generation:
  entity 0.25, graph 0.30, schema completeness 0.30, examples 0.15
```

### 9.6 Grounding Validator

回答前必须检查：

```text
1. 推荐的 endpoint 是否真实存在
2. 参数是否来自该 endpoint
3. 必填参数是否完整
4. 请求 body 是否符合 schema
5. 返回字段是否来自 response schema 或 example
6. auth 是否明确
7. 是否有 source span 支撑
8. 如果信息缺失，必须明确标记 unknown / missing
```

---

## 10. 输出格式设计

### 10.1 API 精准问答

```json
{
  "answer": "可以使用商品详情接口 GET /api/v1/products/{id}。需要传 path 参数 id，认证方式为 Bearer Token。",
  "operation": {
    "method": "GET",
    "path": "/api/v1/products/{id}",
    "summary": "获取商品详情"
  },
  "required_parameters": [
    {"name": "id", "location": "path", "type": "string"}
  ],
  "auth": [
    {"type": "http", "scheme": "bearer"}
  ],
  "example": "curl -H 'Authorization: Bearer $TOKEN' https://api.example.com/api/v1/products/p_001",
  "sources": [
    {
      "source_id": "doc_001",
      "heading_path": ["商品 API", "获取商品详情"],
      "line_start": 22,
      "line_end": 48
    }
  ],
  "confidence": 0.92
}
```

### 10.2 ToolSpec 输出

```json
{
  "tool_id": "tool_get_product_detail",
  "name": "get_product_detail",
  "description": "根据商品 ID 获取商品详情，包括名称、类目、价格、销量等信息。",
  "operation_id": "op_get_product_detail",
  "method": "GET",
  "url_template": "{base_url}/api/v1/products/{id}",
  "auth_required": true,
  "input_schema": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "description": "商品 ID"
      }
    },
    "required": ["id"]
  },
  "required_params": ["id"],
  "source_operation_id": "op_get_product_detail"
}
```

### 10.3 缺口检查输出

```json
{
  "operation_id": "op_search_products",
  "method": "GET",
  "path": "/api/v1/products/search",
  "completeness_score": 0.62,
  "missing_items": [
    "missing_auth_description",
    "missing_response_schema",
    "missing_error_codes"
  ],
  "recommendation": "需要补充认证方式、标准返回 schema 和错误码说明后再编译为 Agent Tool。"
}
```

---

## 11. API 文档质量评估

### 11.1 Endpoint 完整度评分

```text
endpoint_completeness =
  0.15 * has_method_path
+ 0.15 * has_summary_description
+ 0.15 * has_parameters
+ 0.15 * has_request_schema_if_needed
+ 0.15 * has_response_schema
+ 0.10 * has_auth
+ 0.10 * has_examples
+ 0.05 * has_error_codes
```

### 11.2 Tool 可编译评分

```text
tool_compilability =
  0.25 * stable_operation_id
+ 0.25 * complete_input_schema
+ 0.20 * clear_auth_runtime_binding
+ 0.15 * response_schema_available
+ 0.10 * example_available
+ 0.05 * no_schema_conflict
```

### 11.3 查询评估指标

```text
endpoint_recall@k
endpoint_precision@k
field_recall@k
answer_grounding_score
required_param_coverage
tool_schema_validity
source_trace_accuracy
```

测试样例：

```json
{
  "query": "哪个接口可以查询商品销量？",
  "expected_operation_ids": ["op_get_product_detail", "op_search_products"],
  "expected_fields": ["sales", "sales_volume"],
  "must_include_source": true
}
```

---

## 12. 工程目录结构

```text
api-doc-intelligence/
  README.md
  pyproject.toml
  .env.example

  apps/
    api/
      main.py
      routes/
        ingest.py
        parse.py
        index.py
        query.py
        toolspec.py
        eval.py

    cli/
      main.py

  core/
    ingestion/
      loader.py
      source_registry.py
      versioning.py
      file_type_detector.py

    parsers/
      openapi_parser.py
      markdown_api_parser.py
      html_api_parser.py
      postman_parser.py
      table_parser.py
      code_block_parser.py

    compiler/
      api_semantic_compiler.py
      endpoint_extractor.py
      parameter_extractor.py
      schema_inferer.py
      auth_extractor.py
      example_extractor.py
      error_code_extractor.py
      operation_deduper.py
      confidence_scorer.py
      validators.py

    models/
      source_span.py
      api_service.py
      endpoint_operation.py
      parameter.py
      schema_object.py
      auth.py
      example.py
      error_code.py
      tool_spec.py
      query_plan.py

    store/
      db.py
      migrations/
      repositories/
        service_repo.py
        endpoint_repo.py
        parameter_repo.py
        schema_repo.py
        source_span_repo.py

    index/
      structure_index.py
      fts_index.py
      vector_index.py
      entity_index.py
      graph_index.py
      index_pipeline.py

    query/
      query_classifier.py
      entity_extractor.py
      query_planner.py
      retrievers/
        exact_retriever.py
        bm25_retriever.py
        vector_retriever.py
        entity_retriever.py
        graph_retriever.py
      fusion.py
      endpoint_hydrator.py
      reranker.py
      grounding_validator.py
      answer_builder.py

    toolspec/
      tool_spec_generator.py
      openai_tool_adapter.py
      langchain_tool_adapter.py
      mcp_tool_adapter.py

    eval/
      datasets.py
      metrics.py
      test_runner.py

  data/
    raw_docs/
    parsed/
    indexes/
    eval_sets/

  tests/
    fixtures/
      product_api.md
      product_openapi.yaml
      postman_collection.json
    test_openapi_parser.py
    test_markdown_parser.py
    test_semantic_compiler.py
    test_query_endpoint_locate.py
    test_query_capability_search.py
    test_tool_spec_generator.py
```

---

## 13. MVP 实现计划

### Phase 1：OpenAPI 解析优先

目标：支持标准 OpenAPI YAML/JSON。

交付：

```text
1. openapi_parser.py
2. validate_openapi
3. resolve_refs
4. extract EndpointOperation
5. SQLite 存储
6. endpoint locate 查询
```

验收：

```text
输入 product_openapi.yaml
能够列出所有 endpoint
能够查询 GET /products/{id}
能够返回参数、response schema、source json pointer
```

### Phase 2：Markdown API 文档解析

目标：支持非标准 Markdown 文档。

交付：

```text
1. markdown_api_parser.py
2. heading tree
3. table extraction
4. code block extraction
5. endpoint regex extraction
6. table-to-param/schema binding
7. source line range
```

验收：

```text
输入 product_api.md
能够抽取 GET /api/v1/products/{id}
能够识别请求参数表
能够识别返回示例 JSON
能够返回 source line range
```

### Phase 3：多索引与精准查询

目标：支持关键词 + 语义 + entity + graph 查询。

交付：

```text
1. SQLite FTS5
2. vector index
3. entity index
4. graph edge table
5. query planner
6. endpoint hydration
```

验收：

```text
查询：哪个接口可以查询商品销量？
返回：候选 endpoint、字段、调用参数、source、confidence
```

### Phase 4：ToolSpec 生成

目标：从 EndpointOperation 生成 Agent 可用 ToolSpec。

交付：

```text
1. tool_spec_generator.py
2. input_schema builder
3. runtime auth binding design
4. OpenAI function schema adapter
5. MCP tool adapter
```

验收：

```text
查询：把商品详情接口生成 ToolSpec
返回：合法 JSON Schema + operation reference + required params
```

### Phase 5：质量评估与缺口检查

目标：对 API 文档质量和 Tool 可编译性做评估。

交付：

```text
1. completeness scorer
2. tool compilability scorer
3. query eval set
4. grounding validator
5. gap report
```

验收：

```text
输出所有低完整度 endpoint
指出缺少 auth / response schema / examples / error codes
```

---

## 14. 推荐开源技术选型

### 14.1 OpenAPI 解析 / 校验

| 项目 | 作用 | 适用场景 |
|---|---|---|
| `openapi-spec-validator` | Python OpenAPI 2.0/3.0/3.1 校验 | MVP 推荐 |
| `openapi-schema-validator` | OpenAPI schema 校验 | schema 校验 |
| `swagger-parser` | Java OpenAPI/Swagger parser | Java 栈 |
| `@apidevtools/swagger-parser` | JS/TS OpenAPI parser，支持 parse/validate/dereference | Node 栈 |
| `Redocly CLI` | lint / bundle / validate OpenAPI | 生产文档治理 |
| `OpenAPI Generator` | 从 OpenAPI 生成 SDK / server stub / docs | SDK 生成参考 |
| `Kiota` | Microsoft OpenAPI client generator | 强类型 SDK 参考 |

### 14.2 Markdown / HTML 解析

| 项目 | 作用 | 适用场景 |
|---|---|---|
| `markdown-it-py` | Python Markdown parser | MVP |
| `mistune` | Python Markdown parser | 简洁解析 |
| `tree-sitter-markdown` | 增量 Markdown 解析 | 生产增强 |
| `BeautifulSoup` | HTML 解析 | HTML API docs |
| `readability-lxml` | 网页正文抽取 | 外部文档 |
| `Playwright` | 动态网页文档抓取 | JS 渲染文档 |

### 14.3 搜索 / 索引

| 项目 | 作用 | 适用场景 |
|---|---|---|
| SQLite FTS5 | 轻量 BM25 / keyword | MVP |
| Tantivy | Rust 高性能全文检索 | 本地高性能 |
| OpenSearch / Elasticsearch | 生产级全文检索 | 多租户/大规模 |
| FAISS | 本地向量索引 | MVP |
| Chroma / LanceDB | 轻量向量库 | 原型 |
| Qdrant | hybrid search / metadata filter | 生产推荐 |
| Milvus | 大规模向量检索 | 大规模生产 |

### 14.4 Graph / 关系

| 项目 | 作用 | 适用场景 |
|---|---|---|
| NetworkX | 内存图 | MVP |
| Kuzu | 嵌入式图数据库 | 本地 Agent Box |
| Neo4j | 生产图数据库 | 跨文档 API 关系 |
| Microsoft GraphRAG | 文本抽图谱与图检索思路 | 大规模 API 文档关系理解 |

### 14.5 RAG / 编排 / 评估

| 项目 | 作用 | 适用场景 |
|---|---|---|
| LlamaIndex | node/index/retriever/query engine | 知识库原型 |
| Haystack | RAG pipeline / retriever / reranker | 后端 pipeline |
| LangChain | tool / retriever / agent 生态 | Agent 编排 |
| Ragas | RAG 评估 | 检索与回答质量评估 |
| DeepEval | LLM app 单测式评估 | CI 中评估 |
| Phoenix | tracing / eval / troubleshooting | 可观测性 |
| Langfuse | LLM tracing | 生产观测 |

---

## 15. API 文档到 Agent Tool 的关键设计

### 15.1 不要直接把 OpenAPI 全量塞给模型

原因：

```text
1. token 成本高
2. 容易混淆相似接口
3. auth/base_url/header 等 runtime 细节不该由模型生成
4. schema 太复杂时模型容易漏填 required fields
```

正确方式：

```text
OpenAPI / API 文档
  → EndpointOperation
  → Simplified ToolSpec
  → Runtime-controlled API Executor
```

### 15.2 ToolSpec 应该短而准

一个 ToolSpec 只包含：

```text
1. 工具用途
2. 必填输入
3. 可选输入
4. 输入 JSON Schema
5. 输出摘要 schema
6. source operation id
```

不包含：

```text
1. 真实 token
2. 完整 base_url 选择逻辑
3. 敏感 header
4. 过长 response example
5. 过度复杂 oneOf/anyOf/allOf schema
```

### 15.3 Runtime 负责注入

```text
base_url
auth token
tenant_id
common headers
retry
rate limit
logging
error handling
```

---

## 16. 查询示例

### 16.1 查询接口能力

用户：

```text
哪个接口可以查询商品销量？
```

系统流程：

```text
query_type = api_capability_search
entities = [商品, 销量]
retrieval = vector(endpoint_intent) + entity(schema_field) + bm25
hydrate candidate endpoint
validate response fields contain sales/sales_volume
return answer
```

输出：

```text
推荐接口：GET /api/v1/products/{id}
原因：返回字段中包含 sales，接口描述为获取商品详情。
必填参数：id
认证：Bearer Token
来源：商品 API / 获取商品详情 / line 22-48
```

### 16.2 查询参数

用户：

```text
商品搜索接口需要传哪些参数？
```

输出：

```text
接口：GET /api/v1/products/search
必填参数：keyword
可选参数：category_id, page, page_size, sort
来源：...
```

### 16.3 生成 ToolSpec

用户：

```text
把商品详情接口生成 Agent 工具
```

输出：

```json
{
  "name": "get_product_detail",
  "description": "根据商品 ID 查询商品详情。",
  "input_schema": {
    "type": "object",
    "properties": {
      "id": {"type": "string", "description": "商品 ID"}
    },
    "required": ["id"]
  }
}
```

---

## 17. 测试集设计

### 17.1 Fixture 文档

```text
tests/fixtures/product_api.md
tests/fixtures/product_openapi.yaml
tests/fixtures/order_api.md
tests/fixtures/postman_collection.json
```

### 17.2 Golden Query Set

```json
[
  {
    "query": "哪个接口可以查询商品销量？",
    "query_type": "api_capability_search",
    "expected_operation_ids": ["op_get_product_detail"],
    "expected_fields": ["sales"],
    "must_have_source": true
  },
  {
    "query": "GET /api/v1/products/{id} 需要哪些参数？",
    "query_type": "parameter_question",
    "expected_operation_ids": ["op_get_product_detail"],
    "expected_parameters": ["id"]
  },
  {
    "query": "把商品详情接口生成 ToolSpec",
    "query_type": "tool_generation",
    "expected_tool_name": "get_product_detail",
    "expected_required_params": ["id"]
  }
]
```

### 17.3 Parser 单测

```text
test_openapi_parser_extracts_paths
test_openapi_parser_resolves_refs
test_markdown_parser_extracts_method_path
test_markdown_parser_binds_parameter_table
test_markdown_parser_extracts_response_example
```

### 17.4 Query 单测

```text
test_endpoint_locate_by_method_path
test_capability_search_by_business_intent
test_response_field_query
test_tool_spec_generation
test_gap_check_missing_response_schema
```

---

## 18. AI-coding 执行任务拆分

### Task 1：建立 Pydantic 模型

输入：本文第 4 章。  
输出：`core/models/*.py`。

完成标准：

```text
pytest 能创建 ApiService / EndpointOperation / ToolSpec
所有模型支持 model_dump_json
```

### Task 2：实现 OpenAPI Parser

输入：OpenAPI YAML/JSON。  
输出：EndpointOperation 列表。

完成标准：

```text
能解析 paths / parameters / requestBody / responses / security
能保留 json_pointer
```

### Task 3：实现 Markdown API Parser

输入：Markdown API 文档。  
输出：DocBlock + EndpointOperation candidates。

完成标准：

```text
能识别 METHOD + PATH
能绑定参数表
能抽取 JSON 示例
能返回 line_start / line_end
```

### Task 4：实现 SQLite Store

输入：ApiService / EndpointOperation。  
输出：SQLite 持久化。

完成标准：

```text
能 upsert service / endpoint / parameters / schemas / examples / source_spans
```

### Task 5：实现 FTS Index

输入：endpoint card。  
输出：可关键词检索。

完成标准：

```text
查询 path / 参数名 / 字段名 / summary 能命中 endpoint
```

### Task 6：实现 Query Planner

输入：自然语言 query。  
输出：QueryPlan。

完成标准：

```text
能区分 endpoint_locate / api_capability_search / parameter_question / tool_generation
```

### Task 7：实现 Endpoint Hydrator

输入：operation_id。  
输出：完整 endpoint card。

完成标准：

```text
返回 parameters / request_body / responses / auth / examples / source_spans
```

### Task 8：实现 ToolSpec Generator

输入：EndpointOperation card。  
输出：ToolSpec。

完成标准：

```text
input_schema 合法
required params 正确
auth 不暴露 secret
```

### Task 9：实现 Eval Runner

输入：Golden Query Set。  
输出：metrics。

完成标准：

```text
计算 endpoint_recall@k / field_recall@k / grounding_score / tool_schema_validity
```

---

## 19. 最小可运行命令设计

### 19.1 CLI

```bash
api-docx ingest ./docs/product_api.md --source-type markdown
api-docx ingest ./docs/product_openapi.yaml --source-type openapi
api-docx index --service product
api-docx query "哪个接口可以查询商品销量？"
api-docx tool generate --operation-id op_get_product_detail
api-docx eval ./data/eval_sets/product_api_queries.json
```

### 19.2 HTTP API

```http
POST /ingest
POST /parse
POST /index
POST /query
POST /toolspec/generate
POST /eval/run
```

Query request：

```json
{
  "query": "哪个接口可以查询商品销量？",
  "service_filter": ["product"],
  "top_k": 5,
  "return_sources": true
}
```

Query response：

```json
{
  "answer": "可以使用 GET /api/v1/products/{id}。",
  "candidates": [
    {
      "operation_id": "op_get_product_detail",
      "method": "GET",
      "path": "/api/v1/products/{id}",
      "score": 0.91,
      "reason": "返回字段包含 sales，接口语义为商品详情查询。"
    }
  ],
  "sources": [
    {
      "source_id": "product_api_md",
      "line_start": 22,
      "line_end": 48
    }
  ]
}
```

---

## 20. 推荐 MVP 技术栈

```text
Language: Python 3.11+
API: FastAPI
Schema: Pydantic v2
Parser:
  - PyYAML
  - openapi-spec-validator
  - markdown-it-py
  - BeautifulSoup4
Storage:
  - SQLite
  - SQLite FTS5
Vector:
  - FAISS 或 Chroma
Graph:
  - NetworkX + SQLite edge table
LLM:
  - 可选，用于非标准文档修复
Eval:
  - pytest
  - DeepEval / Ragas 可后置
```

生产增强：

```text
PostgreSQL
OpenSearch / Elasticsearch
Qdrant / Milvus
Neo4j / Kuzu
Redocly CLI
OpenTelemetry + Phoenix / Langfuse
```

---

## 21. 关键反模式

### 21.1 反模式：直接对 API 文档切 chunk 做向量检索

问题：

```text
1. 参数表和 endpoint 可能被切开
2. response schema 和调用示例可能被切开
3. Agent 只能看到片段，无法形成完整调用
4. 无法稳定生成 ToolSpec
```

### 21.2 反模式：让 LLM 直接读文档生成接口

问题：

```text
1. 容易发明参数
2. 容易遗漏 required fields
3. 无法精确 source trace
4. 更新文档后难以 diff
```

### 21.3 反模式：把 OpenAPI 全量作为上下文给 Agent

问题：

```text
1. token 成本高
2. 相似接口混淆
3. oneOf/anyOf/allOf schema 会干扰模型
4. auth/runtime 细节容易泄露或误填
```

正确做法：

```text
Parse → API Asset Card → Precision Query → Hydrated Endpoint Card → Simplified ToolSpec
```

---

## 22. 参考开源与资料

### 标准与规范

1. OpenAPI Specification: https://github.com/OAI/OpenAPI-Specification
2. OpenAPI 3.1 Specification: https://swagger.io/specification/
3. AsyncAPI: https://www.asyncapi.com/

### OpenAPI 工具

1. openapi-spec-validator: https://github.com/python-openapi/openapi-spec-validator
2. openapi-schema-validator: https://github.com/python-openapi/openapi-schema-validator
3. swagger-parser Java: https://github.com/swagger-api/swagger-parser
4. Swagger Parser JS: https://github.com/APIDevTools/swagger-parser
5. Redocly CLI: https://redocly.com/docs/cli
6. OpenAPI Generator: https://github.com/OpenAPITools/openapi-generator
7. Kiota: https://github.com/microsoft/kiota

### 文档与 UI

1. Redoc: https://github.com/Redocly/redoc
2. Swagger UI: https://github.com/swagger-api/swagger-ui
3. RapiDoc: https://github.com/rapi-doc/RapiDoc
4. Scalar: https://github.com/scalar/scalar

### API 文档转 OpenAPI 研究

1. SpeCrawler: Generating OpenAPI Specifications from API Documentation Using Large Language Models
2. OASBuilder: Generating OpenAPI Specifications from Online API Documentation with Large Language Models
3. API-Miner: an API-to-API Specification Recommendation Engine
4. LAPIS: Lightweight API Specification for Intelligent Systems

---

## 23. 最终结论

API 文档解析、索引和查询的核心，不是“做一个 API 文档 RAG”，而是构建一个：

```text
API Asset Compiler
```

它必须把文档转成稳定对象：

```text
Service → Endpoint → Parameter → Schema → Example → ToolSpec
```

查询时必须先做计划：

```text
Query → Intent → Multi-index Retrieval → Endpoint Hydration → Grounding Validation → Answer
```

面向 Agent Runtime 时，必须输出精简、可控、可执行的：

```text
ToolSpec
```

而不是把原始 OpenAPI 或 API 文档直接塞给模型。
