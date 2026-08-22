export const buildProfileUpdatePayload = ({
  firstName,
  lastName,
  bio,
  avatarId,
  avatarColor,
  coverPreset,
}) => ({
  first_name: firstName,
  last_name: lastName,
  bio,
  avatar_id: avatarId,
  avatar_color: avatarColor,
  ...(coverPreset ? { cover_preset: coverPreset } : {}),
});
