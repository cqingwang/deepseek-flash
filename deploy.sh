#!/usr/bin/env bash
# =============================================================================
# DeepSeek-V4-Flash 双机集群部署入口 —— 薄层：仅命令解析 + 注入 config 路径。
# 全部功能实现在 program.py（同目录，随仓库提供）；本脚本不承载任何业务逻辑。
#
# 用法（在 head 上执行；chan 需免密 SSH worker 且可 sudo / 操作 docker）：
#   bash deploy.sh --install [模型路径]    安装/覆盖安装（默认 config.common.default_model）
#   bash deploy.sh --uninstall            清理部署（停容器+移除模型注册+禁用自启）
#   bash deploy.sh --restart              重启集群（= stop + start）
#   bash deploy.sh --live_check           双机/API 健康检查
#   bash deploy.sh --doctor               双机环境自检
#   bash deploy.sh --display off|on         设置双机默认终端/图形启动模式
#   bash deploy.sh --help                 显示本帮助
# 兼容无 "--" 前缀写法（如 deploy.sh start）。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROGRAM="$SCRIPT_DIR/program.py"
CONFIG="${CONFIG:-$SCRIPT_DIR/config.yaml}"

[ -f "$PROGRAM" ] || { echo "[FAIL] 缺少 $PROGRAM（program.py 随仓库提供）" >&2; exit 1; }
[ -f "$CONFIG" ]  || { echo "[FAIL] 缺少 $CONFIG（config.yaml 为参数 SSOT）" >&2; exit 1; }

# 剥掉 "--" 前缀（--install -> install）；无前缀亦兼容
CMD="${1#--}"
shift || true

case "$CMD" in
  help|-h|"")  python3 "$PROGRAM" --config "$CONFIG" help ;;
  *)           python3 "$PROGRAM" --config "$CONFIG" "$CMD" "$@" ;;
esac
