import { describe, expect, it } from "vitest";

import { PAYOUT_INFO_CONSENT_NOTICE } from "./consentNotice";

const noticeText = PAYOUT_INFO_CONSENT_NOTICE.map((item) => `${item.term} ${item.detail}`).join("\n");

const detailOf = (term: string) => PAYOUT_INFO_CONSENT_NOTICE.find((item) => item.term === term)?.detail ?? "";

describe("PAYOUT_INFO_CONSENT_NOTICE", () => {
  // 화면은 이 순서대로 항목명·내용을 쌓는다. 처리 근거는 주민등록번호가 나오는 수집 항목 바로 뒤에 있어야
  // 주민등록번호를 이 동의로 처리하는 것처럼 읽히지 않는다.
  it("고지 항목이 정해진 순서로 모두 있다", () => {
    expect(PAYOUT_INFO_CONSENT_NOTICE.map((item) => item.term)).toEqual([
      "수집·이용 목적",
      "수집 항목",
      "처리 근거",
      "보유 및 이용 기간",
      "국외 이전",
      "동의를 거부할 권리",
    ]);
  });

  // 법이 동의 때 알리라고 정한 것이 하나라도 빠지면 그 동의로 받은 수집·국외 이전의 근거가 흔들린다.
  it.each([
    ["수집·이용 목적", "수집·이용 목적"],
    ["주민등록번호를 받는다는 사실", "주민등록번호"],
    ["지급에 쓰인 정보의 5년 보존", "5년간 보존하며, 탈퇴해도"],
    ["쓰인 적 없는 정보의 탈퇴 시 파기", "쓰인 적이 없으면 탈퇴할 때 즉시 파기"],
    ["국외 이전받는 자와 국가", "Cloudflare, Inc.(미국"],
    ["국외 이전의 보유 기간", "일간 7일·주간 4주"],
    ["거부할 권리", "동의를 거부할 수 있어요"],
    ["거부에 따른 불이익", "정산금을 지급받을 수 없지만"],
  ])("고지에 %s 이 있다", (_name, keyword) => {
    expect(noticeText).toContain(keyword);
  });

  // 계좌번호 끝 4자리는 화면 표시용으로 암호화하지 않고 저장하므로, "암호화해 저장"만 적으면 평문 사본이 고지에서 빠진다.
  it("수집 항목이 계좌번호 끝 4자리를 따로 저장한다고 알린다", () => {
    expect(detailOf("수집 항목")).toContain("계좌번호 끝 4자리는 따로 저장합니다");
  });

  // 주민등록번호는 동의로 처리할 수 없어서, 법령에 근거해 처리한다는 사실을 동의 고지 안에 적어 둔다.
  it("처리 근거가 주민등록번호를 동의가 아니라 법령에 따라 처리한다고 알린다", () => {
    const basis = detailOf("처리 근거");
    expect(basis).toContain("이 동의가 아니라");
    expect(basis).toContain("「국세기본법 시행령」 제68조 제3항");
  });

  // 백업에는 암호화한 칸만이 아니라 은행·계좌 끝 4자리(평문)와 지급 기록도 담겨 국외로 간다 — 이전 항목을 실제대로 알린다.
  it("국외 이전 항목에 평문 은행·끝 4자리와 지급 기록이 들어 있다", () => {
    const transfer = detailOf("국외 이전");
    expect(transfer).toContain("은행과 계좌번호 끝 4자리는 그대로");
    expect(transfer).toContain("지급 기록이 함께 담겨");
  });

  // 국외 이전 동의는 거부하는 방법까지 알려야 한다 — 체크하지 않는 것이 그 방법이다.
  it("동의를 거부하는 방법을 알린다", () => {
    expect(detailOf("동의를 거부할 권리")).toContain("체크하지 않으면 돼요");
  });
});
