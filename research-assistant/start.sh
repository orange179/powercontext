#!/bin/bash

echo "🚀 启动文献整理助手..."
echo ""

cd backend

echo "📦 安装依赖..."
pip install -r requirements.txt

echo ""
echo "🌐 启动服务..."
echo "访问地址: http://localhost:8000/app"
echo ""

python main.py
