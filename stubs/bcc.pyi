# BCC库的类型存根文件
# 用于消除类型检查器关于bcc模块的警告

from typing import Any, Dict, Optional, Union, Callable
import ctypes

class BPF:
    """BPF类的类型存根"""
    
    # 程序类型常量
    KPROBE: int
    KRETPROBE: int
    TRACEPOINT: int
    XDP: int
    PERF_EVENT: int
    CGROUP_SKB: int
    CGROUP_SOCK: int
    LWT_IN: int
    LWT_OUT: int
    LWT_XMIT: int
    SOCK_OPS: int
    SK_SKB: int
    CGROUP_DEVICE: int
    SK_MSG: int
    RAW_TRACEPOINT: int
    CGROUP_SOCK_ADDR: int
    LWT_SEG6LOCAL: int
    LIRC_MODE2: int
    SK_REUSEPORT: int
    FLOW_DISSECTOR: int
    
    def __init__(
        self,
        text: Optional[str] = None,
        src_file: Optional[str] = None,
        hdr_file: Optional[str] = None,
        cflags: Optional[list] = None,
        usdt: Optional[Any] = None,
        usdt_contexts: Optional[list] = None,
        debug: int = 0,
        device: Optional[Any] = None,
        allow_rlimit: bool = True
    ) -> None: ...
    
    def attach_kprobe(
        self,
        event: str,
        fn_name: str,
        event_off: int = 0,
        pid: int = -1,
        cpu: int = 0,
        group_fd: int = -1
    ) -> None: ...
    
    def attach_kretprobe(
        self,
        event: str,
        fn_name: str,
        event_off: int = 0,
        pid: int = -1,
        cpu: int = 0,
        group_fd: int = -1
    ) -> None: ...
    
    def attach_tracepoint(
        self,
        tp: str,
        fn_name: str,
        pid: int = -1,
        cpu: int = 0,
        group_fd: int = -1
    ) -> None: ...
    
    def attach_xdp(
        self,
        dev: str,
        fn: Callable,
        flags: int = 0
    ) -> None: ...
    
    def detach_kprobe(self, event: str) -> None: ...
    def detach_kretprobe(self, event: str) -> None: ...
    def detach_tracepoint(self, tp: str) -> None: ...
    def detach_xdp(self, dev: str) -> None: ...
    
    def get_table(self, name: str) -> 'Table': ...
    def load_func(self, func_name: str, prog_type: int) -> int: ...
    
    def trace_print(self, fmt: str = None) -> None: ...
    def trace_fields(self, nonblocking: bool = False) -> tuple: ...
    
    def cleanup(self) -> None: ...

class Table:
    """BPF Table类的类型存根"""
    
    def __init__(self, bpf: BPF, map_id: int, map_fd: int, keytype: type, leaftype: type) -> None: ...
    
    def __getitem__(self, key: Any) -> Any: ...
    def __setitem__(self, key: Any, value: Any) -> None: ...
    def __delitem__(self, key: Any) -> None: ...
    def __contains__(self, key: Any) -> bool: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Any: ...
    
    def items(self) -> Any: ...
    def keys(self) -> Any: ...
    def values(self) -> Any: ...
    def clear(self) -> None: ...
    def update(self, other: Dict) -> None: ...
    
    def get(self, key: Any, default: Any = None) -> Any: ...
    def pop(self, key: Any, default: Any = None) -> Any: ...
    
    # BPF特有方法
    def open_perf_buffer(
        self,
        callback: Callable,
        page_cnt: int = 8,
        lost_cb: Optional[Callable] = None
    ) -> 'PerfBuffer': ...
    
    def poll(self, timeout: int = -1) -> None: ...

class PerfBuffer:
    """Perf Buffer类的类型存根"""
    
    def poll(self, timeout: int = -1) -> None: ...
    def kprobe_poll(self, timeout: int = -1) -> None: ...

# 全局函数
def attach_xdp(dev: str, fn: Callable, flags: int = 0) -> None: ...
def remove_xdp(dev: str, flags: int = 0) -> None: ...

# 常量
XDP_FLAGS_UPDATE_IF_NOEXIST: int
XDP_FLAGS_SKB_MODE: int
XDP_FLAGS_DRV_MODE: int
XDP_FLAGS_HW_MODE: int

# CT相关
class CT:
    def __init__(self) -> None: ...

# USDT相关
class USDT:
    def __init__(self, pid: int = -1, path: str = "") -> None: ...
    def enable_probe(self, probe: str, fn_name: str) -> None: ...
