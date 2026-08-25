import { describe, expect, it } from "vitest";

import { buildProfileUpdatePayload } from "./profileUpdate.js";

describe("buildProfileUpdatePayload", () => {
  it("uses a bounded preset identifier and never submits raw media URLs", () => {
    expect(buildProfileUpdatePayload({
      firstName: "Ada",
      lastName: "Lovelace",
      bio: "Mathematician",
      avatarId: "robot",
      avatarColor: "bg-blue-500",
      coverPreset: "classroom-2",
      profileImage: "/api/uploads/objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
      coverImage: "https://tracker.example/cover.png",
    })).toEqual({
      first_name: "Ada",
      last_name: "Lovelace",
      bio: "Mathematician",
      avatar_id: "robot",
      avatar_color: "bg-blue-500",
      cover_preset: "classroom-2",
    });
  });

  it("omits the preset field when the user did not choose one", () => {
    expect(buildProfileUpdatePayload({
      firstName: "Ada",
      lastName: "Lovelace",
      bio: "",
      avatarId: "robot",
      avatarColor: "bg-blue-500",
      coverPreset: null,
    })).not.toHaveProperty("cover_preset");
  });
});
