<script setup lang="ts">
import { computed } from "vue";
import { VISIBLE_CAP } from "./constants";
import { fmt, fmtDays, coverTone, urgencyLevel, marginLevel } from "./cells";
import type { RestockItem } from "./types";

const props = defineProps<{ rows: RestockItem[]; coverThreshold: number }>();
const emit = defineEmits<{ (e: "open-history", bc: string): void; (e: "select-supplier", bc: string): void }>();
const visible = computed(() => props.rows.slice(0, VISIBLE_CAP));
</script>

<template>
  <table class="rs-table">
    <tbody id="rsTbody">
      <tr v-for="it in visible" :key="it.barcode" class="rs-row">
        <td>
          <span v-if="it.urgency_score != null" class="rs-urg">
            <span class="rs-urg-bar"><span :class="`rs-urg-fill rs-urg-fill--${urgencyLevel(it.urgency_score)}`"
              :style="{ width: Math.max(0, Math.min(100, it.urgency_score)) + '%' }"></span></span>
            <span :class="`rs-urg-num rs-urg-num--${urgencyLevel(it.urgency_score)}`">{{ it.urgency_score }}</span>
          </span>
          <span v-else class="rs-urg-num rs-urg-num--none">—</span>
        </td>
        <td>
          <span class="rs-model">{{ it.name_zh || it.model }}</span>
          <button class="rs-bc-link" @click="emit('open-history', it.barcode)">{{ it.barcode }}</button>
          <span v-if="it.is_truly_discontinued" class="rs-tag rs-tag--disc">停用</span>
          <span v-if="it.is_new_item" class="rs-tag rs-tag--new">新品</span>
          <span v-if="it.stockout_zero_weeks_last8 > 0" class="rs-badge-stockout">⚠ 近 {{ it.stockout_zero_weeks_last8 }} 周零销疑因缺货</span>
        </td>
        <td>
          <button v-if="it.supplier_id" class="rs-supplier" @click="emit('select-supplier', it.supplier_id)">{{ it.supplier_id }}</button>
          <span v-else class="rs-supplier rs-supplier--none">—</span>
        </td>
        <td class="rs-num">{{ fmt(it.qty_total) }}</td>
        <td class="rs-num">
          <span :class="`rs-cover-num ${coverTone(it.weeks_of_cover, props.coverThreshold)}`">
            {{ it.weeks_of_cover != null ? it.weeks_of_cover.toFixed(1) + "w" : "—" }}</span>
        </td>
        <td class="rs-num">{{ fmt(it.weekly_velocity, 1) }}</td>
        <td class="rs-num">€{{ fmt(it.weekly_revenue, 1) }}</td>
        <td class="rs-num">
          <span v-if="it.margin_pct != null" :class="`rs-margin rs-margin--${marginLevel(it.margin_pct)}`">{{ it.margin_pct.toFixed(1) }}%</span>
          <span v-else class="rs-margin rs-margin--none">—</span>
        </td>
        <td class="rs-num">{{ fmtDays(it.last_purchase_days_ago) }}</td>
        <td class="rs-num">{{ it.restock_qty_p50 ?? "—" }}</td>
        <td class="rs-num">{{ it.restock_qty_p98 ?? "—" }}</td>
        <td class="rs-num">{{ it.last_purchase_qty ?? "—" }}</td>
      </tr>
      <tr v-if="visible.length === 0"><td colspan="12" class="empty">无匹配项</td></tr>
    </tbody>
  </table>
</template>
