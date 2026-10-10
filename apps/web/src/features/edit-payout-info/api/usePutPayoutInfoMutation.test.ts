import { MutationObserver, QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { putPayoutInfoMutationOptions } from "./usePutPayoutInfoMutation";

const { put } = vi.hoisted(() => ({ put: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { put } }));

const BODY = {
  legalName: "홍길동",
  rrn: "9001011234567",
  bankCode: "004",
  accountNumber: "12345678901234",
  agreed: true,
} as const;

describe("putPayoutInfoMutationOptions", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    put.mockReset();
    put.mockResolvedValue({ data: undefined });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("저장이 끝나고 폼이 사라지면 요청 본문(주민등록번호 원문)을 뮤테이션 캐시에 남기지 않는다", async () => {
    const queryClient = new QueryClient();
    const observer = new MutationObserver(queryClient, putPayoutInfoMutationOptions(queryClient));
    const unsubscribe = observer.subscribe(() => {});

    await observer.mutate(BODY);
    unsubscribe();
    // 기본 gcTime(5분)보다 훨씬 짧게만 흘려도 비어야 한다.
    await vi.advanceTimersByTimeAsync(1_000);

    expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
  });
});
