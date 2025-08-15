#include <linux/bpf.h>
#include <linux/ptrace.h>
#include <bpf/bpf_helpers.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <linux/tcp.h>

#define MAX_CONTAINERS 1000    // 最大容器数量
#define MAX_SOCK_MAP_ENTRIES 65535
#define MAX_DATA_SIZE 4096     // 最大数据块大小
#define FAASFLOW_MAGIC 0x46414153  // "FAAS" magic number

/* FaaSFlow数据包头结构 */
struct faasflow_header {
    __u32 magic;           // 魔数标识
    __u32 request_id_hash; // 请求ID哈希
    __u32 data_size;       // 数据大小
    __u32 dest_container;  // 目标容器ID
    __u32 src_container;   // 源容器ID
    __u32 data_type;       // 数据类型(json=1, octet=2)
    __u64 timestamp;       // 时间戳
};

/* 性能统计结构 */
struct perf_stats {
    __u64 rx_packets;
    __u64 tx_packets;
    __u64 rx_bytes;
    __u64 tx_bytes;
    __u64 redirect_success;
    __u64 redirect_failed;
    __u64 last_timestamp;
};

/* 容器路由信息 */
struct container_route {
    __u32 container_id;
    __u32 local_available;  // 1=本地可用, 0=需要转发
    __u32 gateway_id;       // 网关容器ID
};

/* Maps定义 */
struct bpf_map_def SEC("maps") container_stats_map = {
    .type        = BPF_MAP_TYPE_PERCPU_ARRAY,
    .key_size    = sizeof(__u32),
    .value_size  = sizeof(struct perf_stats),
    .max_entries = MAX_CONTAINERS,
};

struct bpf_map_def SEC("maps") faasflow_sock_map = {
    .type        = BPF_MAP_TYPE_SOCKMAP,
    .key_size    = sizeof(__u32),
    .value_size  = sizeof(__u32),
    .max_entries = MAX_SOCK_MAP_ENTRIES,
    .map_flags   = 0,
};

struct bpf_map_def SEC("maps") container_route_map = {
    .type        = BPF_MAP_TYPE_HASH,
    .key_size    = sizeof(__u32),
    .value_size  = sizeof(struct container_route),
    .max_entries = MAX_CONTAINERS,
};

/* 数据缓存Map */
struct bpf_map_def SEC("maps") data_cache_map = {
    .type        = BPF_MAP_TYPE_LRU_HASH,
    .key_size    = sizeof(__u64),  // timestamp作为key
    .value_size  = MAX_DATA_SIZE,
    .max_entries = 512,            // 最多缓存512个数据块
};

/* RingBuf用于事件通知 */
struct bpf_map_def SEC("maps") events_ringbuf = {
    .type        = BPF_MAP_TYPE_RINGBUF,
    .max_entries = 1 << 20,  // 1MB
};

/* 事件结构 */
struct data_event {
    __u32 event_type;      // 1=data_received, 2=data_forwarded, 3=error
    __u32 container_id;
    __u32 request_id_hash;
    __u32 data_size;
    __u64 timestamp;
    char data_key[64];     // 数据键名
};

/* 解析FaaSFlow数据包头 */
static inline struct faasflow_header* parse_faasflow_header(void *data, void *data_end)
{
    struct faasflow_header *hdr = data;
    
    if ((void *)(hdr + 1) > data_end)
        return NULL;
        
    if (hdr->magic != FAASFLOW_MAGIC)
        return NULL;
        
    return hdr;
}

/* 更新性能统计 */
static inline void update_stats(__u32 container_id, __u64 bytes, __u32 is_tx)
{
    struct perf_stats *stats = bpf_map_lookup_elem(&container_stats_map, &container_id);
    if (stats) {
        if (is_tx) {
            stats->tx_packets++;
            stats->tx_bytes += bytes;
        } else {
            stats->rx_packets++;
            stats->rx_bytes += bytes;
        }
        stats->last_timestamp = bpf_ktime_get_ns();
    }
}

/* 发送事件通知 */
static inline void send_event(__u32 event_type, __u32 container_id, 
                             __u32 request_id_hash, __u32 data_size, 
                             __u64 timestamp, const char *data_key)
{
    struct data_event *event = bpf_ringbuf_reserve(&events_ringbuf, sizeof(*event), 0);
    if (event) {
        event->event_type = event_type;
        event->container_id = container_id;
        event->request_id_hash = request_id_hash;
        event->data_size = data_size;
        event->timestamp = timestamp;
        
        // 复制数据键名
        #pragma unroll
        for (int i = 0; i < 64; i++) {
            if (i < 63 && data_key && data_key[i]) {
                event->data_key[i] = data_key[i];
            } else {
                event->data_key[i] = '\0';
                break;
            }
        }
        
        bpf_ringbuf_submit(event, 0);
    }
}

/* SK_MSG程序：处理FaaSFlow消息重定向 */
SEC("sk_msg")
int faasflow_sk_msg_prog(struct sk_msg_md *msg)
{
    void *data = (void *)(long)msg->data;
    void *data_end = (void *)(long)msg->data_end;
    
    bpf_printk("[FaaSFlow SK_MSG] Processing message size: %d", msg->size);
    
    // 解析FaaSFlow头
    struct faasflow_header *hdr = parse_faasflow_header(data, data_end);
    if (!hdr) {
        bpf_printk("[FaaSFlow SK_MSG] Invalid FaaSFlow header");
        return SK_DROP;
    }
    
    __u32 dest_container = hdr->dest_container;
    __u32 src_container = hdr->src_container;
    
    bpf_printk("[FaaSFlow SK_MSG] Redirect from Container#%d to Container#%d", 
               src_container, dest_container);
    
    // 查找目标容器路由信息
    struct container_route *route = bpf_map_lookup_elem(&container_route_map, &dest_container);
    if (!route) {
        bpf_printk("[FaaSFlow SK_MSG] No route found for Container#%d", dest_container);
        
        // 转发到网关 (容器ID 0)
        __u32 gateway_id = 0;
        int ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, gateway_id, BPF_F_INGRESS);
        
        if (ret == SK_PASS) {
            update_stats(gateway_id, msg->size, 1);
            send_event(2, dest_container, hdr->request_id_hash, hdr->data_size, 
                      hdr->timestamp, "gateway_forward");
        }
        
        return ret;
    }
    
    // 如果本地可用，直接重定向
    if (route->local_available) {
        int ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, dest_container, BPF_F_INGRESS);
        
        if (ret == SK_PASS) {
            update_stats(dest_container, msg->size, 0);
            update_stats(src_container, msg->size, 1);
            
            // 缓存数据到Map中
            if (hdr->data_size <= MAX_DATA_SIZE) {
                void *payload = data + sizeof(struct faasflow_header);
                if (payload + hdr->data_size <= data_end) {
                    bpf_map_update_elem(&data_cache_map, &hdr->timestamp, payload, BPF_ANY);
                }
            }
            
            send_event(1, dest_container, hdr->request_id_hash, hdr->data_size, 
                      hdr->timestamp, "local_delivery");
            
            bpf_printk("[FaaSFlow SK_MSG] Successfully redirected to Container#%d", dest_container);
        } else {
            bpf_printk("[FaaSFlow SK_MSG] Failed to redirect to Container#%d", dest_container);
            
            // 重定向失败，转发到网关
            __u32 gateway_id = route->gateway_id;
            ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, gateway_id, BPF_F_INGRESS);
            
            if (ret == SK_PASS) {
                update_stats(gateway_id, msg->size, 1);
                send_event(2, dest_container, hdr->request_id_hash, hdr->data_size, 
                          hdr->timestamp, "gateway_fallback");
            }
        }
        
        return ret;
    } else {
        // 目标不在本地，转发到网关
        __u32 gateway_id = route->gateway_id;
        int ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, gateway_id, BPF_F_INGRESS);
        
        if (ret == SK_PASS) {
            update_stats(gateway_id, msg->size, 1);
            send_event(2, dest_container, hdr->request_id_hash, hdr->data_size, 
                      hdr->timestamp, "remote_forward");
            
            bpf_printk("[FaaSFlow SK_MSG] Forwarded to Gateway for Container#%d", dest_container);
        }
        
        return ret;
    }
}

/* Socket操作优化程序 */
SEC("sockops")
int faasflow_sockops_prog(struct bpf_sock_ops *skops)
{
    __u32 family = skops->family;
    __u32 op = skops->op;
    
    switch (op) {
    case BPF_SOCK_OPS_PASSIVE_ESTABLISHED_CB:
    case BPF_SOCK_OPS_ACTIVE_ESTABLISHED_CB:
        bpf_printk("[FaaSFlow SockOps] Connection established");
        
        // 优化TCP参数
        int nodelay = 1;
        bpf_setsockopt(skops, IPPROTO_TCP, TCP_NODELAY, &nodelay, sizeof(nodelay));
        
        // 设置socket缓冲区大小
        int buf_size = 65536;
        bpf_setsockopt(skops, SOL_SOCKET, SO_RCVBUF, &buf_size, sizeof(buf_size));
        bpf_setsockopt(skops, SOL_SOCKET, SO_SNDBUF, &buf_size, sizeof(buf_size));
        
        break;
        
    case BPF_SOCK_OPS_TCP_CONNECT_CB:
        bpf_printk("[FaaSFlow SockOps] TCP connect callback");
        break;
        
    default:
        break;
    }
    
    return 1;
}

char _license[] SEC("license") = "GPL";
