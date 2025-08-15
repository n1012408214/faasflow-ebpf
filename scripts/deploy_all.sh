#!/bin/bash

# FaaSFlow 自动化部署脚本
# 使用方法: ./deploy_all.sh

set -e

echo "=== FaaSFlow 自动化部署脚本 ==="
echo "请确保您已经在所有节点上克隆了FaaSFlow代码"
echo ""

# 检查是否在正确的目录
if [ ! -f "config/config.py" ]; then
    echo "错误: 请在FaaSFlow根目录下运行此脚本"
    exit 1
fi

echo "当前配置的IP地址:"
echo "Gateway: 192.168.2.156"
echo "Storage: 192.168.2.157"
echo "Worker1: 192.168.2.154"
echo "Worker2: 192.168.2.155"
echo ""

read -p "确认配置正确吗? (y/n): " confirm
if [ "$confirm" != "y" ]; then
    echo "部署已取消"
    exit 0
fi

echo ""
echo "=== 开始部署 ==="

# 检查当前节点类型
current_ip=$(hostname -I | awk '{print $1}')
echo "当前节点IP: $current_ip"

case $current_ip in
    "192.168.2.156")
        echo "检测到Gateway节点，开始部署..."
        sudo bash scripts/gateway_setup.bash
        echo "Gateway节点部署完成"
        ;;
    "192.168.2.157")
        echo "检测到Storage节点，开始部署..."
        sudo bash scripts/db_setup.bash
        echo "Storage节点部署完成"
        ;;
    "192.168.2.154"|"192.168.2.155")
        echo "检测到Worker节点，开始部署..."
        sudo bash scripts/worker_setup.bash
        echo "Worker节点部署完成"
        ;;
    *)
        echo "警告: 当前节点IP ($current_ip) 不在配置列表中"
        echo "请手动选择部署类型:"
        echo "1) Gateway节点 (192.168.2.156)"
        echo "2) Storage节点 (192.168.2.157)"
        echo "3) Worker节点 (192.168.2.154/192.168.2.155)"
        read -p "请选择 (1/2/3): " choice
        
        case $choice in
            1)
                echo "开始部署Gateway节点..."
                sudo bash scripts/gateway_setup.bash
                ;;
            2)
                echo "开始部署Storage节点..."
                sudo bash scripts/db_setup.bash
                ;;
            3)
                echo "开始部署Worker节点..."
                sudo bash scripts/worker_setup.bash
                ;;
            *)
                echo "无效选择，部署已取消"
                exit 1
                ;;
        esac
        ;;
esac

echo ""
echo "=== 部署完成 ==="
echo ""
echo "下一步操作:"
echo "1. 在Storage节点 (192.168.2.157) 上启动Kafka和CouchDB服务"
echo "2. 在Gateway节点 (192.168.2.156) 上运行: cd src/workflow_manager && python3 gateway.py 192.168.2.156 7000"
echo "3. 在Worker节点上运行: cd src/workflow_manager && python3 test_server.py <worker_ip>"
echo "4. 在Gateway节点上运行测试脚本"
echo ""
echo "详细说明请参考 DEPLOYMENT_GUIDE.md"


