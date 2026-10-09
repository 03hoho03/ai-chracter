import type { WebnovelEndedReason } from "./webnovelError";

/** 열람 종료 안내 아래의 길. `cloverHistory` 는 클로버 내역, `browse` 는 노벨 목록, `home` 은 홈이다. */
export type ReadingEndedAction = "cloverHistory" | "browse" | "home";

export type ReadingEndedNotice = {
  title: string;
  body: string;
  actions: readonly ReadingEndedAction[];
};

/** 소장한 사람이 더는 읽을 수 없는 소설·화를 열었을 때의 안내. 이유마다 무엇이 일어났고 클로버가 어떻게 됐는지를
 * 말한다 — 소장할 때 본 구매 전 고지와 같은 사유 목록이다.
 *
 * 운영 조치와 게시자 정지는 서버가 같은 이유로 묶어 준다 — 정지 사실을 구매자에게 드러내지 않는다. 게시자가 지웠는데
 * 돌려준 클로버가 0 이면(이미지를 옛 판으로 되돌린 동안의 삭제) 환급 문장을 말하지 않는다. */
export function toReadingEndedNotice(reason: WebnovelEndedReason | undefined, refundedAmount: number): ReadingEndedNotice {
  switch (reason) {
    case "deleted":
      return refundedAmount > 0
        ? {
            title: "게시자가 지운 화예요",
            body: `소장할 때 쓴 클로버 ${refundedAmount.toLocaleString()}개는 돌려드렸어요. 클로버 내역에서 확인할 수 있어요.`,
            actions: ["cloverHistory", "browse"],
          }
        : { title: "게시자가 지운 화예요", body: "지워진 화는 더 볼 수 없어요.", actions: ["browse"] };
    case "publisher_withdrawn":
      return {
        title: "게시자가 탈퇴해 더 볼 수 없어요",
        body: "탈퇴하면 소설이 바로 지워져요. 이 경우 클로버는 돌려드리지 않아요.",
        actions: ["browse"],
      };
    case "withdrawn":
      return {
        title: "공개가 끝난 소설이에요",
        body: "게시자가 공개를 거뒀어요. 다시 공개되면 소장한 화도 다시 열려요.",
        actions: ["browse"],
      };
    case "restricted":
      return {
        title: "지금은 볼 수 없는 소설이에요",
        body: "운영 정책에 따라 이용이 제한됐어요.",
        actions: ["browse"],
      };
    case "source_unavailable":
      return {
        title: "원작을 볼 수 없어 함께 숨겨진 소설이에요",
        body: "원작이 다시 공개되면 이 소설도 다시 볼 수 있어요.",
        actions: ["browse"],
      };
    case "service_off":
      return {
        title: "노벨을 잠시 쉬고 있어요",
        body: "다시 열면 소장한 화도 그대로 볼 수 있어요.",
        actions: ["home"],
      };
    case undefined:
      return { title: "지금은 볼 수 없는 소설이에요", body: "잠시 후 다시 확인해 주세요.", actions: ["browse"] };
  }
}
