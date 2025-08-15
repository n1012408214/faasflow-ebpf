#!/bin/bash

# FaaSFlow 快速启动脚本
# 使用方法: ./quick_start.sh

echo "=== FaaSFlow 快速启动脚本 ==="
echo "此脚本将启动当前节点上的所有FaaSFlow服务"
echo ""

# 检查是否在正确的目录
if [ ! -f "config/config.py" ]; then
    echo "错误: 请在FaaSFlow根目录下运行此脚本"
    exit 1
fi

# 检查当前节点类型
current_ip=$(hostname -I | awk '{print $1}')
echo "当前节点IP: $current_ip"

# 启动Storage服务
if [ "$current_ip" = "192.168.2.157" ]; then
    echo "启动Storage节点服务..."
    
    # 启动Kafka
    echo "启动Kafka服务..."
    docker-compose -f scripts/kafka/docker-compose.yml up -d
    
    # 启动CouchDB
    echo "启动CouchDB服务..."
    docker start couchdb 2>/dev/null || docker run -itd -p 5984:5984 -e COUCHDB_USER=openwhisk -e COUCHDB_PASSWORD=openwhisk --name couchdb couchdb
    
    echo "Storage服务启动完成"
    echo "Kafka运行在: 192.168.2.157:9092"
    echo "CouchDB运行在: 192.168.2.157:5984"
    exit 0
fi

# 启动Gateway服务
if [ "$current_ip" = "192.168.2.156" ]; then
    echo "启动Gateway服务..."
    cd src/workflow_manager
    echo "运行Gateway服务: python3 gateway.py 192.168.2.156 7000"
    python3 gateway.py 192.168.2.156 7000
    exit 0
fi

# 启动Worker服务
if [ "$current_ip" = "192.168.2.154" ] || [ "$current_ip" = "192.168.2.155" ]; then
    echo "启动Worker代理服务..."
    cd src/workflow_manager
    echo "运行Worker代理: python3 test_server.py $current_ip"
    python3 test_server.py $current_ip
    exit 0
fi

# 如果IP不匹配，提供手动选择
echo "警告: 当前节点IP ($current_ip) 不在配置列表中"
echo "请手动选择要启动的服务:"
echo "1) Gateway服务 (192.168.2.156)"
echo "2) Storage服务 (192.168.2.157)"
echo "3) Worker代理服务 (192.168.2.154/192.168.2.155)"
read -p "请选择 (1/2/3): " choice

case $choice in
    1)
        echo "启动Gateway服务..."
        cd src/workflow_manager
        python3 gateway.py 192.168.2.156 7000
        ;;
    2)
        echo "启动Storage服务..."
        docker-compose -f scripts/kafka/docker-compose.yml up -d
        docker start couchdb 2>/dev/null || docker run -itd -p 5984:5984 -e COUCHDB_USER=openwhisk -e COUCHDB_PASSWORD=openwhisk --name couchdb couchdb
        echo "Storage服务启动完成"
        ;;
    3)
        echo "启动Worker代理服务..."
        cd src/workflow_manager
        read -p "请输入Worker IP地址: " worker_ip
        python3 test_server.py $worker_ip
        ;;
    *)
        echo "无效选择，启动已取消"
        exit 1
        ;;
esac


