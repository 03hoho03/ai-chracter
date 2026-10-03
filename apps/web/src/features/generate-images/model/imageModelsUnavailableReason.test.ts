import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { getImageModelsUnavailableReason } from "./imageModelsUnavailableReason";

const AVAILABLE = [{ available: true }];

describe("getImageModelsUnavailableReason", () => {
  it("한 번도 조회가 끝나지 않았으면 대체 화면을 보이지 않는다(로딩 폼)", () => {
    expect(getImageModelsUnavailableReason({ models: undefined, errorUpdatedAt: 0, dataUpdatedAt: 0 })).toBeUndefined();
  });

  it("목록 없이 조회가 실패했으면 오류다", () => {
    expect(getImageModelsUnavailableReason({ models: undefined, errorUpdatedAt: 100, dataUpdatedAt: 0 })).toBe("error");
  });

  // 배경 재조회 실패에도 목록이 남는다 — 보여줄 목록이 있으면 화면을 갈아엎지 않는다.
  it("목록이 있으면 오류가 더 최근이어도 그 목록으로 판정한다", () => {
    expect(getImageModelsUnavailableReason({ models: AVAILABLE, errorUpdatedAt: 200, dataUpdatedAt: 100 })).toBeUndefined();
  });

  it("빈 목록은 empty, 가용 모델이 없으면 unavailable", () => {
    expect(getImageModelsUnavailableReason({ models: [], errorUpdatedAt: 0, dataUpdatedAt: 100 })).toBe("empty");
    expect(
      getImageModelsUnavailableReason({ models: [{ available: false }], errorUpdatedAt: 0, dataUpdatedAt: 100 }),
    ).toBe("unavailable");
  });

  // 실제 query-core 로 상태 전이를 만든다 — 판정이 기대는 성질(재조회가 시작되면 status 는 pending 으로
  // 돌아가도 두 시각은 그대로)이 라이브러리 판올림에서 바뀌면 여기서 드러난다.
  it("오류 뒤 재조회가 진행되는 동안 오류를 유지하고, 성공하면 폼으로 돌아간다", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const queryKey = ["image-model"];
    const judge = () => {
      const state = queryClient.getQueryCache().find<{ available: boolean }[]>({ queryKey })?.state;
      if (state === undefined) throw new Error("쿼리가 캐시에 없다");
      return {
        status: state.status,
        reason: getImageModelsUnavailableReason({
          models: state.data,
          errorUpdatedAt: state.errorUpdatedAt,
          dataUpdatedAt: state.dataUpdatedAt,
        }),
      };
    };

    await queryClient
      .fetchQuery({ queryKey, queryFn: () => Promise.reject(new Error("500")) })
      .catch(() => undefined);
    expect(judge()).toEqual({ status: "error", reason: "error" });

    let resolveRefetch: (models: { available: boolean }[]) => void = () => undefined;
    const refetch = queryClient.fetchQuery({
      queryKey,
      queryFn: () =>
        new Promise<{ available: boolean }[]>((resolve) => {
          resolveRefetch = resolve;
        }),
    });
    expect(judge()).toEqual({ status: "pending", reason: "error" });

    resolveRefetch(AVAILABLE);
    await refetch;
    expect(judge()).toEqual({ status: "success", reason: undefined });
  });
});
