# FaaSFlow 部署指南

## 服务器配置

根据您的需求，FaaSFlow将按照以下配置部署：

- **Gateway节点**: 192.168.2.156
- **Storage节点**: 192.168.2.157  
- **Worker1节点**: 192.168.2.154
- **Worker2节点**: 192.168.2.155

## 硬件要求

- **Gateway节点**: 最小配置 {CPU: 8核, 内存: 16GB, 硬盘: 200GB SSD}
- **Storage节点**: 最小配置 {CPU: 8核, 内存: 16GB, 硬盘: 200GB SSD}
- **Worker节点**: 最小配置 {CPU: 16核, 内存: 64GB, 硬盘: 200GB SSD}

所有节点需要运行 Ubuntu 20.04。

## 部署步骤

### 1. 代码准备

在所有节点上克隆FaaSFlow代码：
```bash
git clone https://github.com/lzjzx1122/FaaSFlow.git
cd FaaSFlow
```

### 2. Storage节点部署 (192.168.2.157)

在Storage节点上执行以下命令：

```bash
cd ~/FaaSFlow
sudo bash scripts/db_setup.bash
```

这将安装：
- Docker
- Kafka (通过docker-compose)
- CouchDB
- Python依赖包

### 3. Gateway节点部署 (192.168.2.156)

在Gateway节点上执行以下命令：

```bash
cd ~/FaaSFlow
sudo bash scripts/gateway_setup.bash
```

这将安装：
- Docker
- CouchDB
- Python依赖包

### 4. Worker节点部署 (192.168.2.154, 192.168.2.155)

在每个Worker节点上执行以下命令：

```bash
cd ~/FaaSFlow
sudo bash scripts/worker_setup.bash
```

这将安装：
- Docker
- Redis
- Python依赖包
- 构建4个benchmark的Docker镜像

## 启动服务

### 1. 启动Gateway

在Gateway节点 (192.168.2.156) 上：

```bash
cd ~/FaaSFlow/src/workflow_manager
python3 gateway.py 192.168.2.156 7000
```

### 2. 启动Worker代理

在Worker1节点 (192.168.2.154) 上：

```bash
cd ~/FaaSFlow/src/workflow_manager
python3 test_server.py 192.168.2.154
```

在Worker2节点 (192.168.2.155) 上：

```bash
cd ~/FaaSFlow/src/workflow_manager
python3 test_server.py 192.168.2.155
```

## 运行测试

所有测试脚本都在Gateway节点上运行。

### 响应延迟测试
```bash
cd ~/FaaSFlow/test
python3 async_test.py
```

### 峰值吞吐量测试
```bash
cd ~/FaaSFlow/test
python3 sync_test.py
```

### 多工作流共置测试
```bash
cd ~/FaaSFlow/test
python3 async_colocation_test.py
```

## 注意事项

1. **重启建议**: 每次运行测试脚本前，建议重启所有节点的服务以避免潜在问题：
   - 重启Gateway: `python3 gateway.py 192.168.2.156 7000`
   - 重启Worker代理: `python3 test_server.py <worker_ip>`

2. **网络连通性**: 确保所有节点之间网络连通，特别是：
   - Gateway (192.168.2.156) 可以访问 Storage (192.168.2.157)
   - Worker节点可以访问 Storage (192.168.2.157)
   - Gateway可以访问所有Worker节点

3. **防火墙设置**: 确保以下端口开放：
   - 7000: Gateway服务端口
   - 5984: CouchDB端口
   - 9092: Kafka端口
   - 6379: Redis端口

4. **DataFlower限制**: 当前DataFlower支持最多3个worker节点，您的配置符合要求。

## 故障排除

如果遇到连接问题，请检查：
1. 网络连通性
2. 防火墙设置
3. 服务是否正常启动
4. 配置文件中的IP地址是否正确

## 验证部署

部署完成后，可以通过运行测试脚本来验证系统是否正常工作。预期结果可以在 `test/expected_results/` 目录中找到。


