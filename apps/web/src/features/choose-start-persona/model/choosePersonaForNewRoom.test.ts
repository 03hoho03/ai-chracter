import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { personaKeys, type Persona, type PersonaList } from "@/entities/persona";
import { sessionKeys } from "@/entities/session";

import { choosePersonaForNewRoom } from "./choosePersonaForNewRoom";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { get } }));

function persona(id: string): Persona {
  return { id, name: id, gender: null, description: "", createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" };
}

function list(ids: string[], defaultPersonaId: string | null): PersonaList {
  return { items: ids.map(persona), defaultPersonaId, maxCount: 10 };
}

describe("choosePersonaForNewRoom", () => {
  let queryClient: QueryClient;
  let openNameModal: ReturnType<typeof vi.fn<() => Promise<Persona | undefined>>>;

  beforeEach(() => {
    get.mockReset();
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    openNameModal = vi.fn<() => Promise<Persona | undefined>>();
  });

  it("starts with the default without asking for a name when profiles exist", async () => {
    get.mockResolvedValue({ data: list(["a", "b"], "b") });

    expect(await choosePersonaForNewRoom(queryClient, undefined, openNameModal)).toEqual({ kind: "chosen", personaId: "b" });
    expect(openNameModal).not.toHaveBeenCalled();
  });

  it("asks for a name when there are no profiles and starts with the created one", async () => {
    get.mockResolvedValue({ data: list([], null) });
    openNameModal.mockResolvedValue(persona("new"));

    expect(await choosePersonaForNewRoom(queryClient, undefined, openNameModal)).toEqual({ kind: "chosen", personaId: "new" });
    expect(openNameModal).toHaveBeenCalledOnce();
  });

  it("does not start when the name modal is closed", async () => {
    get.mockResolvedValue({ data: list([], null) });
    openNameModal.mockResolvedValue(undefined);

    expect(await choosePersonaForNewRoom(queryClient, undefined, openNameModal)).toEqual({ kind: "cancelled" });
  });

  // 목록을 못 받았다고 대화 시작을 막지 않는다 — 서버가 기본으로 시작한다.
  it("goes on with the server default when the list fails", async () => {
    get.mockRejectedValue(new Error("network"));

    expect(await choosePersonaForNewRoom(queryClient, "picked", openNameModal)).toEqual({ kind: "chosen", personaId: "picked" });
    expect(openNameModal).not.toHaveBeenCalled();
  });

  it("asks nothing and does not start while reconsent is required", async () => {
    queryClient.setQueryData(sessionKeys.current(), { termsReconsentRequired: true, privacyReconsentRequired: false });
    get.mockResolvedValue({ data: list([], null) });

    expect(await choosePersonaForNewRoom(queryClient, undefined, openNameModal)).toEqual({ kind: "cancelled" });
    expect(openNameModal).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
  });

  // 로그아웃 전 다른 계정이 남긴 "0개" 캐시로 판정하면 프로필이 있는 계정에 이름 모달이 떠 기본을 덮어쓴다.
  it("refetches instead of trusting a cached list from before", async () => {
    queryClient.setQueryData(personaKeys.list(), list([], null));
    get.mockResolvedValue({ data: list(["mine"], "mine") });

    expect(await choosePersonaForNewRoom(queryClient, undefined, openNameModal)).toEqual({ kind: "chosen", personaId: "mine" });
    expect(openNameModal).not.toHaveBeenCalled();
    expect(get).toHaveBeenCalledOnce();
  });
});
