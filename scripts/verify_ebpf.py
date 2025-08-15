#!/usr/bin/env python3
"""
验证eBPF和BCC安装的脚本
"""

import sys
import os
import subprocess
import platform

def check_python_version():
    """检查Python版本"""
    version = sys.version_info
    print(f"✓ Python版本: {version.major}.{version.minor}.{version.micro}")
    if version < (3, 6):
        print("❌ 警告: Python版本过低，建议使用3.6+")
        return False
    return True

def check_kernel_version():
    """检查Linux内核版本"""
    try:
        kernel_version = platform.release()
        print(f"✓ Linux内核版本: {kernel_version}")
        
        # 简单检查内核版本是否 >= 4.4
        major, minor = map(int, kernel_version.split('.')[:2])
        if (major, minor) < (4, 4):
            print("❌ 警告: 内核版本过低，eBPF功能可能不完整")
            return False
        return True
    except Exception as e:
        print(f"❌ 无法检查内核版本: {e}")
        return False

def check_bcc_import():
    """检查BCC库导入"""
    try:
        from bcc import BPF
        print("✓ BCC库导入成功")
        return True
    except ImportError as e:
        print(f"❌ BCC库导入失败: {e}")
        print("   请运行: pip install bcc")
        return False

def check_system_packages():
    """检查系统包"""
    packages = {
        'linux-headers': ['/usr/src/linux-headers-*', '/lib/modules/*/build'],
        'bpfcc-tools': ['/usr/share/bcc/tools', '/usr/bin/bpftrace'],
        'libbpf': ['/usr/lib/*/libbpf.so*', '/usr/lib/libbpf.so*']
    }
    
    for package, paths in packages.items():
        found = False
        for path_pattern in paths:
            if '*' in path_pattern:
                # 使用glob模式匹配
                import glob
                if glob.glob(path_pattern):
                    found = True
                    break
            else:
                if os.path.exists(path_pattern):
                    found = True
                    break
        
        if found:
            print(f"✓ {package} 已安装")
        else:
            print(f"❌ {package} 未找到")

def test_simple_ebpf():
    """测试简单的eBPF程序编译"""
    try:
        from bcc import BPF
        
        # 简单的eBPF程序
        program = """
        int hello(void *ctx) {
            bpf_trace_printk("Hello from eBPF!\\n");
            return 0;
        }
        """
        
        b = BPF(text=program)
        print("✓ 简单eBPF程序编译成功")
        return True
    except Exception as e:
        print(f"❌ eBPF程序编译失败: {e}")
        return False

def check_permissions():
    """检查权限"""
    if os.geteuid() == 0:
        print("✓ 当前用户为root")
        return True
    
    # 检查capabilities
    try:
        result = subprocess.run(['getcap', sys.executable], 
                              capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            print(f"✓ Python具有capabilities: {result.stdout.strip()}")
            return True
        else:
            print("❌ 没有root权限且未配置capabilities")
            print("   请运行: sudo python3 此脚本")
            print("   或配置: sudo setcap 'CAP_SYS_ADMIN+ep CAP_NET_ADMIN+ep' " + sys.executable)
            return False
    except FileNotFoundError:
        print("❌ getcap命令未找到，无法检查capabilities")
        return False

def main():
    """主函数"""
    print("=== FaaSFlow eBPF环境验证 ===\n")
    
    results = []
    
    print("1. 系统环境检查:")
    results.append(check_python_version())
    results.append(check_kernel_version())
    
    print("\n2. 系统包检查:")
    check_system_packages()
    
    print("\n3. Python包检查:")
    results.append(check_bcc_import())
    
    print("\n4. 权限检查:")
    results.append(check_permissions())
    
    print("\n5. eBPF功能测试:")
    if all(results):
        results.append(test_simple_ebpf())
    else:
        print("❌ 跳过eBPF测试 (前置条件不满足)")
        results.append(False)
    
    print("\n=== 总结 ===")
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print("🎉 所有检查通过! eBPF环境配置正确")
        sys.exit(0)
    else:
        print(f"⚠️  {passed}/{total} 项检查通过，需要修复上述问题")
        print("\n📖 详细安装指南请参考: docs/EBPF_SETUP.md")
        sys.exit(1)

if __name__ == "__main__":
    main()
