// =============================================================================
// === frontend/lib/api/users.ts ===
// G22-1 (28 Nov 2026): the company's office users ("Pengguna"). Mirrors backend/apps/organizations/members.py.
// =============================================================================
import api from "@/lib/api";

export type MemberRole = "owner" | "admin" | "hr";
export type MemberAction = "deactivate" | "activate" | "reset_password" | "set_role";

export interface Member {
  id: string;
  role: MemberRole;
  role_label: string;
  is_active: boolean;
  is_me: boolean;
  user: { id: string; email: string; full_name: string; phone: string; last_login: string | null;
          must_change_password: boolean };
}

export interface MemberList { my_role: MemberRole; can_assign: MemberRole[]; members: Member[] }

export const ROLE_LABELS: Record<MemberRole, string> = { owner: "Pemilik", admin: "Admin", hr: "HR" };

export const usersApi = {
  async list(): Promise<MemberList> {
    const { data } = await api.get("/api/organizations/members/");
    return data;
  },
  async add(body: { email: string; full_name: string; phone?: string; role: MemberRole }):
      Promise<{ member: Member; temp_password: string }> {
    const { data } = await api.post("/api/organizations/members/", body);
    return data;
  },
  async act(id: string, action: MemberAction, role?: MemberRole): Promise<{ member: Member; temp_password?: string }> {
    const { data } = await api.patch(`/api/organizations/members/${id}/`, { action, role });
    return data;
  },
};
