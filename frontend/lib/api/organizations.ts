// =============================================================================
// === frontend/lib/api/organizations.ts ===
// Mirrors backend/apps/organizations/serializers.py.
// =============================================================================
import api from "@/lib/api";

export interface Organization {
  id:           string;
  name:         string;
  invoice_code: string;
  phone:        string;
  address:      string;
  plan:         string;
  is_active:    boolean;
  created_at:   string;
}

export const organizationsApi = {
  async mine(): Promise<{ organization: Organization; role: string } | null> {
    try {
      const { data } = await api.get("/api/organizations/mine/");
      return { organization: data.organization, role: data.role };
    } catch {
      return null;
    }
  },
  async update(patch: Partial<Pick<Organization, "name" | "invoice_code" | "phone" | "address">>): Promise<Organization> {
    const { data } = await api.patch("/api/organizations/mine/", patch);
    return data.organization;
  },
};
