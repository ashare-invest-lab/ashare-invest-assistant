import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiDelete, apiPost } from './client';
import type { Restriction, Paged, Gap } from './types';
import type { RestrictionKind, RestrictionTargetType } from './enums';
import { useCursorPages } from '../lib/cursorPaging';
import { qk } from './queries';

export interface RestrictionFilter {
  kind?: RestrictionKind;
  target_type?: RestrictionTargetType;
}

export interface RestrictionPage extends Paged<Restriction> {
  /** T-A209 草案字段，未验证。 */
  gaps?: Gap[];
}
/** T-A209 草案字段，未验证。 */
export type RestrictionCreated = Restriction & { gaps?: Gap[] };
export interface RestrictionDeleted {
  id: string;
  removed_at: string;
  recheck?: { released_reason_ids?: string[]; remaining_reason_ids?: string[] };
  gaps?: Gap[];
}

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
  return useMutation({
    mutationFn: (body: RestrictionCreate) => apiPost<RestrictionCreated>('/restrictions', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: rk.all });
      void qc.invalidateQueries({ queryKey: qk.today });
      void qc.invalidateQueries({ queryKey: ['terminal'] });
      void qc.invalidateQueries({ queryKey: ['candidate-signals'] });
      void qc.invalidateQueries({ queryKey: ['candidate-signal'] });
      void qc.invalidateQueries({ queryKey: ['non-executable-reasons'] });
    },
  });
}

export function useDeleteRestriction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete<RestrictionDeleted>(`/restrictions/${encodeURIComponent(id)}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: rk.all });
      void qc.invalidateQueries({ queryKey: qk.today });
      void qc.invalidateQueries({ queryKey: ['terminal'] });
      void qc.invalidateQueries({ queryKey: ['candidate-signals'] });
      void qc.invalidateQueries({ queryKey: ['candidate-signal'] });
      void qc.invalidateQueries({ queryKey: ['non-executable-reasons'] });
    },
  });
}
