import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { ReviewCreate, ReviewDetail, ReviewSummary, ReviewVersion } from './types';
import { useCursorPages } from '../lib/cursorPaging';

export interface ReviewFilter { security_code?: string; plan_id?: string }

export const reviewKeys = {
  list: (filter: ReviewFilter) => ['reviews', 'list', filter] as const,
  one: (id: string) => ['reviews', 'one', id] as const,
  versions: (id: string) => ['reviews', 'versions', id] as const,
};

export const useReviews = (filter: ReviewFilter) => useCursorPages<ReviewSummary>({
  queryKey: reviewKeys.list(filter),
  path: '/reviews',
  params: { security_code: filter.security_code || undefined, plan_id: filter.plan_id || undefined },
  idOf: (review) => review.id,
});

export const useReview = (id: string) => useQuery({
  queryKey: reviewKeys.one(id),
  queryFn: ({ signal }) => apiGet<ReviewDetail>(`/reviews/${encodeURIComponent(id)}`, undefined, signal),
  enabled: !!id,
});

export const useReviewVersions = (id: string) => useCursorPages<ReviewVersion>({
  queryKey: reviewKeys.versions(id),
  path: `/reviews/${encodeURIComponent(id)}/versions`,
  enabled: !!id,
  idOf: (version) => String(version.version_no),
});

export const useCreateReview = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewCreate) => apiPost<ReviewDetail>('/reviews', body),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['reviews'] }); },
  });
};
