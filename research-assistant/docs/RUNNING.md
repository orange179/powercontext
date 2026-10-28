# 运行说明

## 环境要求

- Python 3.11 或更高版本
- pip 或 uv 包管理器
- 现代浏览器（Chrome、Firefox、Edge 等）

## 安装步骤

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd research-assistant
```

### 2. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 3. 启动服务

**方式一：使用启动脚本（推荐）**

```bash
# Linux/Mac
chmod +x start.sh
./start.sh

# Windows
cd backend
python main.py
```

**方式二：手动启动**

```bash
cd backend
python main.py
```

服务将在 `http://localhost:8000` 启动。

## 访问应用

- **前端页面**：http://localhost:8000/app
- **API 文档**：http://localhost:8000/docs

## 功能演示

### 1. 导入文献数据

1. 打开浏览器访问 http://localhost:8000/app
2. 点击"导入文献"标签
3. 复制 `data/sample_papers.csv` 文件内容
4. 粘贴到输入框
5. 点击"导入"按钮

预期结果：成功导入 7 篇文献，统计数字更新。

### 2. 语义检索

1. 点击"检索文献"标签
2. 在搜索框输入："Transformer"
3. 点击"检索"按钮

预期结果：返回包含 Transformer 相关内容的文献，显示匹配度分数。

### 3. 设置个人偏好

1. 点击"个人偏好"标签
2. 输入用户 ID：`user1`
3. 选择感兴趣的标签（如：深度学习、NLP）
4. 点击"保存偏好"

预期结果：偏好保存成功，PowerContext 记忆存储。

### 4. 查看文献列表

1. 点击"文献列表"标签

预期结果：显示所有已导入的文献。

## 技术验证

### seekdb 集成验证

在检索功能中，系统使用 seekdb 的语义检索能力：
- 输入关键词后，系统返回匹配的文献
- 匹配度分数基于向量相似度计算
- 支持多字段检索（标题、摘要、关键词、标签）

### PowerContext 集成验证

在个人偏好功能中，系统使用 PowerContext 存储用户记忆：
- 用户偏好被保存到 PowerContext
- 跨会话保持用户偏好
- 基于偏好提供个性化推荐

## API 接口

### POST /api/documents/import
导入 CSV 格式的文献数据

**请求体**：CSV 字符串

**响应**：导入的文献列表

### GET /api/documents
获取所有文献列表

### POST /api/search
语义检索文献

**请求体**：
```json
{
  "query": "Transformer",
  "top_k": 5
}
```

**响应**：匹配的文献列表及分数

### GET /api/user/{user_id}/preferences
获取用户偏好

### POST /api/user/{user_id}/preferences
更新用户偏好

## 故障排查

### 问题：端口被占用

**解决方案**：修改 `backend/main.py` 中的端口号

```python
uvicorn.run(app, host="0.0.0.0", port=8001)
```

### 问题：依赖安装失败

**解决方案**：使用 uv 替代 pip

```bash
pip install uv
uv pip install -r requirements.txt
```

### 问题：前端页面无法访问

**解决方案**：检查 `frontend` 目录是否存在，确保路径正确

## 停止服务

按 `Ctrl+C` 停止服务

---

如有问题，请查看 `README.md` 或提交 Issue。
