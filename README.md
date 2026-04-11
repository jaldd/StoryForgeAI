<div align="center">

# StoryForgeAI

**AI-Powered Novel Writing Assistant**

*让 AI 成为你的创作伙伴，精心打造每一个故事*

[![Java](https://img.shields.io/badge/Java-21-orange.svg)](https://openjdk.org/projects/jdk/21/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.3.4-brightgreen.svg)](https://spring.io/projects/spring-boot)
[![LangChain4j](https://img.shields.io/badge/LangChain4j-1.0.0--beta3-blue.svg)](https://docs.langchain4j.dev/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

[English](#) | [简体中文](#)

</div>

---

## 🎯 项目愿景

StoryForgeAI 是一个基于 **AI Agent** 技术的小说创作辅助系统。不同于传统的文本生成工具，我们专注于：

- **🧠 智能理解**：深度理解创作意图，提供有深度的建议
- **🔗 一致性保障**：通过三层记忆系统，确保长篇小说的角色、情节、世界观一致
- **⚡ 实时交互**：流式输出，即时响应，沉浸式创作体验
- **🛠️ 可扩展**：支持 MCP 协议，可接入外部工具生态

---

## ✨ 核心特性

### 🎭 角色驱动的情节生成
基于角色弧光分析，自动生成符合角色性格发展的情节走向

### 🔍 情节漏洞检测
智能检测角色瞬移、动机缺失、时间线冲突等逻辑漏洞

### 📚 三层记忆系统
- **短期记忆**：最近 10 轮对话上下文
- **长期记忆**：章节向量检索，精准召回相关片段
- **工作记忆**：角色位置、伏笔列表、冲突状态

### 🎨 风格迁移
保持内容不变，改写为指定风格（如：金庸风、网文风、严肃文学）

### 🔄 多模型 Fallback
主模型失败时自动切换备用模型，保障服务稳定性

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (React)                     │
│                  http://localhost:5173                   │
└─────────────────────────┬───────────────────────────────┘
                          │ SSE / REST
┌─────────────────────────▼───────────────────────────────┐
│                    Bootstrap Layer                       │
│              (Composition Root / Assembly)               │
└──────────┬──────────────────────────────────────────────┘
           │
    ┌──────┴──────┬──────────────────┬──────────────────┐
    ▼             ▼                  ▼                  ▼
┌───────┐   ┌──────────┐      ┌──────────────┐   ┌─────────┐
│  API  │   │   CLI    │      │Infrastructure│   │   ...   │
│(WebFlux)  │(Console) │      │ (Adapters)   │   │         │
└───┬───┘   └────┬─────┘      └──────┬───────┘   └────┬────┘
    │            │                   │                │
    └────────────┴───────────────────┴────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │    Application Layer   │
              │   (Use Case / Ports)   │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │     Domain Layer       │
              │  (Entities / Services) │
              └───────────────────────┘
```

**架构原则**：六边形架构（端口适配器）、依赖倒置、领域驱动设计

---

## 🛠️ 技术栈

| 类别 | 技术选型 | 版本 |
|------|---------|------|
| **语言** | Java | 21 (Virtual Threads, Record, Pattern Matching) |
| **框架** | Spring Boot | 3.3.4 |
| **Agent** | LangChain4j | 1.0.0-beta3 |
| **LLM** | GLM-4-Flash | OpenAI 兼容模式 |
| **数据库** | H2 (MVP) / PostgreSQL | 15+ |
| **缓存** | 内存 (MVP) / Redis | 7.0+ |
| **向量库** | 内存 (MVP) / Milvus | 2.3+ |
| **前端** | React + TypeScript + Vite | 19 / 5 / 6 |
| **协议** | REST + SSE | - |
| **工具协议** | MCP (JSON-RPC) | - |

---

## 🚀 快速开始

### 环境要求

- JDK 21+
- Maven 3.9+
- Node.js 18+
- GLM API Key（[获取地址](https://open.bigmodel.cn)）

### 启动步骤

```bash
# 1. 克隆项目
git clone https://github.com/your-org/StoryForgeAI.git
cd StoryForgeAI

# 2. 设置 API Key
export GLM_API_KEY=your_api_key_here

# 3. 编译项目
mvn compile

# 4. 启动后端（终端 1）
cd bootstrap && mvn spring-boot:run

# 5. 启动前端（终端 2）
cd frontend && npm install && npm run dev
```

### 访问地址

| 服务 | 地址 |
|------|------|
| **前端界面** | http://localhost:5173 |
| **后端 API** | http://localhost:8080/api |
| **H2 控制台** | http://localhost:8080/h2-console |
| **健康检查** | http://localhost:8080/actuator/health |

---

## 📁 项目结构

```
StoryForgeAI/
├── domain/              # 领域层（零外部依赖）
│   ├── model/           # 实体、值对象
│   ├── repository/      # 仓储接口
│   ├── service/         # 领域服务接口
│   └── event/           # 领域事件
│
├── application/         # 应用层（用例编排）
│   ├── service/         # 应用服务
│   ├── port/inbound/    # 入站端口（用例接口）
│   ├── port/outbound/   # 出站端口（技术接口）
│   └── dto/             # 数据传输对象
│
├── infrastructure/      # 基础设施层（技术实现）
│   ├── persistence/     # 数据持久化
│   ├── llm/             # LLM 适配器
│   ├── memory/          # 记忆管理实现
│   ├── tool/            # 工具实现
│   └── config/          # 配置类
│
├── api/                 # REST API 层
│   ├── controller/      # 控制器
│   └── config/          # Web 配置
│
├── cli/                 # 命令行界面
│
├── bootstrap/           # 启动装配层
│   └── resources/       # 配置文件
│
├── frontend/            # 前端（React + Vite）
│   ├── src/             # 源码
│   └── package.json     # 依赖配置
│
└── docs/                # 文档
    ├── spec/            # 规格文档
    └── DEVELOPMENT.md   # 开发指南
```

---

## 📖 文档

| 文档 | 说明 |
|------|------|
| [技术规格](docs/spec/technical-spec.md) | 详细技术方案设计 |
| [DDD 建模](docs/spec/ddd-modeling.md) | 领域驱动设计文档 |
| [任务分解](docs/spec/task-breakdown.md) | 开发任务列表 |
| [开发指南](docs/DEVELOPMENT.md) | 编译、测试、启动指南 |

---

## 🗓️ 开发路线

### ✅ 迭代 1：MVP（当前）
- [x] 项目骨架搭建
- [x] DDD 分层架构
- [x] 前端调试页面
- [ ] 意图识别（规则匹配）
- [ ] CharacterArcPlanner 工具
- [ ] 流式输出

### 🔜 迭代 2：记忆系统
- [ ] 三层记忆系统
- [ ] PlotGapDetector 工具
- [ ] StyleTransfer 工具
- [ ] Docker Compose 部署

### 📅 迭代 3：MCP + 多模型
- [ ] MCP Server/Client
- [ ] 多模型 Fallback
- [ ] 预算控制

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

---

## 📄 许可证

本项目采用 [Apache 2.0](LICENSE) 许可证。

---

## 🙏 致谢

- [LangChain4j](https://github.com/langchain4j/langchain4j) - Java AI Agent 框架
- [智谱 AI](https://open.bigmodel.cn) - GLM-4 大语言模型
- [Spring Boot](https://spring.io/projects/spring-boot) - 应用框架

---

<div align="center">

**Made with ❤️ by StoryForgeAI Team**

[⬆ 返回顶部](#storyforgeai)

</div>
