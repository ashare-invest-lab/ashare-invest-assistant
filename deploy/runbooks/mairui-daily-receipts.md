# 麦蕊日线授权回执安装手册

本手册对应 ADD-A4。安装脚本只生成并安装两个非密钥授权回执，不读取证书、密钥或 `.env`，不启动容器，不触发采集。

## 默认与边界

- `DAILY_BARS_SOURCE=off` 是 local 默认值。优点是启动和回放不会意外进入日线采集，缺点是日线更新必须在获批后显式打开。
- `deploy/compose/docker-compose.dev.yml` 固定 `DAILY_BARS_SOURCE=off` 与 `MAIRUI_MODE=replay`。replay 只读取脱敏 fixtures，不调用麦蕊。
- `DAILY_BARS_SOURCE=mairui` 只用于已获批准的配置。优点是可接入真实日线更新，代价是需要授权回执、live 配置和真实上游调用，因此不能在本地回放演练中设置。
- 回执目录应作为 root 属主、应用只读挂载到 `/run/aia/receipts`。安装脚本要求目录不对 group/other 写开放，两个回执文件为 `root:root` 和 `0444`。

## 回执字段

脚本写入以下两个文件，每个对象只含六个字段。

- `mairui-daily.json` 使用 `kind=mairui_daily_snapshot`
- `mairui-daily-bars.json` 使用 `kind=mairui_daily_bars`
- `user_id`、`licence_id`、`receipt_id` 使用 UUID
- `not_before` 与 `expires_at` 使用带时区的 ISO 8601 时间，且 `not_before` 必须早于 `expires_at`

脚本拒绝覆盖已有回执。回执内容由参数生成，脚本不校验数据库证书归属，也不替代人工授权。

## 仅临时目录演练

在 Linux 容器或 Linux 主机的临时目录中以 root 身份运行。下列 UUID 和时间均为虚构演练值，不得替换为仓库内容或提交到公开仓库。

```sh
set -eu
work=$(mktemp -d)
chmod 0755 "$work"

deploy/scripts/install-mairui-daily-receipts.sh \
  --target-dir "$work" \
  --user-id 11111111-1111-4111-8111-111111111111 \
  --licence-id 22222222-2222-4222-8222-222222222222 \
  --daily-receipt-id 33333333-3333-4333-8333-333333333333 \
  --daily-bars-receipt-id 44444444-4444-4444-8444-444444444444 \
  --not-before 2030-01-01T00:00:00Z \
  --expires-at 2030-01-02T00:00:00Z

stat -c '%u:%g %a %n' "$work/mairui-daily.json" "$work/mairui-daily-bars.json"
python3 - "$work/mairui-daily.json" "$work/mairui-daily-bars.json" <<'PY'
import json
import os
import stat
import sys

expected = {
    "mairui-daily.json": "mairui_daily_snapshot",
    "mairui-daily-bars.json": "mairui_daily_bars",
}
fields = {"kind", "user_id", "licence_id", "receipt_id", "not_before", "expires_at"}
for raw_path in sys.argv[1:]:
    path = os.path.abspath(raw_path)
    name = os.path.basename(path)
    st = os.stat(path)
    assert st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o444
    with open(path, encoding="utf-8") as handle:
        obj = json.load(handle)
    assert set(obj) == fields
    assert obj["kind"] == expected[name]
print("receipt drill passed")
PY

rm -r "$work"
```

The drill checks only synthetic files in the temporary directory. It does not run compose, change `DAILY_BARS_SOURCE`, read a licence, or contact an upstream service.

## Approved installation shape

After a separate operator approval for real collection, prepare the root-owned `/run/aia/receipts` directory and run the same script with approved UUID and time values. Keep the directory mounted read-only into `worker` and `ingest`. Keep local and development profiles at `DAILY_BARS_SOURCE=off` and `MAIRUI_MODE=replay` until that approval is recorded.
