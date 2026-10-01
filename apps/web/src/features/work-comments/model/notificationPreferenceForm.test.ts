import { describe, expect, it } from "vitest";

import { notificationPreferenceFormToServer, notificationPreferenceServerToForm } from "../api/notificationPreferenceMappers";
import { notificationPreferenceErrors } from "./notificationPreferenceErrors";

describe("comment preference form/server boundary", () => {
  it("maps each independent boolean explicitly in both directions", () => {
    const server = { newComment: false, reply: true, mention: false };
    const form = notificationPreferenceServerToForm(server);
    expect(form).toEqual({ isNewCommentEnabled: false, isReplyEnabled: true, isMentionEnabled: false });
    expect(notificationPreferenceFormToServer(form)).toEqual(server);
    expect(form).not.toBe(server);
  });
  it("does not forward form-only properties into an extra-forbidden request", () => {
    const values = {
      isNewCommentEnabled: true, isReplyEnabled: false, isMentionEnabled: true, formOnly: "not a server field",
    };
    expect(notificationPreferenceFormToServer(values)).toEqual({ newComment: true, reply: false, mention: true });
  });
  it("connects normalized server validation to its form field and keeps other failures at root", () => {
    expect(notificationPreferenceErrors({ status: 422, message: "server", fields: { new_comment: "English", mention: "English" } }))
      .toEqual([
        { field: "isNewCommentEnabled", message: "새 원댓글 알림 설정을 확인해주세요." },
        { field: "isMentionEnabled", message: "멘션 알림 설정을 확인해주세요." },
      ]);
    expect(notificationPreferenceErrors({ status: 403, message: "English" })[0]?.field).toBe("root");
  });
});
