# 文档交互设计方案

## 1. 核心交互流程

```
┌─────────────────────────────────────────────────────────────┐
│                        用户操作流程                            │
└─────────────────────────────────────────────────────────────┘

1. 创建小说项目
   ↓
2. 上传/编辑文档（章节、角色设定、世界观等）
   ↓
3. 选择操作（续写、分析、润色等）
   ↓
4. 查看AI生成结果
   ↓
5. 接受/修改/重新生成
   ↓
6. 保存结果到项目
```

## 2. 支持的文档类型

| 文档类型 | 说明 | 用途 |
|---------|------|------|
| **章节内容** | 小说正文章节 | 续写、分析、润色 |
| **角色设定** | 角色档案、性格、背景 | 角色弧光分析、角色驱动生成 |
| **世界观设定** | 背景、规则、设定 | 一致性检查、设定补全 |
| **情节大纲** | 章节规划、情节走向 | 情节漏洞检测、情节推进建议 |

## 3. API 接口设计

### 3.1 项目管理接口

#### 3.1.1 创建项目
```http
POST /api/projects
Content-Type: application/json

{
  "title": "我的科幻小说",
  "author": "张三",
  "description": "一个关于AI的故事"
}

Response:
{
  "projectId": "proj_abc123",
  "title": "我的科幻小说",
  "author": "张三",
  "createdAt": "2026-04-11T10:00:00Z"
}
```

#### 3.1.2 获取项目列表
```http
GET /api/projects

Response:
{
  "projects": [
    {
      "projectId": "proj_abc123",
      "title": "我的科幻小说",
      "author": "张三",
      "updatedAt": "2026-04-11T10:00:00Z",
      "chapterCount": 5
    }
  ]
}
```

### 3.2 文档管理接口

#### 3.2.1 上传章节
```http
POST /api/projects/{projectId}/chapters
Content-Type: application/json

{
  "chapterNumber": 1,
  "title": "第一章：开端",
  "content": "张伟站在街头...",
  "type": "chapter"
}

Response:
{
  "chapterId": "chap_001",
  "chapterNumber": 1,
  "title": "第一章：开端",
  "createdAt": "2026-04-11T10:00:00Z",
  "wordCount": 1500
}
```

#### 3.2.2 上传角色设定
```http
POST /api/projects/{projectId}/documents
Content-Type: application/json

{
  "type": "character",
  "name": "张伟",
  "content": {
    "name": "张伟",
    "age": 28,
    "occupation": "程序员",
    "personality": "内向、谨慎、有正义感",
    "background": "来自小城市，北漂5年"
  }
}

Response:
{
  "documentId": "doc_char_001",
  "type": "character",
  "name": "张伟",
  "createdAt": "2026-04-11T10:00:00Z"
}
```

#### 3.2.3 获取项目文档列表
```http
GET /api/projects/{projectId}/documents

Response:
{
  "documents": [
    {
      "documentId": "chap_001",
      "type": "chapter",
      "title": "第一章：开端",
      "updatedAt": "2026-04-11T10:00:00Z"
    },
    {
      "documentId": "doc_char_001",
      "type": "character",
      "name": "张伟",
      "updatedAt": "2026-04-11T10:00:00Z"
    }
  ]
}
```

#### 3.2.4 获取文档详情
```http
GET /api/projects/{projectId}/documents/{documentId}

Response:
{
  "documentId": "chap_001",
  "type": "chapter",
  "chapterNumber": 1,
  "title": "第一章：开端",
  "content": "张伟站在街头...",
  "createdAt": "2026-04-11T10:00:00Z"
}
```

### 3.3 创作交互接口

#### 3.3.1 续写章节
```http
POST /api/projects/{projectId}/continue
Content-Type: application/json

{
  "referenceChapterId": "chap_001",
  "instruction": "接着第一章的结尾续写",
  "targetLength": "2000字",
  "style": "保持原有风格"
}

Response (SSE流式):
data: {"type":"info","content":"正在分析前文..."}
data: {"type":"token","content":"张"}
data: {"type":"token","content":"伟"}
...
data: {"type":"done","content":{"chapterId":"chap_002","wordCount":1980}}
```

#### 3.3.2 分析角色
```http
POST /api/projects/{projectId}/analyze/character
Content-Type: application/json

{
  "characterName": "张伟",
  "analysisDepth": "detailed"
}

Response:
{
  "characterName": "张伟",
  "arcScore": 0.65,
  "stages": [
    {
      "chapter": "第1章",
      "goal": "生存",
      "conflict": "失业危机",
      "belief": "金钱至上",
      "evidence": "张伟盯着银行卡余额..."
    }
  ],
  "suggestions": [
    {
      "type": "TURNING_POINT",
      "description": "建议在第3章增加转折事件",
      "reason": "当前信念转变缺乏铺垫"
    }
  ]
}
```

#### 3.3.3 检测情节漏洞
```http
POST /api/projects/{projectId}/analyze/plot-gaps
Content-Type: application/json

{
  "startChapter": 1,
  "endChapter": 5
}

Response:
{
  "gaps": [
    {
      "type": "CHARACTER_TELEPORT",
      "severity": "high",
      "description": "张伟在第3章结尾在北京，第4章开头突然在上海",
      "location": {
        "chapters": ["第3章", "第4章"],
        "evidence": [
          "第3章: 张伟站在北京街头...",
          "第4章: 张伟推开上海的家门..."
        ]
      },
      "suggestion": "增加过渡场景或说明交通方式"
    }
  ],
  "summary": {
    "totalGaps": 1,
    "highSeverity": 1
  }
}
```

## 4. 数据模型设计

### 4.1 Chapter（章节）
```java
public class Chapter {
    private ChapterId chapterId;
    private NovelProjectId projectId;
    private int chapterNumber;
    private String title;
    private String content;
    private int wordCount;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
```

### 4.2 Document（文档）
```java
public class Document {
    private DocumentId documentId;
    private NovelProjectId projectId;
    private DocumentType type; // CHAPTER, CHARACTER, WORLD, OUTLINE
    private String name;
    private String content; // JSON or plain text
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
```

### 4.3 GenerationResult（生成结果）
```java
public class GenerationResult {
    private GenerationId generationId;
    private NovelProjectId projectId;
    private GenerationType type; // CONTINUE, ANALYZE, POLISH
    private String prompt;
    private String result;
    private int tokenCount;
    private LocalDateTime createdAt;
    private boolean accepted;
}
```

## 5. 前端交互设计

### 5.1 项目管理页面
- 项目列表展示
- 创建新项目按钮
- 项目卡片（标题、作者、更新时间、章节数）

### 5.2 项目详情页面
- 左侧导航：章节列表、文档列表
- 主编辑区：文档编辑器
- 右侧工具栏：续写、分析、润色按钮

### 5.3 章节编辑页面
- Markdown编辑器
- 字数统计
- 保存按钮
- AI操作工具栏（续写、分析、润色）

### 5.4 对话/生成弹窗
- 流式输出展示
- 接受/拒绝/重新生成按钮
- 保存到项目选项

## 6. 实现优先级

### P0（必须）
1. 项目创建和列表接口
2. 章节上传和管理接口
3. 基于已有章节的续写功能
4. 文档存储到数据库

### P1（重要）
1. 角色设定文档管理
2. 角色弧光分析工具
3. 生成结果保存功能

### P2（优化）
1. 世界观设定管理
2. 情节漏洞检测
3. 文档版本历史
