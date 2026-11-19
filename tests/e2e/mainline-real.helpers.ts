import type { TodayResponse } from '../../src/frontend/src/api/types';
import { reportDateToFetch } from '../../src/frontend/src/pages/today/todayView';

export function requiresTodayAccount(today: TodayResponse): boolean {
  return reportDateToFetch(today) !== undefined;
}
