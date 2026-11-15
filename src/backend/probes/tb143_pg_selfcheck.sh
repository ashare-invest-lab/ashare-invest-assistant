#!/usr/bin/env bash
# 仅虚构数据；无需 Docker、TimescaleDB、业务库或 .env。
# bash src/backend/probes/tb143_pg_selfcheck.sh
# PG_BIN=/path/to/postgresql/17/bin bash src/backend/probes/tb143_pg_selfcheck.sh
set -euo pipefail
# 旧断言要求 SQL 直写目标表；暂时拒绝运行，避免把 staging 当成完成装载。
# 保留隔离测试正文供 T-T94 迁移，不绕过/放宽其断言。
printf '%s\n' 'REFUSED: legacy SQL load selfcheck awaits public Python writer migration; use python -m app.cli daily-bars-import-tdx（通达信日线导入）或 python -m probes.tb143_day_load --csv <CSV> --before <DATE>（年度 CSV 经公共 writer）' >&2
exit 1

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

# 以下代码和量价均为虚构夹具。默认未建对照：沪深提交，所有 BJ 前缀/后缀跳过。
# runner 同样仅传 csv/before；-v confirmed=1 也不能代替本会话的对照校验。
cat > "$root/bj_default.csv" <<'CSV'
code,trade_date,adj_type,open,high,low,close,volume,amount
FAKE_SH.SH,2022-02-01,none,10,11,9,10,100,1000
FAKE_SZ.SZ,2022-02-01,none,10,11,9,10,100,1000
920801.BJ,2022-02-01,none,10,11,9,10,100,1000
FAKE_SUFFIX.BJ,2022-02-01,none,10,11,9,10,100,1000
CSV
for prefix in {430..439} {830..839} {870..879} 920; do
    for suffix in '' .BJ .SH .SZ SH SZ; do
        printf '%s899%s,2022-02-01,none,10,11,9,10,100,1000\n' "$prefix" "$suffix" \
            >> "$root/bj_default.csv"
    done
done
psql_test -A -t -v "csv=$root/bj_default.csv" -v before=2023-11-13 \
    -v confirmed=1 -f "$probes/tb143_load_day.sql" > "$root/bj_default.out"
expect_line "$root/bj_default.out" '190|2|188'
expect_line "$root/bj_default.out" 'COMMIT'
psql_test -q <<'SQL'
DO $$
BEGIN
  IF (SELECT count(*) FROM market.daily_bars) <> 8
    OR (SELECT count(*) FROM market.daily_bars
        WHERE code IN ('FAKE_SH.SH', 'FAKE_SZ.SZ') AND source = 'tdx_local') <> 2
    OR EXISTS (SELECT 1 FROM market.daily_bars WHERE code ~ '[.]BJ$'
      OR code ~ '^(43[0-9]|83[0-9]|87[0-9]|920)[0-9]{3}') THEN
    RAISE EXCEPTION 'default BJ gate failed or mixed SH/SZ transaction did not commit';
  END IF;
END $$;
SQL
printf 'BJ default: PASS 190|2|188; mixed SH/SZ committed; wrong suffixes blocked; boolean ignored\n'

# 对照只在本 psql 会话内建立，不读取磁盘确认产物；20 只样本不含待加载代码。
# 同一会话先成功，再逐一破坏对照，验证没有残留确认位，也不跨调用累加。
cat > "$root/bj_confirm.csv" <<'CSV'
code,trade_date,adj_type,open,high,low,close,volume,amount
920802.BJ,2022-02-02,none,10,11,9,10,100,1000
CSV
cat > "$root/bj_session.sql" <<'SQL'
CREATE TEMP TABLE tb143_bj_volume_pairs (
  mairui_code text, mairui_t date, mairui_v numeric,
  code text, trade_date date, volume numeric, source text
);
INSERT INTO tb143_bj_volume_pairs
SELECT '920' || n || '.BJ', '2022-01-04'::date, 1.25,
       '920' || n || '.BJ', '2022-01-04'::date, 125, 'tdx_local'
FROM generate_series(901, 920) AS n;
SQL
for scenario in valid insufficient duplicate units extra_bad source code date illegal null negative fractional nan infinity; do
    case "$scenario" in
        valid) change='' ;;
        insufficient) change="DELETE FROM tb143_bj_volume_pairs WHERE code = '920920.BJ';" ;;
        duplicate) change="INSERT INTO tb143_bj_volume_pairs SELECT * FROM tb143_bj_volume_pairs;" ;;
        units) change="UPDATE tb143_bj_volume_pairs SET volume = 126 WHERE code = '920919.BJ';" ;;
        extra_bad) change="INSERT INTO tb143_bj_volume_pairs VALUES ('920921.BJ', '2022-01-04', 1, '920921.BJ', '2022-01-04', 101, 'tdx_local');" ;;
        source) change="UPDATE tb143_bj_volume_pairs SET source = 'other';" ;;
        code) change="UPDATE tb143_bj_volume_pairs SET mairui_code = '920999.BJ';" ;;
        date) change="UPDATE tb143_bj_volume_pairs SET mairui_t = '2022-01-05';" ;;
        illegal) change="UPDATE tb143_bj_volume_pairs SET code = 'FAKE_ILLEGAL.BJ', mairui_code = 'FAKE_ILLEGAL.BJ' WHERE code = '920920.BJ';" ;;
        null) change='UPDATE tb143_bj_volume_pairs SET mairui_v = NULL;' ;;
        negative) change='UPDATE tb143_bj_volume_pairs SET mairui_v = -1, volume = -100;' ;;
        fractional) change='UPDATE tb143_bj_volume_pairs SET mairui_v = 0.001, volume = 0.1;' ;;
        nan) change="UPDATE tb143_bj_volume_pairs SET mairui_v = 'NaN', volume = 'NaN';" ;;
        infinity) change="UPDATE tb143_bj_volume_pairs SET mairui_v = 'Infinity', volume = 'Infinity';" ;;
    esac
    # 除不足/重复码（连续操作同一集合）外，每次先恢复 20 个合法样本。
    if [[ $scenario != valid && $scenario != insufficient && $scenario != duplicate ]]; then
        cat >> "$root/bj_session.sql" <<'SQL'
TRUNCATE tb143_bj_volume_pairs;
INSERT INTO tb143_bj_volume_pairs
SELECT '920' || n || '.BJ', '2022-01-04'::date, 1.25,
       '920' || n || '.BJ', '2022-01-04'::date, 125, 'tdx_local'
FROM generate_series(901, 920) AS n;
SQL
    fi
    cat >> "$root/bj_session.sql" <<SQL
$change
DELETE FROM market.daily_bars WHERE code = '920802.BJ';
\i $probes/tb143_load_day.sql
SELECT '$scenario', count(*) FROM market.daily_bars WHERE code = '920802.BJ';
SQL
done
psql_test -A -t -v "csv=$root/bj_confirm.csv" -v before=2023-11-13 \
    -f "$root/bj_session.sql" > "$root/bj_session.out"
expect_line "$root/bj_session.out" 'valid|1'
expect_line "$root/bj_session.out" '1|1|0'
for scenario in insufficient duplicate units extra_bad source code date illegal null negative fractional nan infinity; do
    expect_line "$root/bj_session.out" "$scenario|0"
done
if [[ $(grep -Fxc 'COMMIT' "$root/bj_session.out") != 14 \
    || $(grep -Fxc '1|0|1' "$root/bj_session.out") != 13 ]]; then
    cat "$root/bj_session.out" >&2
    printf 'ERROR: BJ confirmation cases did not commit expected counts\n' >&2
    exit 1
fi
printf 'BJ session: PASS valid 20 distinct codes; insufficient/duplicate/mismatch/invalid proofs rejected\n'

# 单独确认成功再退出；新 psql 会话仍拒绝 BJ，确认不得跨进程恢复。
psql_test -A -t -v "csv=$root/bj_confirm.csv" -v before=2023-11-13 \
    > "$root/bj_confirmed_session.out" <<SQL
CREATE TEMP TABLE tb143_bj_volume_pairs AS
SELECT '920' || n || '.BJ' AS mairui_code, '2022-01-04'::date AS mairui_t,
       1.25 AS mairui_v, '920' || n || '.BJ' AS code,
       '2022-01-04'::date AS trade_date, 125 AS volume, 'tdx_local'::text AS source
FROM generate_series(901, 920) AS n;
\i $probes/tb143_load_day.sql
DELETE FROM market.daily_bars WHERE code = '920802.BJ';
SQL
expect_line "$root/bj_confirmed_session.out" '1|1|0'
expect_line "$root/bj_confirmed_session.out" 'COMMIT'
psql_test -A -t -v "csv=$root/bj_confirm.csv" -v before=2023-11-13 \
    -f "$probes/tb143_load_day.sql" > "$root/bj_new_session.out"
expect_line "$root/bj_new_session.out" '1|0|1'
expect_line "$root/bj_new_session.out" 'COMMIT'
printf 'BJ new session: PASS confirmation is not inherited\n'
