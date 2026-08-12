# 05 NCCL 编译与双机验证

## 5.1 安装依赖

```bash
sudo apt-get update && sudo apt-get install -y libopenmpi-dev
```

## 5.2 编译 NCCL（支持 Blackwell sm_121）

两台都执行（约 10–20 分钟）：

```bash
sudo mkdir -p /opt/nccl /opt/nccl-tests
sudo chown -R "$USER":"$(id -gn)" /opt/nccl /opt/nccl-tests
git clone -b v2.30.7-1 https://github.com/NVIDIA/nccl.git /opt/nccl
cd /opt/nccl
make -j$(nproc) src.build NVCC_GENCODE="-gencode=arch=compute_121,code=sm_121"

git clone https://github.com/NVIDIA/nccl-tests.git /opt/nccl-tests
cd /opt/nccl-tests
export CUDA_HOME=/usr/local/cuda
export MPI_HOME=/usr/lib/aarch64-linux-gnu/openmpi
export NCCL_HOME=/opt/nccl/build/
export LD_LIBRARY_PATH=$NCCL_HOME/lib:$CUDA_HOME/lib64/:$MPI_HOME/lib:$LD_LIBRARY_PATH
make -j$(nproc) MPI=1
```

## 5.3 确认 RoCE 设备与 GID

```bash
ibdev2netdev                # 查看物理口 → 网口映射
rdma link show              # 期望 state ACTIVE / LINK_UP
# GID 表：找到 IPv4 的 RoCE v2 索引（NCCL_IB_GID_INDEX）
for i in 0 1 2 3 4 5; do
  echo "idx$i: $(cat /sys/class/infiniband/<HCA>/ports/1/gids/$i) $(cat /sys/class/infiniband/<HCA>/ports/1/gid_attrs/types/$i)"
done
```

预期：IPv4 映射的 GID（`::ffff:<fabric-ip>`）位于 **idx3**（RoCE v2）。重启后若出现空洞，
索引可能漂移——07 章的启动脚本默认自动解析（`NCCL_IB_GID_AUTO=1`）。

## 5.4 双机 all_gather 测试

在 head 上执行（`<MGMT_IF>` 为两台一致的管理网口，`<IP_MGMT_*>` 为管理 IP）：

```bash
export CUDA_HOME=/usr/local/cuda
export MPI_HOME=/usr/lib/aarch64-linux-gnu/openmpi
export NCCL_HOME=/opt/nccl/build/
export LD_LIBRARY_PATH=$NCCL_HOME/lib:$CUDA_HOME/lib64/:$MPI_HOME/lib:$LD_LIBRARY_PATH

mpirun -np 2 -H <IP_MGMT_A>:1,<IP_MGMT_B>:1 \
  --mca plm_rsh_agent "ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no" \
  -x LD_LIBRARY_PATH=$LD_LIBRARY_PATH \
  -x UCX_NET_DEVICES=<MGMT_IF> \
  -x NCCL_SOCKET_IFNAME=<MGMT_IF> \
  -x OMPI_MCA_btl_tcp_if_include=<MGMT_IF> \
  /opt/nccl-tests/build/all_gather_perf -b 16G -e 16G -f 2
```

预期：两个 rank 各识别一块 GB10，`#wrong = 0`，busbw 约 **21 GB/s**（≈171 Gbit/s，单线缆合理值）。

> `/opt/nccl` 和 `/opt/nccl-tests` 仅用于宿主机源码编译与 `mpirun` 验证。
> DSpark 启动时使用 `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` 镜像内的 CUDA/NCCL，
> 当前 `docker-compose.dspark.yml` 不挂载这两个宿主目录，因此不需要把它们加入 `config.yaml`
> 或修改 `start-deepseek-v4-flash-dspark.sh` 的运行时路径。

## 5.5 常见问题

| 现象 | 处理 |
|---|---|
| mpirun 卡住/超时 | 先 `ssh <IP_MGMT_B> hostname` 确认免密；再 `mpirun -np 2 -H ... hostname` 最小验证 |
| GID/网络相关报错 | 用 5.3 检查 GID 索引；重启两台重建 GID 表 |
| `ibv_modify_qp` / `unhandled system error` | RoCEv2 GID 索引漂移：改用自动解析或按 5.3 逐台填写 |

## 官方参考

- [NCCL for Multiple Sparks playbook](https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/nccl/README.md)
- [NCCL 源码（tag v2.30.7-1）](https://github.com/NVIDIA/nccl)
- [nccl-tests 源码](https://github.com/NVIDIA/nccl-tests)
- [NCCL 官方文档](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/usage/communicators.html)
