import { QUOTE_CLOSE_PRICE } from '../i18n/labels';
import { fmtTime } from './format';

const CLOSE_TAG_STATUS = Object.freeze({ stale: true });
export const QUOTE_STALE_THRESHOLD_S = 30;

export interface QuoteFreshnessOptions {
  /** 以服务端快照时点或测试时点作为观察时刻，避免用客户端收到帧的时间前视。 */
  now?: Date | string;
  session?: string;
  tradeDate?: string;
  staleThresholdS?: number;
}

function localParts(now: Date): { date: string; minutes: number } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(now);
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return { date: `${value('year')}-${value('month')}-${value('day')}`, minutes: Number(value('hour')) * 60 + Number(value('minute')) };
}

function isDateString(value: string | undefined): value is string {
  return value !== undefined && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function atClose(day: string | undefined): number | null {
  if (!isDateString(day)) return null;
  const parsed = Date.parse(`${day}T15:00:00+08:00`);
  return Number.isFinite(parsed) ? parsed : null;
}

function referenceTime(now: Date, session?: string, tradeDate?: string, quoteAt?: number): number | null {
  const local = localParts(now);
  const quoteDay = quoteAt === undefined ? undefined : localParts(new Date(quoteAt)).date;
  const day = isDateString(tradeDate) ? tradeDate : local.date;
  const minutes = local.minutes;
  if (session === 'lunch_break' || (!session && minutes >= 11 * 60 + 30 && minutes < 13 * 60)) return Date.parse(`${day}T11:30:00+08:00`);
  if (session === 'closed' || (!session && minutes >= 15 * 60)) return Date.parse(`${day}T15:00:00+08:00`);
  if (session === 'call_auction' || session === 'pre_open' || session === 'non_trading_day' || (!session && minutes < 9 * 60 + 30)) {
    // 非交易日的 trade_date 是后端给出的最近开市日，直接作为收盘参考。
    if (session === 'non_trading_day') return atClose(isDateString(tradeDate) ? tradeDate : undefined);
    // 交易日盘前只接受行情项已给出的日期作为上一开市日，不在前端推算日历。
    if (isDateString(tradeDate) && quoteDay !== undefined && quoteDay < tradeDate) return atClose(quoteDay);
    // 缺少上一开市日时由调用方按 now 计龄，保持保守口径。
    return null;
  }
  return now.getTime();
}

/** 按 #387 时段表和实时 stale_threshold_s 判断单项行情是否过期。 */
export function isQuoteStale(t: unknown, options: QuoteFreshnessOptions = {}): boolean {
  if (typeof t !== 'string' || t === '') return false;
  const quoteAt = Date.parse(t);
  if (!Number.isFinite(quoteAt)) return false;
  const now = options.now === undefined ? new Date() : new Date(options.now);
  if (!Number.isFinite(now.getTime())) return false;
  const reference = referenceTime(now, options.session, options.tradeDate, quoteAt) ?? now.getTime();
  const threshold = options.staleThresholdS ?? QUOTE_STALE_THRESHOLD_S;
  return Number.isFinite(reference) && reference - quoteAt > Math.max(0, threshold) * 1000;
}

/** 收盘回退只由白名单状态和非空行情时点决定。 */
export function quoteCloseTagText(dataStatus: unknown, t: unknown, freshness: QuoteFreshnessOptions = {}): string | null {
  const stale = typeof dataStatus === 'string' && Object.hasOwn(CLOSE_TAG_STATUS, dataStatus) && dataStatus === 'stale';
  const dynamicStale = !stale && freshness.now !== undefined && isQuoteStale(t, freshness);
  if (!stale && !dynamicStale) return null;
  if (typeof t !== 'string' || t === '') return null;
  const formatted = fmtTime(t);
  if (dynamicStale && !formatted.slice(11, 16).startsWith('15:00')) return null;
  const date = formatted.slice(5, 10);
  return /^\d{2}-\d{2}$/.test(date) ? `${QUOTE_CLOSE_PRICE}·${date}` : null;
}
