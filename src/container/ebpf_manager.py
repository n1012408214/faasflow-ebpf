#!/usr/bin/env python3
"""
FaaSFlow eBPF管理工具
提供eBPF程序的加载、卸载和监控功能
"""

import os
import sys
import time
import json
import argparse
from typing import Dict, List, Optional

try:
    from bcc import BPF
    EBPF_AVAILABLE = True
except ImportError:
    EBPF_AVAILABLE = False
    print("警告: BCC库未安装，请安装: pip install bcc")

class FaaSFloweBPFManager:
    """FaaSFlow eBPF程序管理器"""
    
    def __init__(self):
        self.ebpf_program = None
        self.sock_map = None
        self.route_map = None
        self.stats_map = None
        self.data_map = None
        
    def load_program(self, program_file: str = None) -> bool:
        """加载eBPF程序"""
        if not EBPF_AVAILABLE:
            print("❌ BCC库不可用，无法加载eBPF程序")
            return False
            
        try:
            if program_file and os.path.exists(program_file):
                with open(program_file, 'r') as f:
                    ebpf_code = f.read()
                print(f"📄 从文件加载eBPF程序: {program_file}")
            else:
                # 使用内嵌程序
                ebpf_code = self._get_embedded_program()
                print("📄 使用内嵌eBPF程序")
            
            # 编译程序
            self.ebpf_program = BPF(text=ebpf_code)
            
            # 获取Maps
            self.sock_map = self.ebpf_program.get_table("faasflow_sock_map")
            self.route_map = self.ebpf_program.get_table("container_route_map")
            self.stats_map = self.ebpf_program.get_table("container_stats_map")
            self.data_map = self.ebpf_program.get_table("data_cache_map")
            
            print("✅ eBPF程序加载成功")
            return True
            
        except Exception as e:
            print(f"❌ eBPF程序加载失败: {e}")
            return False
    
    def attach_programs(self, interface: str = "lo") -> bool:
        """附加eBPF程序到网络接口"""
        if not self.ebpf_program:
            print("❌ 请先加载eBPF程序")
            return False
            
        try:
            # 加载SK_MSG程序
            msg_prog_fd = self.ebpf_program.load_func("faasflow_sk_msg_prog", BPF.SK_MSG)
            print(f"🔗 SK_MSG程序已加载, FD: {msg_prog_fd}")
            
            # 加载SockOps程序
            sockops_prog_fd = self.ebpf_program.load_func("faasflow_sockops_prog", BPF.SOCK_OPS)
            print(f"🔗 SockOps程序已加载, FD: {sockops_prog_fd}")
            
            print("✅ eBPF程序附加成功")
            return True
            
        except Exception as e:
            print(f"❌ eBPF程序附加失败: {e}")
            return False
    
    def register_container(self, container_id: int, template_name: str, 
                          local_available: bool = True, gateway_id: int = 0) -> bool:
        """注册容器到路由表"""
        if not self.route_map:
            print("❌ 路由Map不可用")
            return False
            
        try:
            import ctypes
            import struct
            
            route_key = ctypes.c_uint32(container_id)
            route_value = struct.pack('III', container_id, 
                                    1 if local_available else 0, gateway_id)
            
            self.route_map[route_key] = route_value
            print(f"📝 容器注册成功: ID={container_id}, Template={template_name}")
            return True
            
        except Exception as e:
            print(f"❌ 容器注册失败: {e}")
            return False
    
    def register_socket(self, container_id: int, socket_fd: int) -> bool:
        """注册Socket到Socket Map"""
        if not self.sock_map:
            print("❌ Socket Map不可用")
            return False
            
        try:
            import ctypes
            
            key = ctypes.c_uint32(container_id)
            self.sock_map[key] = ctypes.c_int(socket_fd)
            print(f"🔌 Socket注册成功: Container={container_id}, FD={socket_fd}")
            return True
            
        except Exception as e:
            print(f"❌ Socket注册失败: {e}")
            return False
    
    def get_statistics(self) -> Dict:
        """获取性能统计信息"""
        if not self.stats_map:
            return {}
            
        stats = {}
        try:
            import ctypes
            import struct
            
            for key, value in self.stats_map.items():
                container_id = key.value
                stats_data = struct.unpack('QQQQQQQ', value[:56])
                
                stats[container_id] = {
                    'rx_packets': stats_data[0],
                    'tx_packets': stats_data[1],
                    'rx_bytes': stats_data[2],
                    'tx_bytes': stats_data[3],
                    'redirect_success': stats_data[4],
                    'redirect_failed': stats_data[5],
                    'last_timestamp': stats_data[6]
                }
                
        except Exception as e:
            print(f"❌ 获取统计信息失败: {e}")
            
        return stats
    
    def print_statistics(self):
        """打印性能统计信息"""
        stats = self.get_statistics()
        
        if not stats:
            print("📊 暂无统计数据")
            return
            
        print("\n📊 eBPF性能统计:")
        print("=" * 80)
        print(f"{'容器ID':<10} {'接收包':<10} {'发送包':<10} {'接收字节':<12} {'发送字节':<12} {'重定向成功':<10} {'重定向失败':<10}")
        print("-" * 80)
        
        for container_id, data in stats.items():
            print(f"{container_id:<10} {data['rx_packets']:<10} {data['tx_packets']:<10} "
                  f"{data['rx_bytes']:<12} {data['tx_bytes']:<12} "
                  f"{data['redirect_success']:<10} {data['redirect_failed']:<10}")
    
    def list_routes(self):
        """列出路由表"""
        if not self.route_map:
            print("❌ 路由Map不可用")
            return
            
        print("\n🗺️  容器路由表:")
        print("=" * 50)
        print(f"{'容器ID':<10} {'本地可用':<10} {'网关ID':<10}")
        print("-" * 50)
        
        try:
            import struct
            
            for key, value in self.route_map.items():
                container_id = key.value
                route_data = struct.unpack('III', value)
                local_available = "是" if route_data[1] else "否"
                gateway_id = route_data[2]
                
                print(f"{container_id:<10} {local_available:<10} {gateway_id:<10}")
                
        except Exception as e:
            print(f"❌ 读取路由表失败: {e}")
    
    def list_sockets(self):
        """列出Socket Map"""
        if not self.sock_map:
            print("❌ Socket Map不可用")
            return
            
        print("\n🔌 Socket映射表:")
        print("=" * 30)
        print(f"{'容器ID':<10} {'Socket FD':<10}")
        print("-" * 30)
        
        try:
            for key, value in self.sock_map.items():
                container_id = key.value
                socket_fd = value.value
                print(f"{container_id:<10} {socket_fd:<10}")
                
        except Exception as e:
            print(f"❌ 读取Socket Map失败: {e}")
    
    def monitor(self, interval: int = 5):
        """实时监控eBPF性能"""
        print(f"🔍 开始监控eBPF性能 (间隔: {interval}秒)")
        print("按 Ctrl+C 停止监控")
        
        try:
            while True:
                os.system('clear')
                print(f"FaaSFlow eBPF 实时监控 - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                self.print_statistics()
                self.list_routes()
                self.list_sockets()
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n🛑 监控已停止")
    
    def cleanup(self):
        """清理eBPF资源"""
        try:
            if self.ebpf_program:
                # 清理Maps
                if self.sock_map:
                    self.sock_map.clear()
                if self.route_map:
                    self.route_map.clear()
                    
                print("🧹 eBPF资源清理完成")
                
        except Exception as e:
            print(f"❌ 清理失败: {e}")
    
    def _get_embedded_program(self) -> str:
        """获取内嵌的eBPF程序代码"""
        return """
        #include <uapi/linux/ptrace.h>
        #include <linux/sched.h>
        #include <linux/fs.h>

        BPF_SOCKMAP(faasflow_sock_map, 65535);
        BPF_HASH(container_route_map, u32, struct container_route, 1000);
        BPF_PERCPU_ARRAY(container_stats_map, struct perf_stats, 1000);
        BPF_HASH(data_cache_map, u64, struct data_entry, 512);

        struct container_route {
            u32 container_id;
            u32 local_available;
            u32 gateway_id;
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

        struct data_entry {
            u64 timestamp;
            u32 data_size;
            u32 request_id_hash;
            u32 container_id;
            char data[4096];
        };

        int faasflow_sk_msg_prog(struct sk_msg_md *msg) {
            u32 dest_container = 1;
            bpf_trace_printk("FaaSFlow SK_MSG: size=%d\\n", msg->size);
            
            int ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, dest_container, BPF_F_INGRESS);
            if (ret != SK_PASS) {
                u32 gateway_id = 0;
                ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, gateway_id, BPF_F_INGRESS);
            }
            return ret;
        }

        int faasflow_sockops_prog(struct bpf_sock_ops *skops) {
            switch (skops->op) {
            case BPF_SOCK_OPS_PASSIVE_ESTABLISHED_CB:
            case BPF_SOCK_OPS_ACTIVE_ESTABLISHED_CB:
                {
                    int nodelay = 1;
                    bpf_setsockopt(skops, IPPROTO_TCP, TCP_NODELAY, &nodelay, sizeof(nodelay));
                    
                    int buf_size = 65536;
                    bpf_setsockopt(skops, SOL_SOCKET, SO_RCVBUF, &buf_size, sizeof(buf_size));
                    bpf_setsockopt(skops, SOL_SOCKET, SO_SNDBUF, &buf_size, sizeof(buf_size));
                }
                break;
            }
            return 1;
        }
        """

def main():
    parser = argparse.ArgumentParser(description='FaaSFlow eBPF管理工具')
    parser.add_argument('--load', '-l', action='store_true', help='加载eBPF程序')
    parser.add_argument('--attach', '-a', action='store_true', help='附加eBPF程序')
    parser.add_argument('--monitor', '-m', action='store_true', help='监控eBPF性能')
    parser.add_argument('--stats', '-s', action='store_true', help='显示统计信息')
    parser.add_argument('--routes', '-r', action='store_true', help='显示路由表')
    parser.add_argument('--sockets', '-k', action='store_true', help='显示Socket表')
    parser.add_argument('--cleanup', '-c', action='store_true', help='清理eBPF资源')
    parser.add_argument('--program', '-p', help='eBPF程序文件路径')
    parser.add_argument('--interval', '-i', type=int, default=5, help='监控间隔(秒)')
    
    args = parser.parse_args()
    
    if len(sys.argv) == 1:
        parser.print_help()
        return
    
    manager = FaaSFloweBPFManager()
    
    try:
        if args.load:
            manager.load_program(args.program)
            
        if args.attach:
            manager.attach_programs()
            
        if args.stats:
            manager.print_statistics()
            
        if args.routes:
            manager.list_routes()
            
        if args.sockets:
            manager.list_sockets()
            
        if args.monitor:
            manager.monitor(args.interval)
            
        if args.cleanup:
            manager.cleanup()
            
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
    except Exception as e:
        print(f"❌ 执行失败: {e}")
    finally:
        manager.cleanup()

if __name__ == "__main__":
    main()
