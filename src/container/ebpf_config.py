# eBPF配置文件
# FaaSFlow eBPF数据传输优化配置

# eBPF功能开关
ENABLE_EBPF = True

# eBPF Map配置
EBPF_MAP_SIZE = 1024  # 最大存储条目数
EBPF_DATA_SIZE = 4096  # 单个数据条目最大大小 (4KB)
EBPF_RINGBUF_SIZE = 1 << 20  # RingBuf大小 (1MB)

# 性能调优参数
EBPF_FALLBACK_ENABLED = True  # 允许回退到传统方法
EBPF_DEBUG_MODE = False  # 调试模式
EBPF_BATCH_SIZE = 10  # 批处理大小

# 网络接口配置
EBPF_INTERFACE = "eth0"  # XDP附加的网络接口
EBPF_XDP_MODE = "generic"  # XDP模式: generic, native, offload

# 监控配置
EBPF_ENABLE_METRICS = True  # 启用性能指标收集
EBPF_METRICS_INTERVAL = 5  # 指标收集间隔(秒)
