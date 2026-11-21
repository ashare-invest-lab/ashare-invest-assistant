import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiDelete, apiPost, newIdempotencyKey } from './client';
import { useRef } from 'react';
import type { Restriction, Paged, Gap } from './types';
import type { RestrictionKind, RestrictionTargetType } from './enums';
import { useCursorPages } from '../lib/cursorPaging';
import { qk } from './queries';

export interface RestrictionFilter {
  kind?: RestrictionKind;
  target_type?: RestrictionTargetType;
}

export interface RestrictionPage extends Paged<Restriction> {
  /** 契约 #337（api-contract §7.5）列表页级缺口。 */
  gaps: Gap[];
}
/** 契约 #337（api-contract §7.5）POST 201 响应。 */
export type RestrictionCreated = Restriction & { gaps: Gap[] };
/** 契约 #337（api-contract §7.5）DELETE 200 响应。 */
export type RestrictionDeleted = Restriction & {
  removed_at: string;
  recheck: { released_reason_ids: string[]; remaining_reason_ids: string[] };
  gaps: Gap[];
};

export interface RestrictionCreate {
  kind: RestrictionKind;
  target_type: RestrictionTargetType;
  target_id: string;
  until: string | null;
  reason: string | null;
}

export const rk = {
  all: ['restrictions'] as const,
  list: (filter: RestrictionFilter) => ['restrictions', 'list', filter] as const,
};

function invalidateRestrictionDependents(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: rk.all });
  void qc.invalidateQueries({ queryKey: qk.today });
  void qc.invalidateQueries({ queryKey: ['terminal'] });
  void qc.invalidateQueries({ queryKey: ['candidate-signals'] });
  void qc.invalidateQueries({ queryKey: ['candidate-signal'] });
  void qc.invalidateQueries({ queryKey: ['non-executable-reasons'] });
}

export function useRestrictions(filter: RestrictionFilter) {
  return useCursorPages<Restriction, RestrictionPage>({
    queryKey: rk.list(filter),
    path: '/restrictions',
    params: { kind: filter.kind, target_type: filter.target_type },
    idOf: (item) => item.id,
  });
}

export function useCreateRestriction() {
  const qc = useQueryClient();
  const key = useRef(newIdempotencyKey());
  const lastBody = useRef<string | null>(null);
  return useMutation({
    mutationFn: (body: RestrictionCreate) => {
      const text = JSON.stringify(body);
      if (lastBody.current !== null && lastBody.current !== text) key.current = newIdempotencyKey();
      lastBody.current = text;
      return apiPost<RestrictionCreated>('/restrictions', body, { idempotencyKey: key.current });
    },
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      lastBody.current = null;
      invalidateRestrictionDependents(qc);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code !== 'NETWORK_ERROR' && error.status >= 400 && error.status < 500) {
        key.current = newIdempotencyKey();
        lastBody.current = null;
      }
    },
  });
}

export function useDeleteRestriction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete<RestrictionDeleted>(`/restrictions/${encodeURIComponent(id)}`),
    onSuccess: () => invalidateRestrictionDependents(qc),
  });
}
