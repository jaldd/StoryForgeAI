# Markdown 转换策略说明

## 概述

StoryForgeAI 支持三种不同的 Markdown 转换策略，用于将非 Markdown 文件转换为标准的 Markdown 格式。用户可以通过配置文件选择使用哪种策略。

## 三种转换策略

### 1. MarkItDown-MCP (默认)

**策略名称**: `markitdown-mcp`

**描述**: 使用微软开源的 MarkItDown 工具进行转换，这是一个专门为 AI 应用设计的文件转换工具，支持多种文件格式。

**特点**:
- 支持多种文件格式的高质量转换
- 保留文档结构和格式
- 专为 AI 应用优化

**依赖**: 需要安装 MarkItDown Python 包

```bash
pip install markitdown
```

### 2. LLM 转换

**策略名称**: `llm`

**描述**: 使用大语言模型（如 GLM-4.5-Flash）进行智能转换，能够理解文档内容并生成高质量的 Markdown。

**特点**:
- 智能理解文档内容
- 生成格式规范的 Markdown
- 支持复杂文档结构

**依赖**: 需要配置有效的 LLM API

### 3. 简单转换

**策略名称**: `simple`

**描述**: 使用简单的字符串处理方法进行转换，适用于简单的文件格式。

**特点**:
- 轻量级，无需外部依赖
- 处理速度快
- 适合简单的文本文件

**依赖**: 无

## 配置方法

在 `bootstrap/src/main/resources/application.yml` 文件中配置默认转换策略：

```yaml
storyforge:
  project:
    # 其他配置...
    markdown-conversion-strategy: markitdown-mcp  # 可选值: markitdown-mcp, llm, simple
```

## 策略选择建议

1. **默认推荐**: `markitdown-mcp` - 提供最佳的转换质量和格式支持
2. **网络受限环境**: `simple` - 无需外部依赖，本地处理
3. **需要智能理解**: `llm` - 处理复杂文档结构和内容

## 故障处理

- 如果选择 `markitdown-mcp` 但未安装 MarkItDown，系统会自动回退到 `simple` 策略
- 如果选择 `llm` 但 LLM 调用失败，系统会自动回退到 `simple` 策略
- 如果配置了未知的策略名称，系统会默认使用 `simple` 策略

## 示例

### 转换 HTML 文件

**输入**:
```html
<h1>标题</h1>
<p>这是一个段落。</p>
<ul>
  <li>项目 1</li>
  <li>项目 2</li>
</ul>
```

**输出**:
```markdown
# 标题

这是一个段落。

- 项目 1
- 项目 2
```

### 转换 JSON 文件

**输入**:
```json
{
  "name": "故事",
  "chapters": [
    "第一章",
    "第二章"
  ]
}
```

**输出**:
```markdown
```json
{
  "name": "故事",
  "chapters": [
    "第一章",
    "第二章"
  ]
}
```
```