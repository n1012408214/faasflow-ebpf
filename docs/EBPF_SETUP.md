# eBPF设置指南

## 概述

FaaSFlow使用eBPF技术进行高性能的容器间数据传输。本指南将帮助您正确安装和配置eBPF相关依赖。

## 系统要求

- Linux内核版本 >= 4.4 (推荐 >= 5.0)
- 具有root权限或适当的capabilities
- Python 3.7+

## 安装步骤

### 1. 检查内核版本

```bash
uname -r
# 输出应该显示 >= 4.4 的版本号
```

### 2. 安装系统依赖

#### Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y \
    linux-headers-$(uname -r) \
    bpfcc-tools \
    libbpf-dev \
    python3-bpfcc
```

#### CentOS/RHEL:

```bash
sudo yum install -y \
    kernel-devel \
    bcc-tools \
    libbpf-devel \
    python3-bcc
```

### 3. 安装Python BCC库

```bash
pip install bcc
```

或者从源码安装（如果包管理器版本过旧）：

```bash
git clone https://github.com/iovisor/bcc.git
cd bcc
mkdir build && cd build
cmake ..
make
sudo make install
cd src/python/
make
sudo make install
```

### 4. 验证安装

```bash
# 测试BCC是否正确安装
python3 -c "from bcc import BPF; print('BCC安装成功')"

# 检查eBPF功能
sudo python3 -c "
from bcc import BPF
b = BPF(text='int hello(void *ctx) { return 0; }')
print('eBPF程序编译成功')
"
```

## 权限配置

### 方式1: 使用root权限（简单但不推荐生产环境）

```bash
sudo python3 your_faasflow_script.py
```

### 方式2: 配置capabilities（推荐）

```bash
# 为Python解释器添加必要的capabilities
sudo setcap 'CAP_SYS_ADMIN+ep CAP_NET_ADMIN+ep CAP_BPF+ep' /usr/bin/python3

# 现在可以以普通用户运行
python3 your_faasflow_script.py
```

### 方式3: 用户组配置

```bash
# 添加用户到bpf组（如果存在）
sudo usermod -a -G bpf $USER

# 重新登录或使用newgrp
newgrp bpf
```

## 故障排除

### 问题1: "bcc模块未找到"

```bash
# 检查Python路径
python3 -c "import sys; print('\\n'.join(sys.path))"

# 确保BCC安装路径在Python路径中
export PYTHONPATH="/usr/lib/python3/dist-packages:$PYTHONPATH"
```

### 问题2: "权限不足"

```bash
# 检查当前用户权限
id

# 检查capabilities
getcap /usr/bin/python3

# 如果没有输出，需要按上述步骤配置capabilities
```

### 问题3: "内核头文件缺失"

```bash
# 安装匹配当前内核的头文件
sudo apt install linux-headers-$(uname -r)

# 或在CentOS上
sudo yum install kernel-devel-$(uname -r)
```

### 问题4: "eBPF程序编译失败"

```bash
# 检查内核配置
zcat /proc/config.gz | grep -E 'CONFIG_BPF|CONFIG_DEBUG_INFO'

# 应该看到:
# CONFIG_BPF=y
# CONFIG_BPF_SYSCALL=y
# CONFIG_DEBUG_INFO=y
```

## 性能调优

### 内核参数优化

```bash
# 增加eBPF Map的内存限制
echo 'net.core.bpf_jit_enable = 1' >> /etc/sysctl.conf
echo 'net.core.bpf_jit_harden = 0' >> /etc/sysctl.conf
sysctl -p
```

### 监控eBPF使用情况

```bash
# 查看已加载的eBPF程序
sudo bpftool prog show

# 查看eBPF Maps
sudo bpftool map show

# 实时跟踪eBPF事件
sudo cat /sys/kernel/debug/tracing/trace_pipe | grep FaaSFlow
```

## Docker环境配置

如果在Docker容器中使用eBPF，需要特殊配置：

```dockerfile
FROM ubuntu:20.04

# 安装eBPF依赖
RUN apt update && apt install -y \
    linux-headers-generic \
    bpfcc-tools \
    libbpf-dev \
    python3-pip

# 安装Python BCC
RUN pip3 install bcc

# 运行时需要特权模式
```

运行Docker容器：

```bash
docker run --privileged \
    -v /sys/kernel/debug:/sys/kernel/debug:rw \
    -v /usr/src:/usr/src:ro \
    -v /lib/modules:/lib/modules:ro \
    your-faasflow-image
```

## 开发环境配置

### VSCode配置

在`.vscode/settings.json`中添加：

```json
{
    "python.analysis.stubPath": "./stubs",
    "python.analysis.typeCheckingMode": "basic"
}
```

### 类型检查配置

项目包含了`pyproject.toml`配置文件，自动处理BCC库的类型检查。

## 参考资料

- [BCC官方文档](https://github.com/iovisor/bcc)
- [eBPF内核文档](https://docs.kernel.org/bpf/)
- [Linux capabilities手册](https://man7.org/linux/man-pages/man7/capabilities.7.html)
