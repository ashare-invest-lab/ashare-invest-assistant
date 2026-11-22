import { QUOTE_CLOSE_PRICE } from '../i18n/labels';
import { fmtTime } from './format';

const CLOSE_TAG_STATUS = Object.freeze({ stale: true });

/** 收盘回退只由白名单状态和非空行情时点决定。 */
export function quoteCloseTagText(dataStatus: unknown, t: unknown): string | null {
  if (typeof dataStatus !== 'string' || !Object.hasOwn(CLOSE_TAG_STATUS, dataStatus) || dataStatus !== 'stale') return null;
  if (typeof t !== 'string' || t === '') return null;
  const date = fmtTime(t).slice(5, 10);
  return /^\d{2}-\d{2}$/.test(date) ? `${QUOTE_CLOSE_PRICE}·${date}` : null;
}
