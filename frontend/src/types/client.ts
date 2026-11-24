/** Metadata about every API response, published to listeners such as the status bar. */
export interface ResponseMeta {
  method: string;
  path: string;
  status: number;
  correlationId: string;
  rateLimitRemaining: string | null;
}

/** A parsed response body together with the response headers (ETag, Idempotency-Replayed, …). */
export interface ApiResult<T> {
  data: T;
  headers: Headers;
}

export interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
}

export type MetaListener = (meta: ResponseMeta) => void;

export interface SignInResult {
  token: string;
  scopes: string[];
}

export type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";
