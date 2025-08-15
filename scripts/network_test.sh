#!/bin/bash

# FaaSFlow 网络连通性测试脚本
# 使用方法: ./network_test.sh

echo "=== FaaSFlow 网络连通性测试 ==="

# 定义节点IP
GATEWAY_IP="192.168.2.156"
STORAGE_IP="192.168.2.157"
WORKER1_IP="192.168.2.154"
WORKER2_IP="192.168.2.155"

# 定义端口
GATEWAY_PORT="7000"
COUCHDB_PORT="5984"
KAFKA_PORT="9092"
REDIS_PORT="6379"

echo "测试节点间网络连通性..."
echo ""

# 测试基本连通性
echo "1. 测试基本网络连通性 (ping):"
for ip in $GATEWAY_IP $STORAGE_IP $WORKER1_IP $WORKER2_IP; do
    if ping -c 1 -W 2 $ip > /dev/null 2>&1; then
        echo "  ✓ $ip - 可达"
    else
        echo "  ✗ $ip - 不可达"
    fi
done
echo ""

# 测试端口连通性
echo "2. 测试端口连通性:"

# Gateway端口
if nc -z -w2 $GATEWAY_IP $GATEWAY_PORT 2>/dev/null; then
    echo "  ✓ Gateway ($GATEWAY_IP:$GATEWAY_PORT) - 可连接"
else
    echo "  ✗ Gateway ($GATEWAY_IP:$GATEWAY_PORT) - 不可连接"
fi

# CouchDB端口
if nc -z -w2 $STORAGE_IP $COUCHDB_PORT 2>/dev/null; then
    echo "  ✓ CouchDB ($STORAGE_IP:$COUCHDB_PORT) - 可连接"
else
    echo "  ✗ CouchDB ($STORAGE_IP:$COUCHDB_PORT) - 不可连接"
fi

# Kafka端口
if nc -z -w2 $STORAGE_IP $KAFKA_PORT 2>/dev/null; then
    echo "  ✓ Kafka ($STORAGE_IP:$KAFKA_PORT) - 可连接"
else
    echo "  ✗ Kafka ($STORAGE_IP:$KAFKA_PORT) - 不可连接"
fi

# Worker节点的Redis端口
for worker_ip in $WORKER1_IP $WORKER2_IP; do
    if nc -z -w2 $worker_ip $REDIS_PORT 2>/dev/null; then
        echo "  ✓ Worker Redis ($worker_ip:$REDIS_PORT) - 可连接"
    else
        echo "  ✗ Worker Redis ($worker_ip:$REDIS_PORT) - 不可连接"
    fi
done
echo ""

# 测试HTTP服务
echo "3. 测试HTTP服务:"

# CouchDB HTTP服务
if curl -s --connect-timeout 2 "http://$STORAGE_IP:$COUCHDB_PORT" > /dev/null 2>&1; then
    echo "  ✓ CouchDB HTTP服务 ($STORAGE_IP:$COUCHDB_PORT) - 可访问"
else
    echo "  ✗ CouchDB HTTP服务 ($STORAGE_IP:$COUCHDB_PORT) - 不可访问"
fi
echo ""

echo "=== 测试完成 ==="
echo ""
echo "如果发现连接问题，请检查:"
echo "1. 防火墙设置"
echo "2. 网络配置"
echo "3. 服务是否已启动"
echo "4. IP地址是否正确"


