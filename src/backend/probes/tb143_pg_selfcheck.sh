#!/usr/bin/env bash
# 仅虚构数据；无需 Docker、TimescaleDB、业务库或 .env。
# bash src/backend/probes/tb143_pg_selfcheck.sh
# PG_BIN=/path/to/postgresql/17/bin bash src/backend/probes/tb143_pg_selfcheck.sh
set -euo pipefail

pgbin=${PG_BIN:-/usr/lib/postgresql/17/bin}
probes=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for program in initdb pg_ctl postgres psql; do
    if [[ ! -x "$pgbin/$program" ]]; then
        printf 'ERROR: missing PostgreSQL 17 executable: %s/%s\n' "$pgbin" "$program" >&2
        exit 1
    fi
done
if [[ $(id -u) == 0 ]]; then
    printf 'ERROR: run as an unprivileged user (initdb refuses root)\n' >&2
    exit 1
fi
if [[ $("$pgbin/postgres" --version) != *' 17.'* ]]; then
    printf 'ERROR: PostgreSQL 17 is required\n' >&2
    exit 1
fi

root=$(mktemp -d /tmp/tb143-pg.XXXXXXXX)
cleanup() {
    local status=$?
    trap - EXIT
    if [[ $status != 0 && -f "$root/server.log" ]]; then
        cat "$root/server.log" >&2
    fi
    if [[ -f "$root/data/postmaster.pid" ]]; then
        if ! env -i PATH=/usr/bin:/bin "$pgbin/pg_ctl" -D "$root/data" -m fast -w -t 30 stop; then
            printf 'ERROR: stop failed; retained cluster for inspection: %s\n' "$root" >&2
            exit 1
        fi
    fi
    rm -rf -- "$root"
    printf 'CLEANUP: stopped PostgreSQL and removed %s\n' "$root"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir "$root/socket" "$root/meta"
port=$(shuf -i 20000-59999 -n 1)
env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 "$pgbin/initdb" -D "$root/data" \
    --username=tb143_test --auth=trust --no-locale --encoding=UTF8 > "$root/initdb.log"
env -i PATH=/usr/bin:/bin "$pgbin/pg_ctl" -D "$root/data" -l "$root/server.log" \
    -o "-F -k $root/socket -p $port -c listen_addresses=''" -w -t 30 start

psql_test() {
    # -X 与清空环境避免读取用户 psql 配置、连接服务配置或真实凭据。
    env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PGPASSFILE=/dev/null PGSERVICEFILE=/dev/null \
        "$pgbin/psql" -X -h "$root/socket" -p "$port" -U tb143_test -d postgres \
        -v ON_ERROR_STOP=1 "$@"
}
expect_line() {
    if ! grep -Fxq -- "$2" "$1"; then
        cat "$1" >&2
        printf 'ERROR: missing expected output: %s\n' "$2" >&2
        exit 1
    fi
}
psql_test -q <<'SQL'
CREATE SCHEMA market;
CREATE TABLE market.daily_bars (
  code text, trade_date date, adj_type text,
  open numeric(20,4), high numeric(20,4), low numeric(20,4), close numeric(20,4),
  pre_close numeric(20,4), volume numeric(20,4), amount numeric(20,4),
  is_suspended boolean, source text, source_licence_id uuid, fetched_at timestamptz,
  PRIMARY KEY (code, trade_date, adj_type)
);
-- 两张普通表手工逐列对应迁移 0036，包括主键、约束、精度与默认值。
CREATE TABLE market.ex_rights_events (
  code text NOT NULL, ex_date date NOT NULL,
  cash_per_share numeric(20,6) NOT NULL, rights_price numeric(20,6) NOT NULL,
  bonus_ratio numeric(20,6) NOT NULL, rights_ratio numeric(20,6) NOT NULL,
  source text NOT NULL CHECK (source IN ('tdx_gbbq')),
  snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  registered_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (code, ex_date, snapshot_sha256)
);
CREATE TABLE market.minute_file_catalog (
  source text NOT NULL CHECK (source IN ('hf_1min', 'tdx_local')),
  code text NOT NULL, kind text NOT NULL CHECK (kind IN ('1m', '5m')),
  date_from date NOT NULL, date_to date NOT NULL,
  rel_path text NOT NULL CHECK (
    rel_path NOT LIKE '/%' AND position(chr(92) in rel_path) = 0
    AND rel_path !~ '(^|/)[.][.](/|$)' AND position(':' in rel_path) = 0
  ),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  row_count bigint NOT NULL CHECK (row_count >= 0),
  splice_segment text NOT NULL CHECK (splice_segment IN ('hf_1m', 'vipdoc_1m', 'lc5')),
  generator text NOT NULL, registered_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source, code, kind, rel_path), CHECK (date_from <= date_to)
);
INSERT INTO market.daily_bars VALUES
  ('FAKE_M', '2023-11-13', 'none', 20, 21, 19, 20, 19, 200, 4000, false,
   'mairui', '00000000-0000-0000-0000-000000000143', '2023-11-14 00:00:00+00'),
  ('FAKE_T', '2021-01-04', 'none', 10, 11, 9, 10, 9, 100, 1000, false,
   'tdx_local', NULL, '2023-11-14 00:00:00+00');
CREATE TABLE seeded_bars AS SELECT * FROM market.daily_bars;
SQL

cat > "$root/day_2021.csv" <<'CSV'
code,trade_date,adj_type,open,high,low,close,volume,amount
FAKE_T,2021-01-04,none,999,999,999,999,999,999
FAKE_A,2021-01-05,none,10,11,9,10,100,1000
FAKE_B,2021-01-06,none,20,21,19,20,200,4000
CSV
cat > "$root/day_2022.csv" <<'CSV'
code,trade_date,adj_type,open,high,low,close,volume,amount
FAKE_A,2022-01-04,none,10,11,9,10,100,1000
FAKE_B,2022-01-05,none,20,21,19,20,200,4000
CSV
for year in 2021 2022; do
    psql_test -A -t -v "csv=$root/day_$year.csv" -v before=2023-11-13 \
        -f "$probes/tb143_load_day.sql" > "$root/day_$year.out"
    expected='2|2|0'
    [[ $year == 2021 ]] && expected='3|2|1'
    expect_line "$root/day_$year.out" "$expected"
    expect_line "$root/day_$year.out" 'before|0'
    expect_line "$root/day_$year.out" 'after|0'
    expect_line "$root/day_$year.out" 'COMMIT'
    printf 'DAY %s committed candidates|inserted|skipped=%s\n' "$year" "$expected"
    # 新 psql 连接证明上一轮真实提交，同时验证重跑时临时视图不会残留。
    psql_test -A -t -v "csv=$root/day_$year.csv" -v before=2023-11-13 \
        -f "$probes/tb143_load_day.sql" > "$root/repeat_$year.out"
    expected='2|0|2'
    [[ $year == 2021 ]] && expected='3|0|3'
    expect_line "$root/repeat_$year.out" "$expected"
    expect_line "$root/repeat_$year.out" 'COMMIT'
    printf 'DAY %s repeat committed candidates|inserted|skipped=%s\n' "$year" "$expected"
done

# 合法行先于违规行，保证拒绝整批，而非只略过违规行；覆盖等于、大于边界。
for invalid_date in 2023-11-13 2023-11-14; do
    cat > "$root/rejected.csv" <<CSV
code,trade_date,adj_type,open,high,low,close,volume,amount
FAKE_VALID,2023-01-04,none,10,11,9,10,100,1000
FAKE_M,$invalid_date,none,999,999,999,999,999,999
CSV
    if psql_test -A -t -v "csv=$root/rejected.csv" -v before=2023-11-13 \
        -f "$probes/tb143_load_day.sql" > "$root/rejected.out" 2>&1; then
        printf 'ERROR: invalid date was accepted: %s\n' "$invalid_date" >&2
        exit 1
    fi
    if ! grep -Fq '日线日期必须全部小于 before，拒绝加载' "$root/rejected.out"; then
        cat "$root/rejected.out" >&2
        exit 1
    fi
    printf 'DAY rejected trade_date=%s (whole transaction rolled back)\n' "$invalid_date"
done

sha=$(printf 'a%.0s' {1..64})
snapshot=$(printf 'b%.0s' {1..64})
generator=$(printf 'c%.0s' {1..40})
cat > "$root/meta/ex_rights_events.csv" <<CSV
code,ex_date,cash_per_share,rights_price,bonus_ratio,rights_ratio,source,snapshot_sha256
FAKE_A,2022-01-04,0.2,8,0.1,0.1,tdx_gbbq,$snapshot
FAKE_B,2022-01-05,0.3,9,0.2,0.2,tdx_gbbq,$snapshot
CSV
cat > "$root/meta/minute_file_catalog.csv" <<CSV
source,code,kind,date_from,date_to,rel_path,sha256,row_count,splice_segment,generator
hf_1min,FAKE_A,1m,2022-01-04,2026-08-07,hf/fake.parquet,$sha,480,hf_1m,$generator
tdx_local,FAKE_A,1m,2026-08-06,2026-08-10,tdx/fake.lc1,$sha,480,vipdoc_1m,$generator
CSV
for mode in first repeat; do
    psql_test -A -t -v "csvdir=$root/meta" -f "$probes/tb143_load_meta.sql" > "$root/meta.out"
    counts='2|2|0'
    [[ $mode == repeat ]] && counts='2|0|2'
    for target in ex_rights_events minute_file_catalog; do
        expect_line "$root/meta.out" "$target|$counts"
        printf 'META %s %s candidates|inserted|skipped=%s\n' "$mode" "$target" "$counts"
    done
    expect_line "$root/meta.out" 'COMMIT'
done

psql_test -q <<'SQL'
DO $$
BEGIN
  IF (SELECT count(*) FROM market.daily_bars) <> 6
    OR (SELECT count(*) FROM market.ex_rights_events) <> 2
    OR (SELECT count(*) FROM market.minute_file_catalog) <> 2 THEN
    RAISE EXCEPTION 'unexpected final row counts';
  END IF;
  IF EXISTS (SELECT * FROM seeded_bars EXCEPT SELECT * FROM market.daily_bars) THEN
    RAISE EXCEPTION 'seeded mairui or tdx_local row changed';
  END IF;
  IF EXISTS (
    SELECT 1 FROM market.daily_bars AS d WHERE d.code IN ('FAKE_A', 'FAKE_B') AND (
      d.source IS DISTINCT FROM 'tdx_local' OR d.pre_close IS NOT NULL
      OR d.is_suspended IS NOT NULL OR d.source_licence_id IS NOT NULL OR d.fetched_at IS NULL
    )
  ) THEN
    RAISE EXCEPTION 'new daily row provenance is incorrect';
  END IF;
END $$;
SQL
printf 'PASS: daily_bars=6; meta=2+2; seeded mairui/tdx_local rows unchanged (all columns)\n'
