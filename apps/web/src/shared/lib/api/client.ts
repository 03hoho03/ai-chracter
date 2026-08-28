import { z } from "zod";
import type { ApiError } from "@ai-character-chat/api-types";
import axios, { type AxiosError } from "axios";

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const baseURL = apiBaseUrl;

/**
 * 인증은 httpOnly 세션 쿠키로 처리되어 브라우저가 요청마다 자동으로 쿠키를
 * 첨부하므로(techspec-overview.md §6.1), 별도의 요청 인터셉터에서 토큰을
 * 붙일 필요는 없다 — `withCredentials: true`만으로 인증 로직이 이 인스턴스에 격리된다.
 */
export const apiClient = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** 401 응답 발생 시 호출될 핸들러를 등록한다. 실제 로그인 라우트 연결(US-011/019)은 이후 단계에서 이 훅을 통해 구현한다. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

/** FastAPI 에러 봉투. `detail`은 셋 중 하나다 — HTTPException의 string, 422 검증 실패의
 * `[{loc, msg, type}]`, 일부 엔드포인트가 쓰는 구조화 dict(예: 429의 retryAfterSeconds).
 *
 * 단언 대신 스키마로 파싱하는 이유(TS-03): 이건 **서버가 주는 외부 데이터**라 모양을 우리가
 * 보장할 수 없다. 프록시가 끼워 넣은 HTML 에러 페이지나 형태가 바뀐 응답이 오면 단언은 그걸
 * 통과시켜 `detail.loc?.at(-1)`에서 터지지만, 파싱은 `undefined`로 떨어져 아래 폴백이 받는다. */
const validationErrorItemSchema = z.object({
  loc: z.array(z.unknown()).optional(),
  msg: z.string().optional(),
});

export const errorEnvelopeSchema = z.object({
  detail: z
    .union([z.string(), z.array(validationErrorItemSchema), z.record(z.string(), z.unknown())])
    .optional(),
});

/** FastAPI는 에러를 항상 `{"detail": ...}` 하나의 키로 내려준다 — HTTPException은 string,
 * 422 검증 실패는 `ValidationErrorItem[]`, 일부 엔드포인트는 구조화된 dict(예: 429의
 * retryAfterSeconds)를 detail로 쓴다. 셋 다 여기서 ApiError로 정규화한다. */
function normalizeError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0;
  const parsed = errorEnvelopeSchema.safeParse(error.response?.data);
  const detail = parsed.success ? parsed.data.detail : undefined;

  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const item of detail) {
      const field = item.loc?.at(-1);
      if (typeof field === "string" && typeof item.msg === "string") {
        fields[field] = item.msg;
      }
    }
    return { status, detail: undefined, fields, message: Object.values(fields)[0] ?? error.message };
  }

  if (typeof detail === "string") {
    return { status, detail, message: detail };
  }

  if (detail && typeof detail === "object") {
    return { status, detail, message: error.message };
  }

  return { status, detail: undefined, message: error.message };
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const normalized = normalizeError(error);

    if (normalized.status === 401) {
      unauthorizedHandler?.();
    }

    return Promise.reject(normalized);
  },
);

/** 이 인스턴스의 실패는 위 인터셉터가 전부 ApiError로 정규화해 reject하므로, catch한
 * `unknown`은 단언 대신 이 가드로 좁힌다(fe-typescript TS-03). */
export function isApiError(error: unknown): error is ApiError {
  return typeof error === "object" && error !== null && "status" in error && "message" in error;
}
