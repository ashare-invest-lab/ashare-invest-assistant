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

function previousWeekday(day: string): string | null {
  const parsed = Date.parse(`${day}T00:00:00+08:00`);
  if (!Number.isFinite(parsed)) return null;
  const date = new Date(parsed);
  do {
    date.setUTCDate(date.getUTCDate() - 1);
  } while (date.getUTCDay() === 0 || date.getUTCDay() === 6);
  return date.toISOString().slice(0, 10);
}

function referenceTime(now: Date, session?: string, tradeDate?: string, quoteAt?: number): number {
  const local = localParts(now);
  const quoteDay = quoteAt === undefined ? undefined : localParts(new Date(quoteAt)).date;
  const day = tradeDate && /^\d{4}-\d{2}-\d{2}$/.test(tradeDate) ? tradeDate : local.date;
  const minutes = local.minutes;
  if (session === 'lunch_break' || (!session && minutes >= 11 * 60 + 30 && minutes < 13 * 60)) return Date.parse(`${day}T11:30:00+08:00`);
  if (session === 'closed' || (!session && minutes >= 15 * 60)) return Date.parse(`${day}T15:00:00+08:00`);
  if (session === 'call_auction' || session === 'pre_open' || session === 'non_trading_day' || (!session && minutes < 9 * 60 + 30)) {
    // 当天交易日的盘前与集合竞价参照上一开市日收盘，避免用当前时钟给当天盘前行情计龄。
    if (session !== 'non_trading_day' && quoteDay === local.date) {
      const previous = previousWeekday(local.date);
      if (previous !== null) return Date.parse(`${previous}T15:00:00+08:00`);
    }
    return Date.parse(`${quoteDay ?? day}T15:00:00+08:00`);
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
  const reference = referenceTime(now, options.session, options.tradeDate, quoteAt);
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
