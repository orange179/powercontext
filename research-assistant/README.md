# 文献整理助手 - Research Assistant

基于 **seekdb** + **PowerContext** 的智能文献检索与管理工具，帮助研究人员高效整理和检索学术文献。

## 📖 项目简介

整理文献要翻几十篇论文，复习时找不到上学期的笔记，周报总要从聊天记录里一条条拼。学习、科研和工作中，总有一些重复又耗时的环节值得被改造。

**文献整理助手**通过集成 seekdb 的语义检索能力和 PowerContext 的用户记忆功能，为用户提供：

- 📥 **批量导入**：支持 CSV 格式文献数据导入
- 🔍 **语义检索**：基于关键词的智能匹配与检索
- 🏷️ **标签管理**：自动提取和管理文献标签
- 👤 **个性化推荐**：基于用户偏好的文献推荐
- 📊 **进度追踪**：记录用户阅读进度和学习历史

## 🛠️ 技术栈

| 组件 | 技术 | 作用 |
|------|------|------|
| 后端框架 | FastAPI | 提供 RESTful API 服务 |
| 前端 | HTML/CSS/JavaScript | 用户交互界面 |
| 语义检索 | seekdb | 向量检索与全文检索 |
| 用户记忆 | PowerContext | 存储用户偏好和阅读进度 |
| 部署 | Qoder Sites | 在线发布与访问 |

## 🚀 快速开始

### 1. 环境要求

- Python 3.11+
- pip 或 uv

### 2. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 3. 启动服务

```bash
# 启动后端 API
python main.py

# 服务将在 http://localhost:8000 启动
# 访问前端页面: http://localhost:8000/app
```

### 4. 使用示例

#### 导入文献数据

1. 打开应用，切换到"导入文献"标签
2. 复制以下示例 CSV 数据：

```csv
title,authors,abstract,keywords,notes,tags
"Attention Is All You Need","Vaswani et al.","The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.","Transformer,Attention,NLP","这篇论文提出了 Transformer 架构","深度学习,NLP,Transformer"
```

3. 粘贴到输入框，点击"导入"

#### 语义检索

1. 切换到"检索文献"标签
2. 输入关键词，如："Transformer"、"深度学习"、"NLP"
3. 系统返回匹配的文献及匹配度分数

#### 设置个人偏好

1. 切换到"个人偏好"标签
2. 输入用户 ID（如：user1）
3. 选择感兴趣的研究标签
4. 点击"保存偏好"（PowerContext 会记住你的偏好）

## 📋 验证样例

### 样例 1：文献导入与检索

**初始数据**：使用 `data/sample_papers.csv` 中的示例数据

**操作步骤**：
1. 启动应用
2. 导入示例 CSV 数据
3. 检索关键词："Transformer"
4. 查看返回结果

**预期结果**：
- 成功导入 7 篇文献
- 检索返回 "Attention Is All You Need"、"BERT"、"GPT-3" 等相关文献
- 匹配度分数显示在结果中

**技术验证**：
- seekdb：语义检索功能正常工作
- PowerContext：用户偏好被保存和读取

### 样例 2：个性化推荐

**操作步骤**：
1. 设置用户偏好：选择"深度学习"、"NLP"标签
2. 保存偏好
3. 查看推荐文献

**预期结果**：
- 系统推荐包含"深度学习"、"NLP"标签的文献
- 推荐理由显示匹配的标签数量

## 🔧 技术集成说明

### seekdb 集成

seekdb 在本项目中提供**语义检索**能力：

```python
# 实际集成示例（当前为模拟实现）
from seekdb_client import SeekDBClient

client = SeekDBClient(
    host="localhost",
    port=3306,
    database="research_db"
)

# 向量检索
results = client.vector_search(
    collection="papers",
    query_vector=embed(query_text),
    top_k=10
)

# 混合检索（向量 + 全文 + 结构化）
results = client.hybrid_search(
    collection="papers",
    vector_query=embed(query_text),
    text_query=query_text,
    filter={"tags": {"$in": ["NLP", "深度学习"]}}
)
```

**作用**：
- 将文献摘要转换为向量表示
- 支持语义相似度检索
- 结合全文检索提高准确率

### PowerContext 集成

PowerContext 在本项目中提供**用户记忆**能力：

```python
# 实际集成示例（当前为模拟实现）
from powercontext import PowerContextClient

client = PowerContextClient(
    api_url="http://localhost:8080",
    api_key="your-api-key"
)

# 保存用户偏好
client.set_memory(
    user_id="user1",
    key="preferences",
    value={
        "preferred_tags": ["深度学习", "NLP"],
        "reading_progress": {"paper_id": "123", "progress": 0.8}
    }
)

# 读取用户偏好
prefs = client.get_memory(user_id="user1", key="preferences")
```

**作用**：
- 存储用户的研究偏好和兴趣标签
- 记录阅读进度和学习历史
- 支持跨会话的个性化推荐

## 📁 项目结构

```
research-assistant/
├── backend/
│   ├── main.py              # FastAPI 后端主程序
│   └── requirements.txt     # Python 依赖
├── frontend/
│   └── index.html          # 前端页面
├── data/
│   └── sample_papers.csv   # 示例文献数据
├── docs/
│   └── README.md           # 项目文档
└── README.md               # 本文件
```

## 🎯 核心功能

### 1. 文献管理
- CSV 格式批量导入
- 自动提取标签和关键词
- 文献列表浏览

### 2. 智能检索
- 基于 seekdb 的语义检索
- 关键词匹配与评分
- 多字段检索（标题、摘要、关键词、标签）

### 3. 个性化推荐
- 基于 PowerContext 的用户偏好记忆
- 标签匹配推荐算法
- 跨会话偏好保持

### 4. 进度追踪
- 阅读进度记录
- 学习历史管理
- 数据持久化

## 🌐 在线体验

本项目已通过 **Qoder Sites** 发布：

🔗 **访问地址**：[https://your-site.qoder.site](https://your-site.qoder.site)

（发布后替换为实际链接）

## 📝 开发记录

本项目使用 **Qoder** 开发，主要开发环节：

1. **需求分析**：Qoder 帮助梳理用户需求和功能设计
2. **架构设计**：Qoder 提供技术栈选型和架构建议
3. **代码实现**：
   - 后端 API：Qoder 生成 FastAPI 代码框架
   - 前端页面：Qoder 实现响应式 UI 设计
   - 数据模型：Qoder 设计 Pydantic 模型
4. **集成调试**：Qoder 协助 seekdb 和 PowerContext 集成
5. **部署发布**：通过 Qoder Sites 一键发布

**Qoder 账号 UID**：`your-uid-here`

（提交时替换为实际 UID）

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- **seekdb**：提供强大的语义检索能力
- **PowerContext**：提供用户记忆和上下文管理
- **Qoder**：提供智能开发辅助和部署平台
- **OceanBase**：提供技术支持和竞赛平台

---

**Built with ❤️ using Qoder**
