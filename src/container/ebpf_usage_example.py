#!/usr/bin/env python3
"""
FaaSFlow eBPF数据传输使用示例

展示如何使用eBPF优化的数据接收功能
"""

import json
import sys
import time

# 模拟数据生产者，将数据发送到eBPF Map
def simulate_data_producer(store):
    """模拟数据生产者"""
    test_data = {
        "test_key_1.json": {"message": "Hello from eBPF!", "timestamp": time.time()},
        "test_key_2": b"Binary data from eBPF",
        "test_key_3.json": {"array": [1, 2, 3, 4, 5], "nested": {"key": "value"}}
    }
    
    for key, data in test_data.items():
        success = store.store_to_ebpf(key, data, "json" if key.endswith(".json") else "octet")
        print(f"存储 {key}: {'成功' if success else '失败'}")

# 模拟数据消费者，从eBPF Map读取数据
def simulate_data_consumer(store):
    """模拟数据消费者"""
    test_keys = ["test_key_1.json", "test_key_2", "test_key_3.json", "nonexistent_key"]
    
    for key in test_keys:
        print(f"\n尝试获取: {key}")
        try:
            # 模拟eBPF数据就绪信号
            data_infos = {
                'datatype': 'ebpf_data_ready',
                'db_key': key,
                'ebpf_map_id': 0
            }
            
            data = store.fetch_input_data(key, data_infos)
            print(f"成功获取: {key}")
            print(f"数据类型: {type(data)}")
            if isinstance(data, dict):
                print(f"内容: {json.dumps(data, indent=2)}")
            elif isinstance(data, bytes):
                print(f"二进制数据长度: {len(data)} bytes")
            else:
                print(f"内容: {data}")
                
        except Exception as e:
            print(f"获取失败: {e}")

# 性能测试
def performance_test(store):
    """eBPF性能测试"""
    print("\n=== eBPF性能测试 ===")
    
    # 测试数据
    test_data = {"performance": "test", "data": "x" * 1000}  # 1KB数据
    key = "perf_test.json"
    
    # 存储性能测试
    start_time = time.time()
    for i in range(100):
        store.store_to_ebpf(f"{key}_{i}", test_data, "json")
    store_time = time.time() - start_time
    
    print(f"存储100个1KB数据耗时: {store_time:.4f}秒")
    print(f"平均存储延迟: {store_time/100*1000:.2f}毫秒")
    
    # 读取性能测试
    start_time = time.time()
    for i in range(100):
        data_infos = {
            'datatype': 'ebpf_data_ready',
            'db_key': f"{key}_{i}",
            'ebpf_map_id': 0
        }
        try:
            store.fetch_input_data(f"{key}_{i}", data_infos)
        except:
            pass
    read_time = time.time() - start_time
    
    print(f"读取100个1KB数据耗时: {read_time:.4f}秒")
    print(f"平均读取延迟: {read_time/100*1000:.2f}毫秒")

if __name__ == "__main__":
    print("FaaSFlow eBPF数据传输示例")
    print("=" * 40)
    
    # 注意：这里需要实际的Store实例
    # 在实际使用中，Store会通过容器初始化
    print("注意：此示例需要在实际的FaaSFlow容器环境中运行")
    print("请确保：")
    print("1. 安装了BCC库 (pip install bcc)")
    print("2. 具有root权限")
    print("3. 内核支持eBPF (Linux 4.4+)")
