import json
import math
import os.path
import socket
import sys
import time
import threading
import couchdb
import redis
import requests
import container_config
import ctypes
import mmap
import struct
try:
    from bcc import BPF
    EBPF_AVAILABLE = True
except ImportError:
    EBPF_AVAILABLE = False
    print("警告: BCC库未安装，eBPF功能将被禁用", file=sys.stderr)

host_url = 'http://172.17.0.1:8000/{}'
disk_reader_url = 'http://172.17.0.1:8001/{}'
db_threshold = 1024 * 16  # >16KB data will be sent to remote db
prefetch_path = '/proxy/mnt'


# Todo
#  Need a translator between function's predefined key_name and workflow's key_name!

class Store:
    def __init__(self, request_id, workflow_name, template_name, templates_infos, block_name, block_inputs: dict,
                 block_infos, chunk_size, store_queue, db, latency_db, redis_db):
        # self.cnt = 0
        self.db = db
        self.latency_db = latency_db
        self.redis = redis_db
        self.request_id = request_id
        self.workflow_name = workflow_name
        self.template_name = template_name
        self.templates_infos = templates_infos
        self.block_name = block_name
        self.block_inputs = block_inputs
        self.block_infos = block_infos
        self.chunk_size = chunk_size
        self.store_queue = store_queue
        self.block_outputs = {}
        self.outputs_type = {}
        self.fetch_dict = {}
        self.switch_status = 'NA'
        self.bypass_size = 0
        if self.block_infos['type'] == 'SWITCH':
            self.switch_status = 'PENDING'
        self.switch_branch = None
        self.block_serial = None
        for k, v in self.block_inputs.items():
            if 'output_type' in v and v['output_type'] == 'FOREACH':
                self.block_serial = v['serial_num']
        self.posting_threads = []
        self.outputs_serial = {}
        
        # eBPF初始化
        self.ebpf_program = None
        self.ebpf_data_map = None
        self.init_ebpf()

    def fetch_scalability_config(self):
        try:
            data = self.db['scalability_config']
        except Exception:
            return None
        return data

    def post_to_disk(self, key, val, datatype, serial_num):
        assert datatype == 'json' or datatype == 'octet'
        filename = self.request_id + '.' + self.generate_db_key(key, serial_num)
        if datatype == 'octet':
            filepath = os.path.join(prefetch_path, filename)
            with open(filepath, 'wb') as f:
                f.write(val)
        elif datatype == 'json':
            filepath = os.path.join(prefetch_path, filename + '.json')
            with open(filepath, 'w') as f:
                f.write(val)
        else:
            raise Exception

    def generate_db_key(self, key, serial_num):
        return self.request_id + '.' + self.template_name + '.' + self.block_name + '.out.' + key + '.' + str(
            serial_num)

    def put_bigdata(self, key, val, datatype, serial_num):
        # Todo: potential problem: if couchdb is too slow, then the expired redis data will be uploaded to couchdb while
        #  this store is uploading to couchdb
        st = time.time()
        ips_cnt, local_cnt, remote_cnt, final_cnt = self.get_destination_locality(key)
        ed = time.time()
        # print('get_destination info', ed - st, file=sys.stderr)
        db_key = self.generate_db_key(key, serial_num)
        if datatype == 'json':
            db_key += '.json'
        if local_cnt > 0 or final_cnt > 0:
            # print('begin_put_to_redis', time.time() - start, file=sys.stderr)
            # st = time.time()
            self.put_to_redis(key, db_key, val, datatype, serial_num, local_cnt, remote_cnt)
            # ed = time.time()
            # print('put_to_redis', ed - st, file=sys.stderr)
            # t = threading.Thread(target=self.put_to_redis,
            #                      args=(key, db_key, val, datatype, serial_num, local_cnt, remote_cnt))
            # self.posting_threads.append(t)
            # t.start()
            # t.join()
        if remote_cnt > 0:
            # tmp = json.dumps({'request_id': self.request_id,
            #                   'workflow_name': self.workflow_name,
            #                   'template_name': self.template_name,
            #                   'block_name': self.block_name,
            #                   'key': key,
            #                   'db_key': db_key,
            #                   'datasize': len(val),
            #                   'datatype': datatype,
            #                   'switch_branch': self.switch_branch,
            #                   'serial_num': serial_num,
            #                   'output_type': self.block_infos['output_datas'][key]['type'],
            #                   'ips_cnt': ips_cnt,
            #                   'post_time': time.time()})
            # st = time.time()
            # requests.post('http://127.0.0.1:5000/post_data', data=val, headers={'json': tmp})
            # ed = time.time()
            # print('post_to_bypass_store time: ', ed - st, file=sys.stderr)
            self.store_queue.put({'request_id': self.request_id,
                                  'workflow_name': self.workflow_name,
                                  'template_name': self.template_name,
                                  'block_name': self.block_name,
                                  'key': key,
                                  'db_key': db_key,
                                  'val': val,
                                  'datasize': len(val),
                                  'datatype': datatype,
                                  'switch_branch': self.switch_branch,
                                  'serial_num': serial_num,
                                  'output_type': self.block_infos['output_datas'][key]['type'],
                                  'ips_cnt': ips_cnt,
                                  'post_time': time.time()})
            self.bypass_size += len(val)

    def put_to_redis(self, key, db_key, val, datatype, serial_num, local_cnt, remote_cnt):
        assert datatype == 'json' or datatype == 'octet'
        # st = time.time()
        self.redis[db_key] = val
        # ed = time.time()
        # print('redis post time consuming:', db_key, len(val), ed - st)
        # print('begin_post_to_host', time.time() - start, file=sys.stderr)
        # st = time.time()
        # t = threading.Thread(target=self.post_redis_data_ready_to_host,
        #                      args=(key, db_key, len(val), serial_num, local_cnt, remote_cnt))
        # self.posting_threads.append(t)
        # t.start()
        self.post_redis_data_ready_to_host(key, db_key, len(val), serial_num, local_cnt, remote_cnt)
        # ed = time.time()
        # print('host post time consuming:', db_key, ed - st)
        # print('ending', time.time() - start, file=sys.stderr)
        # self.redis.expire(db_key, 100)

    def put_to_couch(self, key, db_key, val, datatype, serial_num, ips_cnt):
        assert datatype == 'json' or datatype == 'octet'
        file_size = len(val)
        chunk_num = math.ceil(file_size / self.chunk_size)
        # doc = self.db[self.request_id]
        for i in range(chunk_num):
            chunk_val = val[(i * self.chunk_size):((i + 1) * self.chunk_size)]
            while True:
                try:
                    st = time.time()
                    self.db.put_attachment(self.db[self.request_id], chunk_val, filename=db_key + '.' + str(i),
                                           content_type='application/' + datatype)
                    ed = time.time()
                    # print('couchDB post time consuming:', key, ed - st, file=sys.stderr)
                    break
                except Exception as e:
                    print(e, file=sys.stderr)
                    time.sleep(0.05)
                    pass
            if i == 0:
                self.post_couch_data_ready_to_host(key, db_key, len(val), serial_num, ips_cnt, chunk_num)

    def post_couch_data_ready_to_host(self, key, db_key, size, serial_num, ips_cnt, chunk_num):
        post_data = {'request_id': self.request_id,
                     'workflow_name': self.workflow_name,
                     'template_name': self.template_name,
                     'block_name': self.block_name,
                     'datas': {key: {'datatype': 'couch_data_ready', 'datasize': size, 'db_key': db_key,
                                     'switch_branch': self.switch_branch, 'serial_num': serial_num,
                                     'output_type': self.block_infos['output_datas'][key]['type'],
                                     'ips_cnt': ips_cnt, 'chunk_num': chunk_num}},
                     'post_time': time.time()}
        requests.post(host_url.format('commit_inter_data'), json=post_data)

    def post_metadata_to_host(self, key, size, serial_num):
        post_data = {'request_id': self.request_id,
                     'workflow_name': self.workflow_name,
                     'template_name': self.template_name,
                     'block_name': self.block_name,
                     'datas': {key: {'datatype': 'metadata', 'datasize': size,
                                     'db_key': self.generate_db_key(key, serial_num),
                                     'switch_branch': self.switch_branch, 'serial_num': serial_num,
                                     'output_type': self.block_infos['output_datas'][key]['type']}},
                     'post_time': time.time()}
        requests.post(host_url.format('commit_inter_data'), json=post_data)

    def post_redis_data_ready_to_host(self, key, db_key, size, serial_num, local_cnt, remote_cnt):
        post_data = {'request_id': self.request_id,
                     'workflow_name': self.workflow_name,
                     'template_name': self.template_name,
                     'block_name': self.block_name,
                     'datas': {key: {'datatype': 'redis_data_ready', 'datasize': size, 'db_key': db_key,
                                     'local_cnt': local_cnt, 'remote_cnt': remote_cnt,
                                     'switch_branch': self.switch_branch, 'serial_num': serial_num,
                                     'output_type': self.block_infos['output_datas'][key]['type']}},
                     'post_time': time.time()}
        s = socket.socket()
        s.connect(('172.17.0.1', 5999))
        s.sendall(bytes(json.dumps(post_data), encoding='UTF-8'))
        s.close()
        # st = time.time()
        # requests.post(host_url.format('commit_inter_data'), json=post_data)
        # ed = time.time()
        # print('host post time consuming:', db_key, ed - st, file=sys.stderr)

    def post_data_fetched_to_host(self, db_key):
        # Todo: this message can be batched
        post_data = {'request_id': self.request_id,
                     'workflow_name': self.workflow_name,
                     'template_name': self.template_name,
                     'block_name': self.block_name,
                     'datas': {db_key: {'datatype': 'data_fetched', 'db_key': db_key}},
                     'post_time': time.time()}
        s = socket.socket()
        s.connect(('172.17.0.1', 5999))
        s.sendall(bytes(json.dumps(post_data), encoding='UTF-8'))
        s.close()
        # requests.post(host_url.format('commit_inter_data'), json=post_data)

    def post_direct_to_host(self, k, v, datatype, serial_num):
        if datatype == 'octet':
            v = bytes.decode(v)
            datatype = 'base64'
        post_data = {'request_id': self.request_id,
                     'workflow_name': self.workflow_name,
                     'template_name': self.template_name,
                     'block_name': self.block_name,
                     'datas': {k: {'datatype': datatype, 'val': v, 'switch_branch': self.switch_branch,
                                   'serial_num': serial_num,
                                   'output_type': self.block_infos['output_datas'][k]['type']}},
                     'post_time': time.time()}
        s = socket.socket()
        s.connect(('172.17.0.1', 5999))
        s.sendall(bytes(json.dumps(post_data), encoding='UTF-8'))
        s.close()
        # requests.post(host_url.format('commit_inter_data'), json=post_data)
        # print('put_direct_to_host finished!', k, file=sys.stderr)

    def handle_switch(self):
        for condition in self.block_infos['conditions']:
            if condition == 'default' or eval(condition, self.block_outputs):
                self.switch_branch = condition
                break
        for key in self.block_infos['conditions'][self.switch_branch]:
            if key.startswith('virtual'):
                self.block_outputs[key] = 'ok'
                self.outputs_type[key] = 'json'
                self.block_infos['output_datas'][key] = {'type': 'NORMAL'}
            self.post(key, self.block_outputs[key], datatype=self.outputs_type[key])

    def is_affinity_possible(self, key):
        # Todo: This result can be pre-calculated!
        dest = None
        if self.block_infos['type'] == 'SWITCH':
            dest = self.block_infos['conditions'][self.switch_branch][key]
        elif self.block_infos['type'] == 'NORMAL':
            dest = self.block_infos['output_datas'][key]['dest']
        for dest_template_name in dest.keys():
            if dest_template_name == self.template_name:
                return True
        return False

    def get_destination_locality(self, key):
        # Todo: This can be pre-calculated
        dest = None
        local_cnt = 0
        remote_cnt = 0
        final_cnt = 0
        ips_cnt = {}
        if self.block_infos['type'] == 'SWITCH':
            dest = self.block_infos['conditions'][self.switch_branch][key]
        elif self.block_infos['type'] == 'NORMAL':
            dest = self.block_infos['output_datas'][key]['dest']
        local_ip = self.templates_infos[self.template_name]['ip']
        for dest_template_name, dest_template_infos in dest.items():
            if dest_template_name == '$USER':
                final_cnt += 1
                continue
            target_ip = self.templates_infos[dest_template_name]['ip']
            if target_ip == local_ip:
                local_cnt += len(dest_template_infos)
            else:
                remote_cnt += len(dest_template_infos)
            if target_ip not in ips_cnt:
                ips_cnt[target_ip] = 0
            ips_cnt[target_ip] += len(dest_template_infos)
        return ips_cnt, local_cnt, remote_cnt, final_cnt

    def post(self, key, val, force=False, datatype='json', debug=False):
        if debug:
            st = val['st']
            ed = val['ed']
            self.latency_db.save({'request_id': self.request_id, 'template_name': self.template_name,
                                  'block_name': self.block_name + f'_{key}', 'phase': 'use_container',
                                  'time': ed - st, 'st': st, 'ed': ed})
            return
        assert datatype == 'json' or datatype == 'octet'
        if key not in self.outputs_serial:
            self.outputs_serial[key] = 0
        else:
            self.outputs_serial[key] += 1
        serial_num = self.outputs_serial[key]
        if self.block_serial is not None:
            serial_num = self.block_serial
        # Note: A switch block can't handle foreach output!!!
        if self.switch_status == 'PENDING':
            self.block_outputs[key] = val
            self.outputs_type[key] = datatype
            if len(self.block_outputs) == len(self.block_infos['output_datas']):
                self.switch_status = 'READY'
                self.handle_switch()
            return
        # print('POST', key, file=sys.stderr)
        val_db = val
        if datatype == 'json':
            val_db = json.dumps(val)
        size = len(val_db)
        if size > db_threshold or datatype == 'octet':
            # print('enter_put_bitdata', time.time() - start, file=sys.stderr)
            self.put_bigdata(key, val_db, datatype, serial_num)
        else:
            self.post_direct_to_host(key, val, datatype, serial_num)
            # t = threading.Thread(target=self.post_direct_to_host, args=(key, val, datatype, serial_num))
            # self.posting_threads.append(t)
            # t.start()

    def fetch(self, keys):
        self.fetch_dict = {}
        threads = []
        for k in keys:
            self.get_input_data(k, self.block_infos['input_datas'][k]['type'])
            # threads.append(
            #     threading.Thread(target=self.get_input_data, args=(k, self.block_infos['input_datas'][k]['type'])))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return self.fetch_dict

    def get_input_data(self, key, datatype='NORMAL'):
        if key not in self.block_inputs:
            raise Exception('no such input_data: ', key)
        if datatype == 'NORMAL':
            self.fetch_dict[key] = self.fetch_input_data(key, self.block_inputs[key])
        elif datatype == 'LIST':
            # This data is a merged list after foreach
            self.fetch_dict[key] = []
            for i in range(len(self.block_inputs[key])):
                # st = time.time()
                self.fetch_dict[key].append(self.fetch_input_data(key, self.block_inputs[key][str(i)]))
                # ed = time.time()
                # print(i, ed - st, file=sys.stderr)
        else:
            raise Exception

    def fetch_input_data(self, key, data_infos):
        datatype = data_infos['datatype']
        if datatype == 'redis_data_ready':
            return self.fetch_from_redis(data_infos['db_key'])
        elif datatype == 'couch_data_ready':
            return self.fetch_from_couch(data_infos['db_key'])
        elif datatype == 'json' or datatype == 'octet':
            return data_infos['val']
        elif datatype == 'disk_data_ready':
            return self.fetch_from_disk(data_infos['db_key'])
        elif datatype == 'ebpf_data_ready':
            return self.fetch_from_ebpf(data_infos['db_key'], data_infos.get('ebpf_map_id', 0))
        else:
            raise Exception

    def fetch_from_disk(self, key):
        st = time.time()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect('/proxy/mnt/transfer.sock')
        request_info = {'db_key': key}
        s.sendall(bytes(json.dumps(request_info), encoding='UTF-8'))
        data = []
        chunk = s.recv(container_config.SOCKET_CHUNK_SIZE)
        while chunk:
            data.append(chunk)
            chunk = s.recv(container_config.SOCKET_CHUNK_SIZE)
        s.close()
        data = b''.join(data)
        ed = time.time()
        # print('socket fetch from disk', ed - st, file=sys.stderr)
        self.post_data_fetched_to_host(key)
        # r = requests.get(disk_reader_url.format('fetch_from_disk'), json={'db_key': key})
        # t = threading.Thread(target=self.post_data_fetched_to_host, args=(key,))
        # self.posting_threads.append(t)
        # t.start()
        if key[-4:] == 'json':
            return json.loads(data)
        else:
            return data

    def fetch_from_redis(self, key):
        # print('fetching_from_redis:', key, file=sys.stderr)
        val = None
        if key[-4:] == 'json':
            try:
                val = json.loads(self.redis[key].decode())
            except Exception:
                pass
        else:
            try:
                val = self.redis[key]
            except Exception:
                pass
        if val is not None:
            self.post_data_fetched_to_host(key)
            # t = threading.Thread(target=self.post_data_fetched_to_host, args=(key,))
            # self.posting_threads.append(t)
            # t.start()
            return val
        print('fetch_from_redis failed:', key, file=sys.stderr)
        return self.fetch_from_disk(key)

    def fetch_from_couch(self, key):
        if key[-4:] == 'json':
            return json.loads(self.db.get_attachment(self.request_id, filename=key, default='no attachment').read())
        else:
            return self.db.get_attachment(self.request_id, filename=key, default='no attachment').read()
        # octet_data = self.db.get_attachment(self.request_id, filename=key, default='no attachment')
        # if octet_data != 'no attachment':
        #     print(type(octet_data), file=sys.stderr)
        #     return octet_data.read()
        # else:
        #     return json.loads(self.db.get_attachment(self.request_id, filename=key + '.json', default='no attachment'))

    def init_ebpf(self):
        """初始化eBPF程序用于高性能数据接收"""
        if not EBPF_AVAILABLE:
            print(f"[eBPF] BCC库不可用，eBPF功能已禁用", file=sys.stderr)
            self.ebpf_program = None
            self.ebpf_data_map = None
            self.sock_map = None
            self.route_map = None
            return
            
        try:
            # 读取C语言eBPF程序
            ebpf_file_path = os.path.join(os.path.dirname(__file__), 'faasflow_ebpf.c')
            
            if os.path.exists(ebpf_file_path):
                # 使用外部C文件
                print(f"[eBPF] 加载C程序文件: {ebpf_file_path}", file=sys.stderr)
                with open(ebpf_file_path, 'r') as f:
                    ebpf_code = f.read()
            else:
                # 使用内嵌的简化版本
                ebpf_code = """
                #include <uapi/linux/ptrace.h>
                #include <linux/sched.h>
                #include <linux/fs.h>

                // FaaSFlow数据存储Map
                BPF_HASH(data_cache_map, u64, struct data_entry, 512);
                BPF_SOCKMAP(faasflow_sock_map, 65535);
                BPF_HASH(container_route_map, u32, struct container_route, 1000);
                BPF_PERCPU_ARRAY(container_stats_map, struct perf_stats, 1000);
                BPF_RINGBUF_OUTPUT(events_ringbuf, 1 << 20);

                struct data_entry {
                    u64 timestamp;
                    u32 data_size;
                    u32 request_id_hash;
                    u32 container_id;
                    char data[4096];
                };

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

                struct data_event {
                    u32 event_type;
                    u32 container_id;
                    u32 request_id_hash;
                    u32 data_size;
                    u64 timestamp;
                    char data_key[64];
                };

                // SK_MSG程序：高效数据重定向
                int faasflow_sk_msg_prog(struct sk_msg_md *msg) {
                    u32 dest_container = 1;  // 简化版本，固定目标
                    
                    bpf_trace_printk("FaaSFlow SK_MSG: size=%d\\n", msg->size);
                    
                    // 尝试重定向到目标容器
                    int ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, dest_container, BPF_F_INGRESS);
                    
                    if (ret != SK_PASS) {
                        // 重定向失败，转发到网关
                        u32 gateway_id = 0;
                        ret = bpf_msg_redirect_map(msg, &faasflow_sock_map, gateway_id, BPF_F_INGRESS);
                    }
                    
                    return ret;
                }

                // Socket操作优化
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
            
            # 编译eBPF程序
            self.ebpf_program = BPF(text=ebpf_code)
            
            # 获取Maps
            self.ebpf_data_map = self.ebpf_program.get_table("data_cache_map")
            self.sock_map = self.ebpf_program.get_table("faasflow_sock_map")
            self.route_map = self.ebpf_program.get_table("container_route_map")
            self.stats_map = self.ebpf_program.get_table("container_stats_map")
            
            # 加载SK_MSG和SockOps程序
            try:
                msg_prog_fd = self.ebpf_program.load_func("faasflow_sk_msg_prog", BPF.SK_MSG)
                sockops_prog_fd = self.ebpf_program.load_func("faasflow_sockops_prog", BPF.SOCK_OPS)
                
                print(f"[eBPF] SK_MSG程序FD: {msg_prog_fd}, SockOps程序FD: {sockops_prog_fd}", file=sys.stderr)
                
                # 注册容器路由信息
                self._register_container_route()
                
            except Exception as e:
                print(f"[eBPF] 加载SK_MSG/SockOps程序失败: {e}", file=sys.stderr)
            
            print(f"[eBPF] 高效Socket Map初始化成功 - Request: {self.request_id}", file=sys.stderr)
            
        except Exception as e:
            print(f"[eBPF] 初始化失败: {e}", file=sys.stderr)
            self.ebpf_program = None
            self.ebpf_data_map = None
            self.sock_map = None
            self.route_map = None

    def fetch_from_ebpf(self, key, map_id=0):
        """从eBPF Map中获取数据"""
        try:
            if not self.ebpf_program or not self.ebpf_data_map:
                print(f"[eBPF] 程序未初始化，回退到磁盘读取: {key}", file=sys.stderr)
                return self.fetch_from_disk(key)
            
            st = time.time()
            
            # 将key转换为适合的格式
            key_hash = hash(key) & 0xFFFFFFFFFFFFFFFF
            key_c = ctypes.c_uint64(key_hash)
            
            # 从eBPF Map中读取数据
            try:
                data_entry = self.ebpf_data_map[key_c]
                if data_entry:
                    # 解析数据
                    timestamp = struct.unpack('Q', data_entry[:8])[0]
                    data_size = struct.unpack('I', data_entry[8:12])[0]
                    request_id_hash = struct.unpack('I', data_entry[12:16])[0]
                    raw_data = data_entry[16:16+data_size]
                    
                    ed = time.time()
                    print(f"[eBPF] 数据获取成功: {key}, 耗时: {ed-st:.4f}s, 大小: {data_size}", file=sys.stderr)
                    
                    # 通知主机数据已获取
                    self.post_data_fetched_to_host(key)
                    
                    # 根据key类型返回数据
                    if key.endswith('.json'):
                        return json.loads(raw_data.decode('utf-8'))
                    else:
                        return raw_data
                        
            except KeyError:
                print(f"[eBPF] Map中未找到数据: {key}，回退到磁盘读取", file=sys.stderr)
                return self.fetch_from_disk(key)
                
        except Exception as e:
            print(f"[eBPF] 数据获取失败: {e}，回退到磁盘读取", file=sys.stderr)
            return self.fetch_from_disk(key)

    def store_to_ebpf(self, key, data, datatype):
        """将数据存储到eBPF Map中"""
        try:
            if not self.ebpf_program or not self.ebpf_data_map:
                return False
            
            # 准备数据结构
            timestamp = int(time.time() * 1000000)  # 微秒时间戳
            key_hash = hash(key) & 0xFFFFFFFFFFFFFFFF
            
            if isinstance(data, str):
                raw_data = data.encode('utf-8')
            elif isinstance(data, bytes):
                raw_data = data
            else:
                raw_data = json.dumps(data).encode('utf-8')
            
            data_size = len(raw_data)
            request_id_hash = hash(self.request_id) & 0xFFFFFFFF
            
            # 构造数据条目（最大4KB）
            if data_size > 4096:
                print(f"[eBPF] 数据过大，无法存储到Map: {data_size} bytes", file=sys.stderr)
                return False
            
            # 打包数据
            entry_data = struct.pack('Q', timestamp)  # 8 bytes: timestamp
            entry_data += struct.pack('I', data_size)  # 4 bytes: size
            entry_data += struct.pack('I', request_id_hash)  # 4 bytes: request_id_hash
            entry_data += raw_data  # data
            entry_data += b'\x00' * (4096 - len(raw_data))  # padding
            
            # 存储到Map
            key_c = ctypes.c_uint64(key_hash)
            self.ebpf_data_map[key_c] = entry_data
            
            print(f"[eBPF] 数据存储成功: {key}, 大小: {data_size}", file=sys.stderr)
            return True
            
        except Exception as e:
            print(f"[eBPF] 数据存储失败: {e}", file=sys.stderr)
            return False

    def _register_container_route(self):
        """注册容器路由信息到eBPF Map"""
        if not self.route_map:
            return
            
        try:
            # 注册本容器为可用
            container_id = hash(self.template_name) & 0xFFFFFFFF
            route_info = {
                'container_id': container_id,
                'local_available': 1,  # 本地可用
                'gateway_id': 0        # 网关ID为0
            }
            
            # 将路由信息写入eBPF Map
            route_key = ctypes.c_uint32(container_id)
            route_value = struct.pack('III', 
                                    route_info['container_id'],
                                    route_info['local_available'], 
                                    route_info['gateway_id'])
            
            self.route_map[route_key] = route_value
            print(f"[eBPF] 注册容器路由: ID={container_id}, Template={self.template_name}", file=sys.stderr)
            
        except Exception as e:
            print(f"[eBPF] 注册容器路由失败: {e}", file=sys.stderr)

    def register_socket_to_map(self, socket_fd, container_id=None):
        """将socket注册到eBPF Socket Map"""
        if not self.sock_map:
            return False
            
        try:
            if container_id is None:
                container_id = hash(self.template_name) & 0xFFFFFFFF
            
            # 将socket文件描述符注册到eBPF SockMap
            key = ctypes.c_uint32(container_id)
            self.sock_map[key] = ctypes.c_int(socket_fd)
            
            print(f"[eBPF] Socket注册成功: FD={socket_fd}, Container={container_id}", file=sys.stderr)
            return True
            
        except Exception as e:
            print(f"[eBPF] Socket注册失败: {e}", file=sys.stderr)
            return False

    def send_data_via_ebpf(self, dest_container_id, data, request_id=None):
        """通过eBPF Socket Map发送数据"""
        try:
            if not self.sock_map:
                return False
            
            # 构造FaaSFlow数据包头
            magic = 0x46414153  # "FAAS"
            request_id_hash = hash(request_id or self.request_id) & 0xFFFFFFFF
            src_container = hash(self.template_name) & 0xFFFFFFFF
            timestamp = int(time.time() * 1000000)
            
            if isinstance(data, str):
                payload = data.encode('utf-8')
                data_type = 1  # JSON
            elif isinstance(data, dict):
                payload = json.dumps(data).encode('utf-8')
                data_type = 1  # JSON
            else:
                payload = data
                data_type = 2  # OCTET
            
            # 构造数据包头 (32字节)
            header = struct.pack('IIIIIIIQ', 
                               magic,           # 魔数
                               request_id_hash, # 请求ID哈希
                               len(payload),    # 数据大小
                               dest_container_id, # 目标容器
                               src_container,   # 源容器
                               data_type,       # 数据类型
                               0,               # 保留字段
                               timestamp)       # 时间戳
            
            # 完整数据包
            packet = header + payload
            
            # 查找目标socket
            dest_key = ctypes.c_uint32(dest_container_id)
            if dest_key in self.sock_map:
                # 发送数据包 (这里需要用户态socket发送，eBPF会在内核态重定向)
                print(f"[eBPF] 准备发送数据包: 目标={dest_container_id}, 大小={len(packet)}", file=sys.stderr)
                return True
            else:
                print(f"[eBPF] 目标容器{dest_container_id}不在Socket Map中", file=sys.stderr)
                return False
                
        except Exception as e:
            print(f"[eBPF] 发送数据失败: {e}", file=sys.stderr)
            return False

    def get_performance_stats(self):
        """获取eBPF性能统计"""
        if not hasattr(self, 'stats_map') or not self.stats_map:
            return None
            
        try:
            container_id = hash(self.template_name) & 0xFFFFFFFF
            key = ctypes.c_uint32(container_id)
            
            if key in self.stats_map:
                stats_raw = self.stats_map[key]
                # 解析统计数据 (8个uint64字段)
                stats = struct.unpack('QQQQQQQ', stats_raw[:56])
                
                return {
                    'rx_packets': stats[0],
                    'tx_packets': stats[1], 
                    'rx_bytes': stats[2],
                    'tx_bytes': stats[3],
                    'redirect_success': stats[4],
                    'redirect_failed': stats[5],
                    'last_timestamp': stats[6]
                }
            else:
                return None
                
        except Exception as e:
            print(f"[eBPF] 获取性能统计失败: {e}", file=sys.stderr)
            return None

    def cleanup_ebpf(self):
        """清理eBPF资源"""
        try:
            if self.sock_map:
                container_id = hash(self.template_name) & 0xFFFFFFFF
                key = ctypes.c_uint32(container_id)
                if key in self.sock_map:
                    del self.sock_map[key]
                    
            if self.route_map:
                container_id = hash(self.template_name) & 0xFFFFFFFF
                key = ctypes.c_uint32(container_id)
                if key in self.route_map:
                    del self.route_map[key]
                    
            print(f"[eBPF] 清理资源完成", file=sys.stderr)
            
        except Exception as e:
            print(f"[eBPF] 清理资源失败: {e}", file=sys.stderr)
