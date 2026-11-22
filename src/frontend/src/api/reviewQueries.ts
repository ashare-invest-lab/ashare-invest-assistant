import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import { ApiError, apiGet, apiPost, newIdempotencyKey } from './client';
import type { ReviewCreate, ReviewDetail, ReviewSummary, ReviewVersion, ReviewVersionCreate } from './types';
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

function useReviewIdemMutation<B, R>(post: (body: B, idempotencyKey: string) => Promise<R>) {
  const client = useQueryClient();
  const key = useRef(newIdempotencyKey());
  const lastBody = useRef<string | null>(null);
  return useMutation({
    mutationFn: (body: B) => {
      const text = JSON.stringify(body);
      if (lastBody.current !== null && lastBody.current !== text) key.current = newIdempotencyKey();
      lastBody.current = text;
      return post(body, key.current);
    },
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      lastBody.current = null;
      await client.invalidateQueries({ queryKey: ['reviews'] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.code !== 'NETWORK_ERROR') {
        key.current = newIdempotencyKey();
        lastBody.current = null;
      }
    },
  });
}

export const useCreateReview = () => useReviewIdemMutation<ReviewCreate, ReviewDetail>((body, idempotencyKey) =>
  apiPost<ReviewDetail>('/reviews', body, { idempotencyKey }));

export const useCreateReviewVersion = (id: string) => useReviewIdemMutation<ReviewVersionCreate, ReviewDetail>((body, idempotencyKey) =>
  apiPost<ReviewDetail>(`/reviews/${encodeURIComponent(id)}/versions`, body, { idempotencyKey }));
