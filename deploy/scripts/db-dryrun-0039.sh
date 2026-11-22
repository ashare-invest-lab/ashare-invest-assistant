#!/bin/sh
# 0039 只读盘点与收口核验。脚本在 PostgreSQL 容器内运行。
set -u
LC_ALL=C
export LC_ALL

usage() {
    printf '%s\n' '用法：db-dryrun-0039.sh --pre [--dbname NAME]' '      db-dryrun-0039.sh --post FILE|- [--dbname NAME]'
}

# 名称只许字母、数字、下划线和连字符，且不以连字符开头，防止选项或连接串注入。
safe_name() {
    case "$1" in
        '' | -* | *[!A-Za-z0-9_-]*) return 1 ;;
    esac
    return 0
}

[ "$#" -ge 1 ] || { usage >&2; exit 4; }
mode=$1
shift
baseline=
case "$mode" in
    --pre) ;;
    --post)
        [ "$#" -ge 1 ] || { usage >&2; exit 4; }
        baseline=$1
        shift
        ;;
    *) usage >&2; exit 4 ;;
esac

dbname=
case "$#" in
    0) ;;
    1)
        case "$1" in
            --dbname=*) dbname=${1#--dbname=}; safe_name "$dbname" || { usage >&2; exit 4; } ;;
            *) usage >&2; exit 4 ;;
        esac
        ;;
    2)
        [ "$1" = "--dbname" ] || { usage >&2; exit 4; }
        dbname=$2
        safe_name "$dbname" || { usage >&2; exit 4; }
        ;;
    *) usage >&2; exit 4 ;;
esac

pg_user=${POSTGRES_USER-}
if [ -z "$dbname" ]; then
    [ -n "$pg_user" ] && [ -n "${POSTGRES_DB-}" ] || exit 4
    dbname=$POSTGRES_DB
    safe_name "$dbname" || exit 4
fi
if [ -n "$pg_user" ]; then
    safe_name "$pg_user" || exit 4
fi

# 固定连到本容器 Unix socket，屏蔽继承的连接覆盖变量。
unset PGHOSTADDR PGPORT PGSERVICE PGSERVICEFILE PGDATABASE PGUSER PGOPTIONS PGSSLMODE PGREQUIRESSL PGTARGETSESSIONATTRS 2>/dev/null || true
PGHOST=/var/run/postgresql
export PGHOST

tmp=${TMPDIR:-/tmp}/dryrun-0039.$$
mkdir "$tmp" 2>/dev/null || exit 4
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

run_sql() {
    # 参数是 SQL 片段，连接参数不会写入输出。
    PGOPTIONS='-c default_transaction_read_only=on' \
        psql -X -q -A -t -v ON_ERROR_STOP=1 -h "$PGHOST" -d "$dbname" ${pg_user:+"-U$pg_user"} <<EOF
BEGIN READ ONLY;
$1
ROLLBACK;
EOF
}

head=$(run_sql "SELECT version_num FROM public.alembic_version LIMIT 1;") || exit 4
head=$(printf '%s\n' "$head" | sed -n 's/^[[:space:]]*//p' | sed -n '1p')
if [ "$mode" = "--pre" ]; then
    if [ "$head" = "0039" ]; then
        printf '%s\n' 'dry_run_status=already_applied'
        exit 0
    fi
    if [ "$head" != "0038" ]; then
        printf 'reason=unexpected_head:%s\n' "$head"
        printf '%s\n' 'dry_run_status=blocked'
        exit 2
    fi
else
    if [ "$head" != "0039" ]; then
        printf 'reason=unexpected_head:%s\n' "$head"
        printf '%s\n' 'dry_run_status=blocked'
        exit 2
    fi
fi

tables='quotes_snapshot realtime_quotes minute_bars minute5_bars'
ext=0
if ext_out=$(run_sql "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN 1 ELSE 0 END;"); then
    [ "$(printf '%s\n' "$ext_out" | sed -n '1p')" = 1 ] && ext=1
else
    exit 4
fi

reasons=$tmp/reasons
: >"$reasons" || exit 4
baseline_file=$tmp/baseline
if [ "$mode" = "--post" ]; then
    if [ "$baseline" = "-" ]; then
        tr -d '\r' >"$baseline_file" || exit 4
    else
        tr -d '\r' <"$baseline" >"$baseline_file" 2>/dev/null || exit 4
    fi
fi

value() {
    file=$1
    key=$2
    default=$3
    got=$(sed -n "s/^$key=//p" "$file" | sed -n '1p')
    [ -n "$got" ] && printf '%s' "$got" || printf '%s' "$default"
}

add_reason() {
    [ "$3" -gt 0 ] 2>/dev/null && printf 'reason=%s:%s:%s\n' "$1" "$2" "$3" >>"$reasons"
}

for table in $tables; do
    exists=$(run_sql "SELECT CASE WHEN to_regclass('market.$table') IS NULL THEN 0 ELSE 1 END;") || exit 4
    exists=$(printf '%s\n' "$exists" | sed -n '1p')
    printf 'table.%s.exists=%s\n' "$table" "$exists"
    if [ "$exists" != 1 ]; then
        printf '%s\n' \
            "table.$table.is_hypertable=false" \
            "table.$table.chunks=0" \
            "table.$table.compressed_chunks=0" \
            "table.$table.primary_key=" \
            "table.$table.unique_indexes=" \
            "table.$table.rows=0" \
            "table.$table.source.NULL=0" \
            "table.$table.licence_null_rows=0" \
            "table.$table.dup_code_ts_groups=0" \
            "table.$table.dup_code_ts_rows=0" \
            "predict.$table.backfill_rows=0" \
            "predict.$table.mairui_null_licence=0" \
            "predict.$table.source_outside_scope=0" \
            "predict.$table.licence_relation_violation=0" \
            "predict.$table.conflict_legacy_groups=0" \
            "predict.$table.conflict_offline_groups=0" \
            "predict.$table.conflict_licence_groups=0" \
            "predict.$table.columns_already_present=0"
        [ "$mode" = "--post" ] && printf '%s\n' \
            "post.$table.revision_gt_zero=0" "post.$table.row_id_null=0" \
            "post.$table.conflict_fingerprint_licence=0" "post.$table.conflict_fingerprint_offline=0"
        continue
    fi

    cols=$(run_sql "SELECT column_name FROM information_schema.columns WHERE table_schema='market' AND table_name='$table' ORDER BY column_name;") || exit 4
    has_source=0; has_licence=0; has_row=0; has_revision=0; has_fp=0
    has_final=0
    printf '%s\n' "$cols" | grep -qx 'source' && has_source=1
    printf '%s\n' "$cols" | grep -qx 'source_licence_id' && has_licence=1
    printf '%s\n' "$cols" | grep -qx 'row_id' && has_row=1
    printf '%s\n' "$cols" | grep -qx 'revision' && has_revision=1
    printf '%s\n' "$cols" | grep -qx 'content_fingerprint' && has_fp=1
    printf '%s\n' "$cols" | grep -qx 'is_final' && has_final=1

    source_test='FALSE'; source_bad='0'; mairui_bad='0'; relation_bad='0'
    source_lines="SELECT 'source.NULL=' || count(*) FROM market.$table;"
    legacy_where='TRUE'; offline_query='0'; licence_query='0'
    if [ "$has_revision" -eq 1 ]; then rev='revision'; group_rev=',revision'; else rev='0'; group_rev=''; fi
    if [ "$has_source" -eq 1 ]; then
        source_test="source IS NOT NULL AND source NOT IN ('mairui','tdx_local','pro_latest','pro_history','ssjy_more','ssjy_all','real_all')"
        source_bad="count(*) FILTER (WHERE $source_test)"
        source_lines="SELECT 'source.' || coalesce(source::text,'NULL') || '=' || count(*) FROM market.$table GROUP BY source ORDER BY source NULLS FIRST;"
        legacy_where='source IS NULL'
        offline_query="count(*) FROM (SELECT code,ts,source,$rev AS rv FROM market.$table WHERE source IN ('tdx_local','pro_latest','pro_history','ssjy_more','ssjy_all','real_all') GROUP BY code,ts,source$group_rev HAVING count(*)>1) d"
        if [ "$has_licence" -eq 1 ]; then
            mairui_bad="count(*) FILTER (WHERE source='mairui' AND source_licence_id IS NULL)"
            # 0039 source_licence_relation：非 mairui（含 NULL）行带证书即违反。
            relation_bad="count(*) FILTER (WHERE source_licence_id IS NOT NULL AND (source IS NULL OR source <> 'mairui'))"
            legacy_where='source IS NULL AND source_licence_id IS NULL'
            licence_query="count(*) FROM (SELECT code,ts,source,source_licence_id,$rev AS rv FROM market.$table WHERE source='mairui' AND source_licence_id IS NOT NULL GROUP BY code,ts,source,source_licence_id$group_rev HAVING count(*)>1) d"
        fi
    fi
    if [ "$has_licence" -eq 1 ]; then
        licence_null='count(*) FILTER (WHERE source_licence_id IS NULL)'
    else
        licence_null='count(*)'
    fi
    if [ "$has_row" -eq 1 ]; then row_null='count(*) FILTER (WHERE row_id IS NULL)'; else row_null='count(*)'; fi
    if [ "$has_fp" -eq 1 ] && [ "$has_source" -eq 1 ]; then
        fp_lic="count(*) FROM (SELECT code,ts,source,source_licence_id,content_fingerprint FROM market.$table WHERE source='mairui' AND source_licence_id IS NOT NULL AND content_fingerprint IS NOT NULL GROUP BY code,ts,source,source_licence_id,content_fingerprint HAVING count(*)>1) x"
        fp_off="count(*) FROM (SELECT code,ts,source,content_fingerprint FROM market.$table WHERE source IN ('tdx_local','pro_latest','pro_history','ssjy_more','ssjy_all','real_all') AND content_fingerprint IS NOT NULL GROUP BY code,ts,source,content_fingerprint HAVING count(*)>1) x"
    else
        fp_lic='0'; fp_off='0'
    fi
    new_cols="'row_id','revision','content_fingerprint'"
    [ "$table" = quotes_snapshot ] || [ "$table" = realtime_quotes ] && new_cols="$new_cols,'source_licence_id'"
    [ "$table" = quotes_snapshot ] && new_cols="$new_cols,'source'"
    [ "$table" = minute_bars ] || [ "$table" = minute5_bars ] && new_cols="$new_cols,'is_final'"
    extra=''
    if [ "$ext" -eq 1 ]; then
        extra="SELECT 'is_hypertable=' || CASE WHEN EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_schema='market' AND hypertable_name='$table') THEN 'true' ELSE 'false' END; SELECT 'chunks=' || count(*) FROM timescaledb_information.chunks WHERE hypertable_schema='market' AND hypertable_name='$table'; SELECT 'compressed_chunks=' || count(*) FROM timescaledb_information.chunks WHERE hypertable_schema='market' AND hypertable_name='$table' AND is_compressed IS TRUE;"
    else
        extra="SELECT 'is_hypertable=false'; SELECT 'chunks=0'; SELECT 'compressed_chunks=0';"
    fi
    sql="$extra
SELECT 'primary_key=' || coalesce((SELECT c.conname FROM pg_constraint c WHERE c.conrelid='market.$table'::regclass AND c.contype='p'),'');
SELECT 'unique_indexes=' || coalesce((SELECT string_agg(c.relname, ',' ORDER BY c.relname) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE i.indrelid='market.$table'::regclass AND i.indisunique AND NOT i.indisprimary),'');
SELECT 'rows=' || count(*) FROM market.$table;
$source_lines
SELECT 'licence_null_rows=' || $licence_null FROM market.$table;
SELECT 'dup_code_ts_groups=' || count(*) FROM (SELECT code,ts FROM market.$table GROUP BY code,ts HAVING count(*)>1) d;
SELECT 'dup_code_ts_rows=' || coalesce(sum(n),0) FROM (SELECT count(*) AS n FROM market.$table GROUP BY code,ts HAVING count(*)>1) d;
SELECT 'predict.$table.backfill_rows=' || count(*) FROM market.$table;
SELECT 'predict.$table.mairui_null_licence=' || $mairui_bad FROM market.$table;
SELECT 'predict.$table.source_outside_scope=' || $source_bad FROM market.$table;
SELECT 'predict.$table.licence_relation_violation=' || $relation_bad FROM market.$table;
SELECT 'predict.$table.conflict_legacy_groups=' || count(*) FROM (SELECT code,ts FROM market.$table WHERE $legacy_where GROUP BY code,ts HAVING count(*)>1) d;
SELECT 'predict.$table.conflict_offline_groups=' || $offline_query;
SELECT 'predict.$table.conflict_licence_groups=' || $licence_query;
SELECT 'predict.$table.columns_already_present=' || count(*) FROM information_schema.columns WHERE table_schema='market' AND table_name='$table' AND column_name IN ($new_cols);
SELECT 'post.$table.revision_gt_zero=' || count(*) FILTER (WHERE $rev>0) FROM market.$table;
SELECT 'post.$table.row_id_null=' || $row_null FROM market.$table;
SELECT 'post.$table.conflict_fingerprint_licence=' || $fp_lic;
SELECT 'post.$table.conflict_fingerprint_offline=' || $fp_off;"
    result=$(run_sql "$sql") || exit 4
    printf '%s\n' "$result" >"$tmp/$table"

    is_h=$(value "$tmp/$table" is_hypertable false)
    chunks=$(value "$tmp/$table" chunks 0)
    compressed=$(value "$tmp/$table" compressed_chunks 0)
    rows=$(value "$tmp/$table" rows 0)
    printf 'table.%s.is_hypertable=%s\n' "$table" "$is_h"
    printf 'table.%s.chunks=%s\n' "$table" "$chunks"
    printf 'table.%s.compressed_chunks=%s\n' "$table" "$compressed"
    printf 'table.%s.primary_key=%s\n' "$table" "$(value "$tmp/$table" primary_key '')"
    printf 'table.%s.unique_indexes=%s\n' "$table" "$(value "$tmp/$table" unique_indexes '')"
    printf 'table.%s.rows=%s\n' "$table" "$rows"
    printf 'table.%s.source.NULL=%s\n' "$table" "$(value "$tmp/$table" source.NULL 0)"
    grep '^source\.' "$tmp/$table" | grep -v '^source\.NULL=' | sed "s/^/table.$table./" || true
    printf 'table.%s.licence_null_rows=%s\n' "$table" "$(value "$tmp/$table" licence_null_rows "$rows")"
    printf 'table.%s.dup_code_ts_groups=%s\n' "$table" "$(value "$tmp/$table" dup_code_ts_groups 0)"
    printf 'table.%s.dup_code_ts_rows=%s\n' "$table" "$(value "$tmp/$table" dup_code_ts_rows 0)"
    for item in backfill_rows mairui_null_licence source_outside_scope licence_relation_violation conflict_legacy_groups conflict_offline_groups conflict_licence_groups columns_already_present; do
        printf 'predict.%s.%s=%s\n' "$table" "$item" "$(value "$tmp/$table" "predict.$table.$item" 0)"
    done
    [ "$mode" = "--pre" ] && {
        add_reason "$table" compressed_chunks "$compressed"
        add_reason "$table" mairui_null_licence "$(value "$tmp/$table" "predict.$table.mairui_null_licence" 0)"
        add_reason "$table" source_outside_scope "$(value "$tmp/$table" "predict.$table.source_outside_scope" 0)"
        add_reason "$table" licence_relation_violation "$(value "$tmp/$table" "predict.$table.licence_relation_violation" 0)"
        add_reason "$table" conflict_legacy_groups "$(value "$tmp/$table" "predict.$table.conflict_legacy_groups" 0)"
        add_reason "$table" conflict_offline_groups "$(value "$tmp/$table" "predict.$table.conflict_offline_groups" 0)"
        add_reason "$table" conflict_licence_groups "$(value "$tmp/$table" "predict.$table.conflict_licence_groups" 0)"
        add_reason "$table" columns_already_present "$(value "$tmp/$table" "predict.$table.columns_already_present" 0)"
        if [ "$table" = quotes_snapshot ] && [ "$has_source" -eq 1 ]; then
            qbad=$(run_sql "SELECT count(*) FROM market.quotes_snapshot WHERE source IS NOT NULL AND source <> 'mairui';") || exit 4
            add_reason "$table" quotes_source_outside_scope "$(printf '%s\n' "$qbad" | sed -n '1p')"
        fi
    }
    if [ "$mode" = "--post" ]; then
        for item in conflict_legacy_groups conflict_offline_groups conflict_licence_groups; do
            n=$(value "$tmp/$table" "predict.$table.$item" 0)
            add_reason "$table" "$item" "$n"
        done
        for item in revision_gt_zero row_id_null conflict_fingerprint_licence conflict_fingerprint_offline; do
            printf 'post.%s.%s=%s\n' "$table" "$item" "$(value "$tmp/$table" "post.$table.$item" 0)"
            n=$(value "$tmp/$table" "post.$table.$item" 0)
            add_reason "$table" "$item" "$n"
        done
        old_rows=$(value "$baseline_file" "table.$table.rows" __missing__)
        old_licence=$(value "$baseline_file" "table.$table.licence_null_rows" __missing__)
        [ "$old_rows" = "$rows" ] || printf 'reason=%s:rows_changed:%s->%s\n' "$table" "$old_rows" "$rows" >>"$reasons"
        now_licence=$(value "$tmp/$table" licence_null_rows "$rows")
        [ "$old_licence" = "$now_licence" ] || printf 'reason=%s:licence_null_rows_changed:%s->%s\n' "$table" "$old_licence" "$now_licence" >>"$reasons"
        [ "$old_rows" != __missing__ ] || printf 'reason=%s:baseline_missing:1\n' "$table" >>"$reasons"
        [ "$old_licence" != __missing__ ] || printf 'reason=%s:baseline_missing:1\n' "$table" >>"$reasons"
    fi
done

if [ -s "$reasons" ]; then
    cat "$reasons"
    printf '%s\n' 'dry_run_status=blocked'
    exit 2
fi
printf '%s\n' 'dry_run_status=ok'
exit 0
