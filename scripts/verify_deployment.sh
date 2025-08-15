#!/bin/bash

# FaaSFlow 部署验证脚本
# 使用方法: ./verify_deployment.sh

echo "=== FaaSFlow 部署验证脚本 ==="

# 检查是否在正确的目录
if [ ! -f "config/config.py" ]; then
    echo "错误: 请在FaaSFlow根目录下运行此脚本"
    exit 1
fi

# 定义节点IP
GATEWAY_IP="192.168.2.156"
STORAGE_IP="192.168.2.157"
WORKER1_IP="192.168.2.154"
WORKER2_IP="192.168.2.155"

echo "验证配置文件..."
echo ""

# 检查配置文件
echo "1. 检查配置文件:"
if grep -q "192.168.2.156" config/config.py; then
    echo "  ✓ Gateway IP配置正确"
else
    echo "  ✗ Gateway IP配置错误"
fi

if grep -q "192.168.2.157" config/config.py; then
    echo "  ✓ Storage IP配置正确"
else
    echo "  ✗ Storage IP配置错误"
fi

if grep -q "192.168.2.154" config/config.py && grep -q "192.168.2.155" config/config.py; then
    echo "  ✓ Worker IP配置正确"
else
    echo "  ✗ Worker IP配置错误"
fi
echo ""

# 检查Docker服务
echo "2. 检查Docker服务:"
if systemctl is-active --quiet docker; then
    echo "  ✓ Docker服务正在运行"
else
    echo "  ✗ Docker服务未运行"
fi
echo ""

# 检查Docker容器
echo "3. 检查Docker容器:"
if docker ps | grep -q "couchdb"; then
    echo "  ✓ CouchDB容器正在运行"
else
    echo "  ✗ CouchDB容器未运行"
fi

if docker ps | grep -q "broker"; then
    echo "  ✓ Kafka容器正在运行"
else
    echo "  ✗ Kafka容器未运行"
fi

if docker ps | grep -q "redis"; then
    echo "  ✓ Redis容器正在运行"
else
    echo "  ✗ Redis容器未运行"
fi
echo ""

# 检查Python依赖
echo "4. 检查Python依赖:"
if python3 -c "import redis, kafka, couchdb" 2>/dev/null; then
    echo "  ✓ Python依赖包已安装"
else
    echo "  ✗ Python依赖包缺失"
fi
echo ""

# 检查网络连通性
echo "5. 检查网络连通性:"
if ping -c 1 -W 2 $STORAGE_IP > /dev/null 2>&1; then
    echo "  ✓ Storage节点网络可达"
else
    echo "  ✗ Storage节点网络不可达"
fi

if ping -c 1 -W 2 $GATEWAY_IP > /dev/null 2>&1; then
    echo "  ✓ Gateway节点网络可达"
else
    echo "  ✗ Gateway节点网络不可达"
fi

for worker_ip in $WORKER1_IP $WORKER2_IP; do
    if ping -c 1 -W 2 $worker_ip > /dev/null 2>&1; then
        echo "  ✓ Worker节点 $worker_ip 网络可达"
    else
        echo "  ✗ Worker节点 $worker_ip 网络不可达"
    fi
done
echo ""

# 检查服务端口
echo "6. 检查服务端口:"
if nc -z -w2 $STORAGE_IP 5984 2>/dev/null; then
    echo "  ✓ CouchDB端口 (5984) 可访问"
else
    echo "  ✗ CouchDB端口 (5984) 不可访问"
fi

if nc -z -w2 $STORAGE_IP 9092 2>/dev/null; then
    echo "  ✓ Kafka端口 (9092) 可访问"
else
    echo "  ✗ Kafka端口 (9092) 不可访问"
fi

if nc -z -w2 localhost 6379 2>/dev/null; then
    echo "  ✓ Redis端口 (6379) 可访问"
else
    echo "  ✗ Redis端口 (6379) 不可访问"
fi
echo ""

echo "=== 验证完成 ==="
echo ""
echo "如果发现问题，请:"
echo "1. 检查 DEPLOYMENT_GUIDE.md 中的部署步骤"
echo "2. 运行 ./scripts/network_test.sh 进行网络测试"
echo "3. 确保所有服务都已正确启动"
echo "4. 检查防火墙设置"


