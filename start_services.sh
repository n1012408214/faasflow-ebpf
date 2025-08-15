#!/bin/bash

# FaaSFlow 服务启动脚本
# 使用方法: ./start_services.sh

set -e

echo "=== FaaSFlow 服务启动脚本 ==="

# 检查是否在正确的目录
if [ ! -f "config/config.py" ]; then
    echo "错误: 请在FaaSFlow根目录下运行此脚本"
    exit 1
fi

# 检查当前节点类型
current_ip=$(hostname -I | awk '{print $1}')
echo "当前节点IP: $current_ip"

case $current_ip in
    "192.168.2.156")
        echo "启动Gateway服务..."
        cd src/workflow_manager
        echo "运行: python3 gateway.py 192.168.2.156 7000"
        python3 gateway.py 192.168.2.156 7000
        ;;
    "192.168.2.157")
        echo "启动Storage服务..."
        echo "启动Kafka服务..."
        docker-compose -f scripts/kafka/docker-compose.yml up -d
        echo "启动CouchDB服务..."
        docker start couchdb
        echo "Storage服务启动完成"
        echo "Kafka运行在: 192.168.2.157:9092"
        echo "CouchDB运行在: 192.168.2.157:5984"
        ;;
    "192.168.2.154"|"192.168.2.155")
        echo "启动Worker代理服务..."
        cd src/workflow_manager
        echo "运行: python3 test_server.py $current_ip"
        python3 test_server.py $current_ip
        ;;
    *)
        echo "警告: 当前节点IP ($current_ip) 不在配置列表中"
        echo "请手动选择启动的服务:"
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
                docker start couchdb
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
        ;;
esac

