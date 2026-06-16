import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { MeData } from "../api/types.gen";

export const useCurrentUser = defineStore("currentUser", () => {
  const displayName = ref<string | null>(null);
  const isAdmin = ref(false); // 安全默认：未知时不显示 admin 项

  async function load() {
    try {
      const me = await apiGet<MeData>("/api/me");
      displayName.value = me.display_name;
      isAdmin.value = me.is_admin;
    } catch (e) {
      // 401 透传 → client.ts 的登录跳转接管（不吞）。
      if (e instanceof UnauthenticatedError) throw e;
      // 500/网络 → 降级：admin 项隐藏（安全默认），不缓存 isAdmin。
      isAdmin.value = false;
    }
  }

  return { displayName, isAdmin, load };
});
