# StoryForgeAI 开发指南

## 1. 项目结构

```
StoryForgeAI/
├── domain/              # 领域层（零外部依赖）
├── application/         # 应用层（用例编排）
├── infrastructure/      # 基础设施层（技术实现）
├── api/                 # REST API（WebFlux）
├── cli/                 # 命令行界面
├── bootstrap/           # 启动装配层
├── frontend/            # 前端（React + Vite）
└── docs/                # 文档
```

## 2. 环境要求

| 工具 | 版本 |
|------|------|
| JDK | 21+ |
| Maven | 3.9+ |
| Node.js | 18+ |
| npm | 9+ |

## 3. 编译

```bash
# 编译所有模块
mvn compile

# 跳过测试编译
mvn compile -DskipTests

# 清理并编译
mvn clean compile
```

## 4. 测试

```bash
# 运行所有测试
mvn test

# 运行单个模块测试
mvn test -pl domain

# 跳过测试
mvn install -DskipTests
```

## 5. 打包

```bash
# 打包（生成 bootstrap/target/bootstrap-0.1.0-SNAPSHOT.jar）
mvn package -DskipTests

# 安装到本地仓库
mvn install -DskipTests
```

## 6. 配置

### 6.1 后端配置

配置文件：`bootstrap/src/main/resources/application.yml`

```yaml
spring:
  application:
    name: storyforge
  datasource:
    url: jdbc:h2:mem:storyforge;DB_CLOSE_DELAY=-1
    driver-class-name: org.h2.Driver
    username: sa
    password:
  jpa:
    hibernate:
      ddl-auto: create-drop
    show-sql: false
  h2:
    console:
      enabled: true

server:
  port: 8080

model:
  providers:
    - name: glm-4-flash
      endpoint: https://open.bigmodel.cn/api/paas/v4
      model: glm-4-flash
      apikey: ${GLM_API_KEY}
      maxTokens: 4096
      temperature: 0.7

management:
  endpoints:
    web:
      exposure:
        include: health,info
```

### 6.2 环境变量

```bash
# 设置 GLM API Key
export GLM_API_KEY=your_api_key_here
```

### 6.3 MVP 阶段简化配置

MVP 阶段不依赖外部中间件，使用内存存储：

| 组件 | MVP 方案 | 生产方案 |
|------|---------|---------|
| 数据库 | H2 内存数据库 | PostgreSQL |
| 缓存 | 内存 Map | Redis |
| 向量存储 | 内存列表 | Milvus/pgvector |

## 7. 启动

### 7.1 后端启动

```bash
# 方式 1：Maven 启动
cd bootstrap
mvn spring-boot:run

# 方式 2：JAR 启动
java -jar bootstrap/target/bootstrap-0.1.0-SNAPSHOT.jar

# 方式 3：指定配置
java -jar bootstrap/target/bootstrap-0.1.0-SNAPSHOT.jar --spring.profiles.active=dev
```

后端启动后访问：
- API: http://localhost:8080/api
- H2 控制台: http://localhost:8080/h2-console（JDBC URL: jdbc:h2:mem:storyforge）
- 健康检查: http://localhost:8080/actuator/health

### 7.2 前端启动

```bash
# 安装依赖
cd frontend
npm install

# 开发模式启动
npm run dev
```

前端启动后访问：http://localhost:5173

### 7.3 同时启动（推荐）

```bash
# 终端 1：后端
cd bootstrap && mvn spring-boot:run

# 终端 2：前端
cd frontend && npm run dev
```

## 8. API 测试

### 8.1 健康检查

```bash
curl http://localhost:8080/actuator/health
```

### 8.2 聊天接口

```bash
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "projectId": "test"}'
```

### 8.3 流式接口

```bash
curl -X POST http://localhost:8080/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "projectId": "test"}'
```

## 9. 前端开发

### 9.1 目录结构

```
frontend/
├── src/
│   ├── main.tsx       # 入口
│   ├── App.tsx        # 主组件（聊天界面）
│   ├── App.css        # 样式
│   └── index.css      # 全局样式
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts     # Vite 配置（含代理）
```

### 9.2 代理配置

`vite.config.ts` 已配置代理：

```typescript
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8080',
      changeOrigin: true,
    },
  },
}
```

前端请求 `/api/*` 会自动代理到后端 `http://localhost:8080/api/*`。

### 9.3 构建生产版本

```bash
cd frontend
npm run build
```

构建产物在 `frontend/dist/`，可放到 `api/src/main/resources/static/` 随后端一起部署。

## 10. 常见问题

### Q1: 编译报错找不到 LangChain4j 类

确保父 POM 中 LangChain4j BOM 版本正确，然后执行：

```bash
mvn clean install -U
```

### Q2: 前端请求后端 CORS 错误

开发模式下 Vite 已配置代理，不会出现 CORS。如果仍有问题，检查后端是否启动。

### Q3: H2 数据库连接失败

确保 `application.yml` 中 H2 配置正确，且依赖已添加：

```xml
<dependency>
    <groupId>com.h2database</groupId>
    <artifactId>h2</artifactId>
    <scope>runtime</scope>
</dependency>
```

### Q4: GLM API 调用失败

检查：
1. `GLM_API_KEY` 环境变量是否设置
2. 网络是否能访问 `https://open.bigmodel.cn`
3. API Key 是否有效

## 11. IDE 配置

### IntelliJ IDEA

1. 导入项目：File → Open → 选择项目根目录
2. 等待 Maven 自动导入依赖
3. 设置 JDK 21：File → Project Structure → Project SDK

### VS Code

1. 安装扩展：Extension Pack for Java
2. 安装扩展：Spring Boot Extension Pack
3. 打开项目根目录

## 12. 下一步

- [ ] 实现 `CharacterArcPlanner` 工具
- [ ] 实现意图识别（规则匹配）
- [ ] 实现流式输出优化
- [ ] 添加更多测试用例
