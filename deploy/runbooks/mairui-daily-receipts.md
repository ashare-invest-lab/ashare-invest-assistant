# 麦蕊日线授权回执安装

本手册只覆盖两份**已获授权的非密钥回执**的生成与安装：

- `/run/aia/receipts/mairui-daily-bars.json`，`kind=mairui_daily_bars`
- `/run/aia/receipts/mairui-daily.json`，`kind=mairui_daily_snapshot`

脚本不会读取证书、密钥或 `.env`，不会启动应用栈，不会调用采集任务。local/dev 仍使用 `DAILY_BARS_SOURCE=off`，dev 的 `MAIRUI_MODE=replay` 只表示回放输入。真实来源的开启、回执的真实安装和首次拉取必须由编排者按后续批准执行。

## 回执字段

两份回执都必须只包含以下六个字段，脚本拒绝无效 UUID、无效时间或倒置时间窗口：

| 字段 | 含义 |
|---|---|
| `kind` | 对应上面的固定种类 |
| `user_id` | 已获授权用户 UUID |
| `licence_id` | 数据证书 UUID |
| `receipt_id` | 授权回执 UUID |
| `not_before` | RFC3339 含时区起始时间 |
| `expires_at` | RFC3339 含时区结束时间 |

实际 UUID 和时间由授权流程提供。不要把证书、密钥、持仓、交易数据或真实用户标识写入仓库、命令记录或报告。

## 安装器行为

`deploy/scripts/install-mairui-daily-receipts.sh` 使用固定镜像 `alpine:3.21@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab`、root 用户和 `--network none`。它只在临时目录或指定的 `aia_receipts` 具名卷中写入两个文件，并且：

- 创建或校验 root 所有、`0755` 的回执目录。
- 创建 root:root、`0444` 的普通文件。
- 目标文件已存在、是符号链接或并发创建时退出，不覆盖已有回执。
- 只在两个文件都成功落盘后返回成功，失败时不启动任何服务。

## 临时目录演练

演练必须在 Linux 或 WSL 中运行。Windows Git Bash、MSYS 和 Cygwin 会被脚本拒绝，避免 Docker Desktop 把 POSIX 临时路径解释为命名卷。

以下值全部是虚构演练值。演练过程不访问麦蕊，不连接应用栈：

```bash
set -euo pipefail
TMP_DIR="$(mktemp -d -t aia-mairui-receipts.XXXXXX)"
IMAGE='alpine:3.21@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab'
cleanup_tmp() {
  docker run --rm --network none --user 0 \
    --env "CLEANUP_UID=$(id -u)" --env "CLEANUP_GID=$(id -g)" \
    -v "$TMP_DIR:/run/aia/receipts" "$IMAGE" sh -ceu '
      chmod -R u+w /run/aia/receipts
      rm -f /run/aia/receipts/mairui-daily-bars.json /run/aia/receipts/mairui-daily.json
      chown "$CLEANUP_UID:$CLEANUP_GID" /run/aia/receipts
    ' >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR" 2>/dev/null || true
}
trap cleanup_tmp EXIT

# 临时目录必须位于本机临时目录，不要指向仓库或现有数据卷。
deploy/scripts/install-mairui-daily-receipts.sh \
  --target-dir "$TMP_DIR" \
  --user-id 11111111-1111-4111-8111-111111111111 \
  --licence-id 22222222-2222-4222-8222-222222222222 \
  --receipt-id 33333333-3333-4333-8333-333333333333 \
  --not-before 2026-01-01T00:00:00Z \
  --expires-at 2030-01-01T00:00:00Z

docker run --rm --network none --user 10001:10001 \
  -v "$TMP_DIR:/run/aia/receipts:ro" "$IMAGE" sh -ceu '
    test "$(stat -c "%u:%g %a" /run/aia/receipts)" = "0:0 755"
    test "$(stat -c "%u:%g %a" /run/aia/receipts/mairui-daily-bars.json)" = "0:0 444"
    test "$(stat -c "%u:%g %a" /run/aia/receipts/mairui-daily.json)" = "0:0 444"
    cat /run/aia/receipts/mairui-daily-bars.json >/dev/null
    cat /run/aia/receipts/mairui-daily.json >/dev/null
    if touch /run/aia/receipts/should-not-exist 2>/dev/null; then
      echo "非 root 进程不应能写回执目录" >&2
      exit 1
    fi
  '

在与后端依赖一致的 Linux/WSL 环境执行下面的只读校验。它只读取临时目录中的虚构回执，不读取证书或密钥：

```bash
PYTHONPATH=src/backend uv run --offline --project src/backend python - "$TMP_DIR" <<'PY'
import datetime as dt
import sys
import uuid
from pathlib import Path

from app.ingest.daily_bars import read_daily_bars_grant
from app.master.daily_delivery import read_grant

root = Path(sys.argv[1])
user_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
now = dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
assert read_grant(root / "mairui-daily.json") is not None
assert read_daily_bars_grant(
    root / "mairui-daily-bars.json", now=now, user_id=user_id
) is not None
print("receipt readers: valid 0444 permissions accepted")
PY
```

docker run --rm --network none --user 0 \
  -v "$TMP_DIR:/run/aia/receipts" "$IMAGE" sh -ceu '
  chmod 0644 /run/aia/receipts/mairui-daily-bars.json /run/aia/receipts/mairui-daily.json
'

再执行下面的只读校验，确认放宽到 `0644` 后两份回执均被拒绝：

```bash
PYTHONPATH=src/backend uv run --offline --project src/backend python - "$TMP_DIR" <<'PY'
import datetime as dt
import sys
import uuid
from pathlib import Path

from app.ingest.daily_bars import read_daily_bars_grant
from app.master.daily_delivery import read_grant

root = Path(sys.argv[1])
user_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
now = dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
assert read_grant(root / "mairui-daily.json") is None
assert read_daily_bars_grant(
    root / "mairui-daily-bars.json", now=now, user_id=user_id
) is None
print("receipt readers: 0644 rejected")
PY
```

演练结束后只删除本次 `TMP_DIR`。不要把演练文件复制到仓库、镜像或长期卷。

## 获批安装到运行卷

实际安装前确认两份回执来自已批准的授权流程，并取得现有运行栈使用的具名卷名。不要从 `.env` 内容复制值到日志或报告。脚本拒绝覆盖已有文件，因此替换旧回执前先按编排者批准的回执轮换流程处理：

```bash
deploy/scripts/install-mairui-daily-receipts.sh \
  --volume-name <已确认的卷前缀>_aia_receipts \
  --user-id <已批准的用户 UUID> \
  --licence-id <已批准的证书 UUID> \
  --receipt-id <本次回执 UUID> \
  --not-before <RFC3339 起始时间> \
  --expires-at <RFC3339 结束时间>
```

安装后用固定镜像和只读挂载复核权限。复核命令不加入 `aia_egress`，不运行 `compose up`，不启动 `ingest`：

```bash
IMAGE='alpine:3.21@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab'
docker run --rm --network none --user 0 \
  -v '<已确认的卷前缀>_aia_receipts:/run/aia/receipts:ro' "$IMAGE" sh -ceu '
    stat -c "%u:%g %a %n" /run/aia/receipts
    stat -c "%u:%g %a %n" /run/aia/receipts/mairui-daily-bars.json
    stat -c "%u:%g %a %n" /run/aia/receipts/mairui-daily.json
  '
```

期望目录为 `0:0 755`，两个文件均为 `0:0 444`。安装、权限核验和后续首次日线拉取分别留存回执，不把真实字段值贴入公开 PR 或日志。
