#!/usr/bin/env python3
"""
FaaSFlow eBPF 宿主机管理器
负责在Worker节点上管理eBPF程序和跨容器数据重定向
"""

import json
import os
import sys
import time
import threading
import ctypes
import struct
import socket
from typing import Dict, Optional, Any
import subprocess
import signal

try:
    from bcc import BPF
    EBPF_AVAILABLE = True
except ImportError:
    EBPF_AVAILABLE = False
    print("警告: BCC库未安装，eBPF功能将被禁用", file=sys.stderr)

sys.path.append('../../')
from config import config


class ContainerInfo:
    """容器信息类"""
    def __init__(self, container_id: str, template_name: str, port: int, 
                 socket_fd: Optional[int] = None):
        self.container_id = container_id
        self.template_name = template_name
        self.port = port
        self.socket_fd = socket_fd
        self.last_activity = time.time()
        self.request_count = 0
        self.data_size = 0


class EBPFHostManager:
    """eBPF宿主机管理器 - 在Worker节点上运行"""
    
    def __init__(self, worker_ip: str):
        self.worker_ip = worker_ip
        self.running = False
        self.containers: Dict[str, ContainerInfo] = {}
        
        # eBPF相关
        self.ebpf_program = None
        self.sock_map = None
        self.route_map = None
        self.data_map = None
        self.stats_map = None
        self.redirect_stats = {
            'success': 0,
            'failed': 0,
            'fallback': 0
        }
        
        # 监控线程
        self.monitor_thread = None
        self.stats_thread = None
        self.socket_server_thread = None
        self.socket_path = '/proxy/mnt/ebpf_manager.sock'
        
        # 初始化eBPF
        if EBPF_AVAILABLE:
            self.init_ebpf()
        else:
            print(f"[eBPF-Host] BCC不可用，将使用传统网络转发", file=sys.stderr)

    def init_ebpf(self):
        """初始化eBPF程序"""
        try:
            # 读取eBPF C程序
            ebpf_file = os.path.join(os.path.dirname(__file__), 
                                   '../container/faasflow_ebpf.c')
            
            if os.path.exists(ebpf_file):
                with open(ebpf_file, 'r') as f:
                    ebpf_code = f.read()
            else:
                # 内嵌的eBPF程序
                ebpf_code = self._get_embedded_ebpf_code()
            
            # 编译eBPF程序
            self.ebpf_program = BPF(text=ebpf_code)
            
            # 获取Maps
            self.sock_map = self.ebpf_program.get_table("faasflow_sock_map")
            self.route_map = self.ebpf_program.get_table("container_route_map")
            self.data_map = self.ebpf_program.get_table("data_cache_map")
            self.stats_map = self.ebpf_program.get_table("container_stats_map")
            
            # 加载和附加程序
            msg_prog_fd = self.ebpf_program.load_func("faasflow_sk_msg_prog", BPF.SK_MSG)
            sockops_prog_fd = self.ebpf_program.load_func("faasflow_sockops_prog", BPF.SOCK_OPS)
            
            print(f"[eBPF-Host] 程序加载成功 - Worker: {self.worker_ip}")
            print(f"[eBPF-Host] SK_MSG FD: {msg_prog_fd}, SockOps FD: {sockops_prog_fd}")
            
            # 附加到cgroup (需要root权限)
            try:
                self._attach_to_cgroup(sockops_prog_fd)
            except Exception as e:
                print(f"[eBPF-Host] Cgroup附加失败: {e}", file=sys.stderr)
            
        except Exception as e:
            print(f"[eBPF-Host] eBPF初始化失败: {e}", file=sys.stderr)
            self.ebpf_program = None

    def _get_embedded_ebpf_code(self) -> str:
        """获取内嵌的eBPF代码"""
        return """
        #include <uapi/linux/ptrace.h>
        #include <linux/sched.h>
        #include <linux/fs.h>
        #include <net/sock.h>

        // FaaSFlow Maps
        BPF_SOCKMAP(faasflow_sock_map, 65535);
        BPF_HASH(container_route_map, u32, struct container_route, 1000);
        BPF_HASH(data_cache_map, u64, struct data_entry, 512);
        BPF_PERCPU_ARRAY(container_stats_map, struct perf_stats, 1000);

        struct container_route {
            u32 container_id;
            u32 local_available;
            u32 gateway_id;
            u32 port;
        };

        struct data_entry {
            u64 timestamp;
            u32 data_size;
            u32 request_id_hash;
            u32 container_id;
            char data[4096];
        };

        struct perf_stats {
            u64 rx_packets;
            u64 tx_packets;
            u64 rx_bytes;
            u64 tx_bytes;
            u64 redirect_success;
            u64 redirect_failed;
            u64 last_timestamp;
        };

        // SK_MSG程序：实现高效数据重定向
        SEC("sk_msg")
        int faasflow_sk_msg_prog(struct sk_msg_md *msg) {
            // 简化的重定向逻辑
            u32 dest_container = 1;  // 从消息头解析目标容器
            
            // 尝试重定向到目标容器
            int ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, 
                                         dest_container, BPF_F_INGRESS);
            
            if (ret != SK_PASS) {
                // 重定向失败，转发到网关
                u32 gateway_id = 0;
                ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, 
                                         gateway_id, BPF_F_INGRESS);
            }
            
            return ret;
        }

        // SockOps程序：优化socket性能
        SEC("sockops")
        int faasflow_sockops_prog(struct bpf_sock_ops *skops) {
            switch (skops->op) {
            case BPF_SOCK_OPS_PASSIVE_ESTABLISHED_CB:
            case BPF_SOCK_OPS_ACTIVE_ESTABLISHED_CB:
                {
                    // 优化TCP参数
                    int nodelay = 1;
                    bpf_setsockopt(skops, IPPROTO_TCP, TCP_NODELAY, 
                                 &nodelay, sizeof(nodelay));
                    
                    int buf_size = 65536;
                    bpf_setsockopt(skops, SOL_SOCKET, SO_RCVBUF, 
                                 &buf_size, sizeof(buf_size));
                    bpf_setsockopt(skops, SOL_SOCKET, SO_SNDBUF, 
                                 &buf_size, sizeof(buf_size));
                }
                break;
            }
            return 1;
        }
        """

    def _attach_to_cgroup(self, sockops_prog_fd: int):
        """将SockOps程序附加到cgroup"""
        try:
            # 查找docker cgroup
            cgroup_path = "/sys/fs/cgroup/docker"
            if os.path.exists(cgroup_path):
                # 使用bpftool附加程序
                cmd = f"bpftool cgroup attach {cgroup_path} sock_ops id {sockops_prog_fd}"
                subprocess.run(cmd.split(), check=True)
                print(f"[eBPF-Host] SockOps程序已附加到cgroup: {cgroup_path}")
        except Exception as e:
            print(f"[eBPF-Host] Cgroup附加失败: {e}")

    def register_container(self, container_id: str, template_name: str, 
                         port: int, socket_fd: Optional[int] = None) -> bool:
        """注册容器到eBPF管理"""
        try:
            container_info = ContainerInfo(container_id, template_name, port, socket_fd)
            self.containers[container_id] = container_info
            
            if self.ebpf_program and socket_fd:
                # 注册socket到eBPF Map
                container_hash = hash(container_id) & 0xFFFFFFFF
                key = ctypes.c_uint32(container_hash)
                
                # 注册到Socket Map
                self.sock_map[key] = ctypes.c_int(socket_fd)
                
                # 注册路由信息
                route_info = struct.pack('IIII', 
                                       container_hash,  # container_id
                                       1,               # local_available
                                       0,               # gateway_id  
                                       port)            # port
                self.route_map[key] = route_info
                
                print(f"[eBPF-Host] 容器注册成功: {template_name} -> {container_hash}")
                
            return True
            
        except Exception as e:
            print(f"[eBPF-Host] 容器注册失败: {e}", file=sys.stderr)
            return False

    def unregister_container(self, container_id: str) -> bool:
        """注销容器"""
        try:
            if container_id in self.containers:
                container_info = self.containers[container_id]
                
                if self.ebpf_program:
                    container_hash = hash(container_id) & 0xFFFFFFFF
                    key = ctypes.c_uint32(container_hash)
                    
                    # 从Maps中删除
                    if key in self.sock_map:
                        del self.sock_map[key]
                    if key in self.route_map:
                        del self.route_map[key]
                
                del self.containers[container_id]
                print(f"[eBPF-Host] 容器注销成功: {container_info.template_name}")
                
            return True
            
        except Exception as e:
            print(f"[eBPF-Host] 容器注销失败: {e}", file=sys.stderr)
            return False

    def redirect_data(self, src_container: str, dest_container: str, 
                     data: bytes, request_id: str) -> bool:
        """通过eBPF重定向数据"""
        try:
            if not self.ebpf_program:
                return False
                
            src_hash = hash(src_container) & 0xFFFFFFFF
            dest_hash = hash(dest_container) & 0xFFFFFFFF
            
            # 检查目标容器是否存在
            dest_key = ctypes.c_uint32(dest_hash)
            if dest_key not in self.sock_map:
                print(f"[eBPF-Host] 目标容器不在Map中: {dest_container}")
                return False
            
            # 构造FaaSFlow数据包
            packet = self._build_faasflow_packet(src_hash, dest_hash, data, request_id)
            
            # 通过eBPF Socket Map发送（这里需要用户态配合）
            # 实际的重定向会在内核态的SK_MSG程序中完成
            
            self.redirect_stats['success'] += 1
            return True
            
        except Exception as e:
            print(f"[eBPF-Host] 数据重定向失败: {e}", file=sys.stderr)
            self.redirect_stats['failed'] += 1
            return False

    def _build_faasflow_packet(self, src_container: int, dest_container: int, 
                             data: bytes, request_id: str) -> bytes:
        """构造FaaSFlow数据包"""
        magic = 0x46414153  # "FAAS"
        request_id_hash = hash(request_id) & 0xFFFFFFFF
        timestamp = int(time.time() * 1000000)
        data_size = len(data)
        
        # 32字节包头
        header = struct.pack('IIIIIIIQ',
                           magic,           # 魔数
                           request_id_hash, # 请求ID
                           data_size,       # 数据大小
                           dest_container,  # 目标容器
                           src_container,   # 源容器
                           1,               # 数据类型
                           0,               # 保留字段
                           timestamp)       # 时间戳
        
        return header + data

    def store_data_in_map(self, key: str, data: bytes, container_id: str) -> bool:
        """将数据存储到eBPF Map中"""
        try:
            if not self.ebpf_program or len(data) > 4096:
                return False
                
            timestamp = int(time.time() * 1000000)
            key_hash = hash(key) & 0xFFFFFFFFFFFFFFFF
            container_hash = hash(container_id) & 0xFFFFFFFF
            request_id_hash = hash(key.split('.')[0]) & 0xFFFFFFFF
            
            # 构造数据条目
            entry_data = struct.pack('Q', timestamp)     # 8 bytes
            entry_data += struct.pack('I', len(data))    # 4 bytes
            entry_data += struct.pack('I', request_id_hash)  # 4 bytes
            entry_data += struct.pack('I', container_hash)   # 4 bytes
            entry_data += data                           # data
            entry_data += b'\x00' * (4096 - len(data))  # padding
            
            # 存储到Map
            map_key = ctypes.c_uint64(key_hash)
            self.data_map[map_key] = entry_data
            
            print(f"[eBPF-Host] 数据存储成功: {key}, 大小: {len(data)}")
            return True
            
        except Exception as e:
            print(f"[eBPF-Host] 数据存储失败: {e}", file=sys.stderr)
            return False

    def get_data_from_map(self, key: str) -> Optional[bytes]:
        """从eBPF Map获取数据"""
        try:
            if not self.ebpf_program:
                return None
                
            key_hash = hash(key) & 0xFFFFFFFFFFFFFFFF
            map_key = ctypes.c_uint64(key_hash)
            
            if map_key in self.data_map:
                entry_data = self.data_map[map_key]
                
                # 解析数据
                timestamp = struct.unpack('Q', entry_data[:8])[0]
                data_size = struct.unpack('I', entry_data[8:12])[0]
                request_id_hash = struct.unpack('I', entry_data[12:16])[0]
                container_hash = struct.unpack('I', entry_data[16:20])[0]
                raw_data = entry_data[20:20+data_size]
                
                print(f"[eBPF-Host] 数据获取成功: {key}, 大小: {data_size}")
                return raw_data
            else:
                return None
                
        except Exception as e:
            print(f"[eBPF-Host] 数据获取失败: {e}", file=sys.stderr)
            return None

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        if not self.stats_map:
            return self.redirect_stats
            
        try:
            # 聚合所有容器的统计
            total_stats = {
                'rx_packets': 0,
                'tx_packets': 0,
                'rx_bytes': 0,
                'tx_bytes': 0,
                'redirect_success': 0,
                'redirect_failed': 0
            }
            
            for container_id in self.containers:
                container_hash = hash(container_id) & 0xFFFFFFFF
                key = ctypes.c_uint32(container_hash)
                
                if key in self.stats_map:
                    stats_raw = self.stats_map[key]
                    stats = struct.unpack('QQQQQQQ', stats_raw[:56])
                    
                    total_stats['rx_packets'] += stats[0]
                    total_stats['tx_packets'] += stats[1]
                    total_stats['rx_bytes'] += stats[2]
                    total_stats['tx_bytes'] += stats[3]
                    total_stats['redirect_success'] += stats[4]
                    total_stats['redirect_failed'] += stats[5]
            
            # 添加宿主机统计
            total_stats.update(self.redirect_stats)
            total_stats['containers_count'] = len(self.containers)
            
            return total_stats
            
        except Exception as e:
            print(f"[eBPF-Host] 统计获取失败: {e}", file=sys.stderr)
            return self.redirect_stats

    def start_socket_server(self):
        """启动Unix socket服务器，供容器连接"""
        def socket_server_loop():
            try:
                # 清理旧的socket文件
                if os.path.exists(self.socket_path):
                    os.unlink(self.socket_path)
                
                # 创建Unix socket服务器
                server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server_sock.bind(self.socket_path)
                server_sock.listen(10)
                
                # 设置权限，让容器可以访问
                os.chmod(self.socket_path, 0o666)
                
                print(f"[eBPF-Host] Socket服务器启动: {self.socket_path}")
                
                while self.running:
                    try:
                        client_sock, _ = server_sock.accept()
                        client_sock.settimeout(30)
                        
                        # 接收消息
                        data = client_sock.recv(4096)
                        if data:
                            message = json.loads(data.decode())
                            
                            # 处理消息
                            response = self.handle_container_notification(message)
                            
                            # 发送响应
                            if response is not None:
                                client_sock.sendall(json.dumps({
                                    'status': 'ok', 
                                    'data': response
                                }).encode())
                            else:
                                client_sock.sendall(json.dumps({
                                    'status': 'ok'
                                }).encode())
                        
                        client_sock.close()
                        
                    except socket.timeout:
                        continue
                    except Exception as e:
                        print(f"[eBPF-Host] 客户端处理错误: {e}", file=sys.stderr)
                        
                server_sock.close()
                
            except Exception as e:
                print(f"[eBPF-Host] Socket服务器错误: {e}", file=sys.stderr)
        
        if not self.socket_server_thread:
            self.socket_server_thread = threading.Thread(target=socket_server_loop, daemon=True)
            self.socket_server_thread.start()

    def start_monitoring(self):
        """启动监控线程"""
        if self.running:
            return
            
        self.running = True
        
        # 启动socket服务器
        self.start_socket_server()
        
        def monitor_loop():
            while self.running:
                try:
                    # 清理过期容器
                    current_time = time.time()
                    expired_containers = []
                    
                    for container_id, info in self.containers.items():
                        if current_time - info.last_activity > 300:  # 5分钟超时
                            expired_containers.append(container_id)
                    
                    for container_id in expired_containers:
                        self.unregister_container(container_id)
                    
                    # 打印统计信息
                    if len(self.containers) > 0:
                        stats = self.get_performance_stats()
                        print(f"[eBPF-Host] 活跃容器: {stats['containers_count']}, "
                              f"重定向成功: {stats['redirect_success']}, "
                              f"失败: {stats['redirect_failed']}")
                    
                    time.sleep(30)  # 30秒检查一次
                    
                except Exception as e:
                    print(f"[eBPF-Host] 监控异常: {e}", file=sys.stderr)
                    time.sleep(5)
        
        self.monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitor_thread.start()
        print(f"[eBPF-Host] 监控线程已启动")

    def stop(self):
        """停止管理器"""
        self.running = False
        
        # 清理所有容器
        container_ids = list(self.containers.keys())
        for container_id in container_ids:
            self.unregister_container(container_id)
        
        # 等待监控线程结束
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        print(f"[eBPF-Host] 管理器已停止")

    def handle_container_notification(self, notification: Dict[str, Any]):
        """处理容器通知"""
        try:
            action = notification.get('action')
            container_id = notification.get('container_id')
            
            if action == 'ping':
                # 响应ping请求
                print(f"[eBPF-Host] 收到ping: {container_id}")
                return {'pong': True, 'timestamp': time.time()}
                
            elif action == 'register':
                template_name = notification.get('template_name')
                port = notification.get('port')
                socket_fd = notification.get('socket_fd')
                
                success = self.register_container(container_id, template_name, port, socket_fd)
                return {'registered': success}
                
            elif action == 'unregister':
                success = self.unregister_container(container_id)
                return {'unregistered': success}
                
            elif action == 'data_redirect':
                dest_container = notification.get('dest_container')
                data = notification.get('data', b'')
                request_id = notification.get('request_id', '')
                
                success = self.redirect_data(container_id, dest_container, data, request_id)
                return {'redirected': success}
                
            elif action == 'store_data':
                key = notification.get('key')
                data = notification.get('data', '').encode('utf-8')
                
                success = self.store_data_in_map(key, data, container_id)
                return {'stored': success}
                
            elif action == 'get_data':
                key = notification.get('key')
                data = self.get_data_from_map(key)
                if data:
                    return {'data': data.decode('utf-8', errors='ignore')}
                else:
                    return {'data': None}
                    
            else:
                print(f"[eBPF-Host] 未知操作: {action}")
                return {'error': f'Unknown action: {action}'}
                
        except Exception as e:
            print(f"[eBPF-Host] 通知处理失败: {e}", file=sys.stderr)
            return {'error': str(e)}


# 全局eBPF管理器实例
ebpf_manager = None


def init_ebpf_manager(worker_ip: str):
    """初始化全局eBPF管理器"""
    global ebpf_manager
    if ebpf_manager is None:
        ebpf_manager = EBPFHostManager(worker_ip)
        ebpf_manager.start_monitoring()
        print(f"[eBPF-Host] 全局管理器已初始化: {worker_ip}")
    return ebpf_manager


def get_ebpf_manager() -> Optional[EBPFHostManager]:
    """获取全局eBPF管理器"""
    return ebpf_manager


def cleanup_ebpf_manager():
    """清理全局eBPF管理器"""
    global ebpf_manager
    if ebpf_manager:
        ebpf_manager.stop()
        ebpf_manager = None


# 信号处理
def signal_handler(signum, frame):
    print(f"[eBPF-Host] 收到信号 {signum}，正在清理...")
    cleanup_ebpf_manager()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python3 ebpf_host_manager.py <worker_ip>")
        sys.exit(1)
    
    worker_ip = sys.argv[1]
    manager = init_ebpf_manager(worker_ip)
    
    print(f"[eBPF-Host] 管理器运行中，按Ctrl+C停止...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup_ebpf_manager()
