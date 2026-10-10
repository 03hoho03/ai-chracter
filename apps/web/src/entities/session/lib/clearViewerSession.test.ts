import { QueryClient, QueryObserver, type QueryKey } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { characterImageArchiveKeys } from "@/entities/character-image-archive/@x/session";
import { chatModelKeys } from "@/entities/chat-model/@x/session";
import { chatRoomKeys } from "@/entities/chat-room/@x/session";
import { cloverKeys } from "@/entities/clover/@x/session";
import { commentKeys } from "@/entities/comment/@x/session";
import { contentKeys, favoriteKeys } from "@/entities/content/@x/session";
import { creatorPayoutKeys } from "@/entities/creator-payout/@x/session";
import { draftKeys } from "@/entities/draft/@x/session";
import { generatedImagesKeys } from "@/entities/generated-image/@x/session";
import { imageJobKeys } from "@/entities/image-job/@x/session";
import { inquiryKeys } from "@/entities/inquiry/@x/session";
import { notificationKeys } from "@/entities/notification/@x/session";
import { novelKeys } from "@/entities/novel/@x/session";
import { personaKeys } from "@/entities/persona/@x/session";
import { previewSessionKeys } from "@/entities/preview-session/@x/session";
import { storyImageArchiveKeys } from "@/entities/story-image-archive/@x/session";
import { webnovelKeys } from "@/entities/webnovel/@x/session";

import { sessionKeys } from "../api/keys";
import { clearViewerQueries, clearViewerSession } from "./clearViewerSession";

// 키 팩토리마다 실제로 쓰이는 모양 하나 이상. 접두 하나가 빠지면 그 줄이 남아 실패한다.
const VIEWER_KEYS: QueryKey[] = [
  chatRoomKeys.myList("u1"),
  chatRoomKeys.myRecentList("u1", 10),
  chatRoomKeys.list({ contentId: "c1", contentType: "character" }),
  chatRoomKeys.detail("r1"),
  chatRoomKeys.memory("r1"),
  chatRoomKeys.playGuide("r1"),
  chatRoomKeys.endingCollection("s1"),
  characterImageArchiveKeys.list("c1"),
  storyImageArchiveKeys.list("s1"),
  chatModelKeys.all,
  cloverKeys.balance(),
  cloverKeys.missions(),
  cloverKeys.ledger("use"),
  commentKeys.preferences("u1"),
  commentKeys.mutes("u1"),
  commentKeys.roots("u1", "c1", "latest"),
  contentKeys.detail("c1"),
  contentKeys.draft("c1"),
  contentKeys.versions("c1"),
  contentKeys.list("u1", "character"),
  favoriteKeys.list("character"),
  creatorPayoutKeys.summary(),
  creatorPayoutKeys.statements(),
  draftKeys.list(),
  generatedImagesKeys.list(),
  imageJobKeys.status("j1"),
  inquiryKeys.list(),
  inquiryKeys.detail("i1"),
  notificationKeys.list("u1"),
  notificationKeys.unread("u1"),
  novelKeys.list(),
  novelKeys.detail("n1"),
  personaKeys.list(),
  previewSessionKeys.detail("p1"),
  webnovelKeys.detail("n1"),
  webnovelKeys.chapter("n1", "ch1"),
  webnovelKeys.list("latest"),
  webnovelKeys.home(),
];

// 누구에게나 같은 응답이라 계정이 바뀌어도 그대로 써도 되는 캐시.
const SHARED_KEYS: QueryKey[] = [
  cloverKeys.pricing(),
  commentKeys.stickers,
  contentKeys.browse({ type: "character", sort: "popular" }),
  contentKeys.genres(),
  contentKeys.homeCuration("character"),
];

let client: QueryClient | undefined;

function makeClient(): QueryClient {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return client;
}

afterEach(() => {
  client?.clear();
  client = undefined;
});

/** 화면에 붙은 쿼리 훅처럼 조회가 켜진 관찰자를 붙인다. 붙는 순간 다시 받지 않게 캐시의 값을 신선하다고 둔다 — 그래야
 * 정리 뒤의 조회만 센다(값이 없으면 신선도와 무관하게 받는다). */
function observe(qc: QueryClient, queryKey: QueryKey) {
  const queryFn = vi.fn(() => Promise.resolve("B"));
  const options = { queryKey, queryFn, staleTime: Infinity };
  const observer = new QueryObserver(qc, options);
  const unsubscribe = observer.subscribe(() => {});
  return { observer, options, queryFn, unsubscribe };
}

describe("clearViewerQueries", () => {
  it("화면에 붙지 않은 사용자별 캐시는 지운다", () => {
    const qc = makeClient();
    for (const key of VIEWER_KEYS) qc.setQueryData(key, "A");

    clearViewerQueries(qc);

    for (const key of VIEWER_KEYS) expect(qc.getQueryCache().find({ queryKey: key, exact: true }), String(key)).toBeUndefined();
  });

  it("화면에 붙은 사용자별 캐시는 옛 값을 비우되 다시 받지 않는다 — 다시 그려져도 받지 않는다", () => {
    const qc = makeClient();
    const observed = VIEWER_KEYS.map((key) => {
      qc.setQueryData(key, "A");
      return observe(qc, key);
    });

    clearViewerQueries(qc);
    // 관찰자가 세션 변화로 다시 그려질 때 쿼리 훅이 하는 일(같은 옵션으로 다시 맞춘다).
    for (const { observer, options } of observed) observer.setOptions(options);

    for (const [index, { observer, queryFn }] of observed.entries()) {
      const key = String(VIEWER_KEYS[index]);
      expect(observer.getCurrentResult().data, key).toBeUndefined();
      expect(queryFn, key).not.toHaveBeenCalled();
    }
    for (const { unsubscribe } of observed) unsubscribe();
  });

  it("다음 계정이 같은 키를 열면 첫 결과부터 옛 값이 없고 새로 받는다", () => {
    const qc = makeClient();
    for (const key of VIEWER_KEYS) qc.setQueryData(key, "A");
    clearViewerQueries(qc);

    for (const key of VIEWER_KEYS) {
      const { observer, options, queryFn, unsubscribe } = observe(qc, key);
      expect(observer.getOptimisticResult(qc.defaultQueryOptions(options)).data, String(key)).toBeUndefined();
      expect(queryFn, String(key)).toHaveBeenCalledTimes(1);
      unsubscribe();
    }
  });

  it("누구에게나 같은 캐시와 세션은 건드리지 않는다", () => {
    const qc = makeClient();
    for (const key of [...SHARED_KEYS, sessionKeys.current()]) qc.setQueryData(key, "kept");

    clearViewerQueries(qc);

    for (const key of [...SHARED_KEYS, sessionKeys.current()]) expect(qc.getQueryData(key), String(key)).toBe("kept");
  });
});

describe("clearViewerSession", () => {
  it("사용자별 캐시는 다시 받지 않고 비우고, 세션만 비운 뒤 다시 받는다", async () => {
    const qc = makeClient();
    qc.setQueryData(sessionKeys.current(), { id: "u1" });
    const sessionFn = vi.fn(() => Promise.reject(new Error("401")));
    const session = new QueryObserver(qc, { queryKey: sessionKeys.current(), queryFn: sessionFn, staleTime: Infinity });
    const unsubscribeSession = session.subscribe(() => {});
    qc.setQueryData(cloverKeys.balance(), "A");
    const clover = observe(qc, cloverKeys.balance());

    clearViewerSession(qc);

    expect(session.getCurrentResult().data).toBeUndefined();
    expect(sessionFn).toHaveBeenCalledTimes(1);
    expect(clover.observer.getCurrentResult().data).toBeUndefined();
    expect(clover.queryFn).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(session.getCurrentResult().status).toBe("error"));
    unsubscribeSession();
    clover.unsubscribe();
  });
});
