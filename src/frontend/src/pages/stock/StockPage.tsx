import { labelOf } from '../../lib/explanations';
import { Button, Result, Tabs, Tag, Tooltip } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router';
import { ApiError } from '../../api/client';
import { ENUMS } from '../../api/enums';
import { CODE_RE, useBarsOf, useBarsWindow, useQuote, useSecurityProfile } from '../../api/marketQueries';
import type { SecurityProfile } from '../../api/marketTypes';
import { useHorizonAssessment } from '../../api/queries';
import type { Bar, BarsResponse, QuoteItem } from '../../api/types';
import { DataStatusTag, ErrorBox, GapNote, KeyTip, Loading } from '../../components/common';
import { QuoteStreamFallback } from '../../components/QuoteStreamFallback';
import { CAP_KIND_TEXT, HORIZON_DATA_MISSING, capExplanation, horizonDataMissing, noSuitableForLackOfData } from '../../i18n/horizonCaps';
import { BOARD, HORIZON, INDUSTRY_TAXONOMY, LISTING_STATUS, PROVIDER, QUOTE_CLOSE_PRICE, SECURITY_RISK_FLAG, SECURITY_RISK_FLAG_TIP, SECURITY_TYPE } from '../../i18n/labels';
import { fmtAmount, fmtNum, fmtPrice, fmtTime, pctClass, signed } from '../../lib/format';
import { StockErrorBoundary } from './StockErrorBoundary';
import { PriceChartPanel } from './PriceChartPanel';
import { AnnouncementsTab, FactorsTab, FinancialsTab, FundFlowTab } from './StockTabs';
import { AddToResearch } from '../../features/research/AddToResearch';
import { WatchlistToggle } from '../../features/watchlist/WatchlistToggle';

const TABS = ['financials', 'fund-flow', 'factors', 'announcements'] as const;
type TabKey = (typeof TABS)[number];

/** /stocks/:code 个股档案（plan §2.4）：行情头 + 深色分时/日K/周K + 周期分类 + 财务/资金/因子/公告外链 */
export function StockPage() {
  const { code = '' } = useParams();
  const client = useQueryClient();
  return (
    <StockErrorBoundary key={code} onRetry={() => {
      // 连同档案缓存标为过期，重挂载后重新读取本证券的数据。
      void client.invalidateQueries({ predicate: (q) => q.queryKey[1] === code.trim().toUpperCase() });
    }}>
      <StockPageContent />
    </StockErrorBoundary>
  );
}

function StockPageContent() {
  const { code: raw = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  // 评审 T-F22a m13：先去空格、转大写再校验；合法但写法不规范时改写为规范 URL
  const code = raw.trim().toUpperCase();
  const valid = CODE_RE.test(code);
  const profile = useSecurityProfile(valid && code === raw ? code : undefined);

  if (valid && code !== raw) return <Navigate to={`/stocks/${encodeURIComponent(code)}${location.search}`} replace />;

  if (!valid) {
    return (
      <div className="page-scroll" data-testid="stock-page">
        <Result status="warning" title="证券代码格式不正确" subTitle={<span>应为 6 位代码加交易所后缀，例如 <span className="mono">600000.SH</span>；收到 <span className="mono">{code}</span></span>}
          extra={<Button size="small" onClick={() => navigate('/terminal')}>回到交易终端</Button>} />
      </div>
    );
  }
  if (profile.isPending) return <div className="page-scroll" data-testid="stock-page"><Loading /></div>;
  if (profile.isError) {
    const nf = profile.error instanceof ApiError && profile.error.status === 404;
    // 契约 §7.3：北交所旧代码 404 带 details.superseded_by，提示改用新代码（真实资源 404，不是“开发中”）
    const superseded = nf ? (profile.error as ApiError).details?.superseded_by : undefined;
    return (
      <div className="page-scroll" data-testid="stock-page">
        {nf ? (
          <Result
            status="404"
            title="未找到该证券"
            subTitle={typeof superseded === 'string' && superseded !== ''
              ? <span><span className="mono">{code}</span> 已停用，请改用 <span className="mono">{superseded}</span></span>
              : <span className="mono">{code}</span>}
            extra={<Button size="small" onClick={() => navigate('/market')}>去市场概览</Button>}
          />
        ) : <ErrorBox error={profile.error} />}
      </div>
    );
  }
  return <StockBody key={code} profile={profile.data} />;
}

function StockBody({ profile }: { profile: SecurityProfile }) {
  const code = profile.security_code;
  const [sp, setSp] = useSearchParams();
  const tab: TabKey = (TABS as readonly string[]).includes(sp.get('tab') ?? '') ? (sp.get('tab') as TabKey) : 'financials';
  return (
    <div className="page-scroll stock-page" data-testid="stock-page">
      <StockHeader profile={profile} />
      <div className="stock-top">
        <PriceChartPanel code={code} initial="d" height={392} />
        <div className="stock-side">
          <ProfilePanel profile={profile} />
          <HorizonPanel code={code} />
        </div>
      </div>
      <section className="panel stock-tabs">
        <Tabs
          size="small"
          activeKey={tab}
          onChange={(k) => setSp((p) => { const n = new URLSearchParams(p); n.set('tab', k); return n; }, { replace: true })}
          items={[
            { key: 'financials', label: '财务', children: <FinancialsTab code={code} /> },
            { key: 'fund-flow', label: '资金流', children: <FundFlowTab code={code} /> },
            { key: 'factors', label: '因子', children: <FactorsTab code={code} /> },
            { key: 'announcements', label: '公告', children: <AnnouncementsTab code={code} /> },
          ]}
        />
      </section>
    </div>
  );
}

// HTTP /quotes 的无来源响应会返回 t=null；没有行情交易日就不能把日K或分时前收认作今日行情。
function todayBar(bars: Bar[] | undefined, q: QuoteItem | null | undefined) {
  const last = bars?.[bars.length - 1];
  return last && q?.t && last.t.slice(0, 10) === q.t.slice(0, 10) ? last : null;
}

/** 1m 响应顶层 pre_close（契约 v0.2.6 Bar 响应）；只在与行情同一交易日时使用 */
function intradayPreClose(res: BarsResponse | undefined, q: QuoteItem | null | undefined) {
  if (!res?.pre_close || !q?.t) return null;
  // A-12/F-14：data_as_of 可为 null（无数据时点），不能直接 slice；取不到交易日就不认这个前收
  const stamp = res.items[0]?.t ?? res.data_as_of;
  if (!stamp) return null;
  const day = stamp.slice(0, 10);
  return day === q.t.slice(0, 10) ? res.pre_close : null;
}

/**
 * 市值 = 价格 × 股本。评审 T-F22a m19：A 股价格 < 1e5、股本 < 1e12，乘积 < 1e17，
 * 双精度相对误差约 1e-16，展示只保留到 0.01 亿（1e6 元），浮点误差远小于展示精度，因此保留 Number 乘法。
 */
const capOf = (price: string, shares: number) => Number(price) * shares;

function StockHeader({ profile }: { profile: SecurityProfile }) {
  const code = profile.security_code;
  const quote = useQuote(code);
  // T-F21：与图表的日 K 窗口共用缓存（同一窗口大小）
  const daily = useBarsWindow(code, 'd', 250);
  // 评审 T-F22a m12：日 K 还没有当日 bar 时，用 1m 响应的 pre_close 作昨收（与分时图共用缓存）
  const intraday = useBarsOf(code, '1m', 240);
  const q = quote.data;
  const displayQuote = q?.data_status === 'unavailable' ? null : q;
  const tb = todayBar(daily.first ? daily.bars : undefined, displayQuote);
  // v0.2.7：停牌不是上市状态，用 suspended 表示
  const suspended = profile.suspended === true;
  const preClose = tb?.pre_close ?? intradayPreClose(intraday.data, displayQuote) ?? (suspended && displayQuote ? displayQuote.price : null);
  const float = profile.float_shares ? Number(profile.float_shares) : null;
  // v0.2.8：ETF 涨跌额按 3 位
  const pd = profile.type === 'etf' ? 3 : 2;
  // 与现有收盘价标签使用相同的 stale + 有价/时点判断；两项都缺失时提示回退。
  const turnoverHint = displayQuote?.data_status === 'stale' && displayQuote.price != null && displayQuote.t && displayQuote.volume == null && displayQuote.amount == null
    ? '收盘价回退，无成交量/额' : '暂无数据';
  const stats: [string, React.ReactNode, string?][] = [
    ['今开', tb ? <span className={pctClass(preClose ? Number(tb.open) - Number(preClose) : 0)}>{fmtPrice(tb.open, profile.type)}</span> : '—'],
    ['最高', tb ? <span className={pctClass(preClose ? Number(tb.high) - Number(preClose) : 0)}>{fmtPrice(tb.high, profile.type)}</span> : '—'],
    ['最低', tb ? <span className={pctClass(preClose ? Number(tb.low) - Number(preClose) : 0)}>{fmtPrice(tb.low, profile.type)}</span> : '—'],
    ['昨收', fmtPrice(preClose, profile.type)],
    ['成交量', displayQuote?.volume != null ? `${fmtAmount(Number(displayQuote.volume) / 100)}手` : '—', displayQuote && displayQuote.volume == null ? turnoverHint : undefined],
    ['成交额', displayQuote ? fmtAmount(displayQuote.amount) : '—', displayQuote && displayQuote.amount == null ? turnoverHint : undefined],
    ['换手率', displayQuote?.volume != null && float ? `${fmtNum((Number(displayQuote.volume) / float) * 100)}%` : '—'],
    ['总市值', displayQuote?.price != null && profile.total_shares ? fmtAmount(capOf(displayQuote.price, Number(profile.total_shares))) : '—'],
    ['流通市值', displayQuote?.price != null && float ? fmtAmount(capOf(displayQuote.price, float)) : '—'],
  ];
  return (
    <header className="stock-head" data-testid="stock-head">
      <div className="sh-id">
        <span className="q-name">{profile.name}</span>
        <span className="mono muted">{code}</span>
        <QuoteStreamFallback />
        {profile.type !== 'stock' ? <Tag color={labelOf(SECURITY_TYPE, profile.type) ? 'blue' : undefined} data-testid="security-type-tag">{(labelOf(SECURITY_TYPE, profile.type) ?? '未知')}</Tag> : null}
        {profile.board ? <Tag variant="outlined">{(labelOf(BOARD, profile.board) ?? '未知')}</Tag> : null}
        {profile.risk_flag ? <Tag color={labelOf(SECURITY_RISK_FLAG, profile.risk_flag) ? 'orange' : undefined} data-testid="risk-flag-tag" data-flag={profile.risk_flag} title={(labelOf(SECURITY_RISK_FLAG_TIP, profile.risk_flag) ?? '未知')}>{(labelOf(SECURITY_RISK_FLAG, profile.risk_flag) ?? '未知')}</Tag> : null}
        {suspended ? <Tag color="default" data-testid="suspended-tag">停牌</Tag> : null}
        {profile.listing_status !== 'listed' ? <Tag data-testid="listing-status-tag">{(labelOf(LISTING_STATUS, profile.listing_status) ?? '未知')}</Tag> : null}
        <AddToResearch origin="from_stock" securityCode={code} securityType={profile.type} />
        <WatchlistToggle code={code} securityType={profile.type} testId="watchlist-stock" />
      </div>
      {quote.isPending ? <span className="muted">行情加载中…</span> : q ? (
        <div className="sh-quote">
          <span className={`q-price mono ${pctClass(displayQuote?.change_pct)}`}>{fmtPrice(displayQuote?.price, profile.type)}</span>
          {q.data_status === 'stale' && q.t ? <Tag data-testid="quote-stale-tag">{QUOTE_CLOSE_PRICE}·{fmtTime(q.t).slice(5, 10)}</Tag> : null}
          <span className={`mono ${pctClass(displayQuote?.change_pct)}`}>
            {preClose && displayQuote?.price != null && !suspended ? `${signed(Number(displayQuote.price) - Number(preClose), pd)} ` : ''}{displayQuote?.change_pct != null ? `(${signed(displayQuote.change_pct)}%)` : '—'}
          </span>
          {q.data_status !== 'stale' && displayQuote?.t ? <Tooltip title="行情时间（北京时间）"><span className="muted small mono">{fmtTime(displayQuote.t)}</span></Tooltip> : null}
          <DataStatusTag status={q.data_status} asOf={q.data_as_of} gaps={q.gaps} />
        </div>
      ) : <span className="muted">无行情缓存</span>}
      {q ? <GapNote status={q.data_status} gaps={q.gaps} asOf={q.data_as_of} testId="quote-gap-note" /> : null}
      <div className="sh-stats">
        {stats.map(([k, v, hint]) => (
          <div key={k}>
            <label>{k}</label>
            {hint ? <KeyTip lines={[hint]}><b className="mono">{v}</b></KeyTip> : <b className="mono">{v}</b>}
          </div>
        ))}
      </div>
    </header>
  );
}

function ProfilePanel({ profile }: { profile: SecurityProfile }) {
  // v0.2.8：ETF 的板块、风险标记、股本、行业为 null、概念为 []，不算数据缺口，显示“不适用”
  const etf = profile.type === 'etf';
  const none = etf ? '不适用' : '—';
  const rows: [string, React.ReactNode][] = [
    ['类型', (labelOf(SECURITY_TYPE, profile.type) ?? '未知')],
    ['所属行业', profile.industry ? `${profile.industry.name}（${(labelOf(INDUSTRY_TAXONOMY, profile.industry.taxonomy) ?? '未知')}）` : none],
    ['概念', profile.concepts.length ? profile.concepts.map((c) => c.name).join('、') : none],
    ['上市日期', profile.list_date ? `${profile.list_date}${profile.list_date_basis === 'neeq_select' ? '（精选层挂牌日）' : ''}` : '—'],
    ...(profile.delist_date ? [['退市日期', profile.delist_date] as [string, React.ReactNode]] : []),
    ...(profile.former_names.length ? [['曾用名', profile.former_names.map((f) => f.name).join('、')] as [string, React.ReactNode]] : []),
    ...(profile.code_history.length
      ? [['原代码', <span className="mono">{profile.code_history.map((c) => c.security_code).join('、')}</span>] as [string, React.ReactNode]]
      : []),
    ['总股本', profile.total_shares ? `${fmtAmount(profile.total_shares)}股` : none],
    ['流通股本', profile.float_shares ? `${fmtAmount(profile.float_shares)}股` : none],
    ...(etf ? [['交易单位', '每手 100 份，价格保留 3 位小数'] as [string, React.ReactNode]] : []),
    ['交易所', profile.exchange === 'SH' ? '上交所' : profile.exchange === 'SZ' ? '深交所' : '北交所'],
  ];
  return (
    <section className="panel side-panel" data-testid="profile-panel">
      <div className="panel-head">
        <span className="panel-title">基本信息</span>
        <span className="spacer" />
        <DataStatusTag status={profile.data_status} asOf={profile.data_as_of} gaps={profile.gaps} />
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {/* v0.2.7：attribution 原样展示；sources 说明各字段来源 */}
      <div className="muted small profile-attr" data-testid="profile-attribution">
        {profile.attribution}（主数据截至 {profile.master_as_of}）
        {profile.sources.length ? ` · 来源：${[...new Set(profile.sources.map((x) => (labelOf(PROVIDER, x.provider) ?? '未知')))].join('、')}` : ''}
      </div>
    </section>
  );
}

/** 契约 §7.3 /horizon-assessments：周期分类（只描述适合的持有周期，不含动作） */
function HorizonPanel({ code }: { code: string }) {
  const q = useHorizonAssessment(code);
  const notFound = q.error instanceof ApiError && q.error.status === 404;
  return (
    <section className="panel side-panel" data-testid="horizon-panel">
      <div className="panel-head">
        <span className="panel-title">周期分类</span>
        {q.data ? <span className="muted small mono">v{q.data.classifier_version}</span> : null}
        {/* T-B46/T-B47 R8/R9：没有适合周期且有 data_missing 封顶时显示“数据不足”，不说“都不适合” */}
        {q.data && noSuitableForLackOfData(q.data) ? <Tag color="warning" variant="outlined" data-testid="hz-data-missing">{HORIZON_DATA_MISSING}</Tag> : null}
        <span className="spacer" />
        <span className="muted small">只描述适合的持有周期</span>
      </div>
      {q.isPending ? <Loading /> : notFound ? (
        <div className="muted small hz-empty">暂无周期分类结果（该证券当前未进入策略池）</div>
      ) : q.isError ? <ErrorBox error={q.error} /> : (
        <div className="hz-list stock-hz">
          {ENUMS.horizon.map((h) => {
            const score = q.data.scores[h];
            const caps = q.data.caps.filter((c) => c.horizon === h);
            const hints = q.data.hints.filter((x) => x.horizon === h);
            const ok = q.data.suitable.includes(h);
            return (
              <div key={h} className={`hz-line${ok ? ' ok' : ''}`} data-testid={`hz-${h}`}>
                <span className="hz-name">{(labelOf(HORIZON, h) ?? '未知')}</span>
                <span className="track"><span className="fill" style={{ width: `${score}%` }} /></span>
                <span className="mono hz-score">{score}</span>
                {ok ? <Tag color="blue" variant="outlined">适合</Tag>
                  : horizonDataMissing(q.data, h) ? <Tag variant="outlined" data-testid={`hz-dm-${h}`}>{HORIZON_DATA_MISSING}</Tag>
                    : <span className="hz-tag-gap" />}
                {/* 评审 T-F22a m10：封顶/提示可 Tab 聚焦、Enter/Space 打开，读屏读到全文 */}
                {caps.length ? (
                  <KeyTip lines={caps.map((c) => `封顶 ${c.cap}（${(labelOf(CAP_KIND_TEXT, c.kind) ?? '未知')}）：${capExplanation(c)}`)} className="warn small" testId={`cap-${h}`}>封顶</KeyTip>
                ) : null}
                {hints.length ? (
                  <KeyTip lines={hints.map((x) => x.text)} className="muted small" testId={`hint-${h}`}>提示</KeyTip>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
