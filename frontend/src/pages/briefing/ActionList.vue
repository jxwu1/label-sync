<script setup lang="ts">
export interface Column {
  key: string;
  label: string;
}
type Cell = string | number | null;

withDefaults(
  defineProps<{
    title: string;
    total: number;
    href: string;
    columns: Column[];
    rows: Record<string, Cell>[];
    available?: boolean;
    emptyText?: string;
  }>(),
  { available: true, emptyText: "暂无数据" },
);
</script>

<template>
  <div class="action">
    <div class="action__head">
      <span class="action__title">{{ title }}<span v-if="available" class="action__count"> · {{ total }}</span></span>
      <a class="action__more" :href="href">查看全部 →</a>
    </div>

    <div v-if="!available" class="action__na">暂不可用</div>
    <div v-else-if="rows.length === 0" class="action__empty">{{ emptyText }}</div>
    <table v-else class="action__table">
      <thead>
        <tr>
          <th v-for="c in columns" :key="c.key">{{ c.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in rows" :key="i">
          <td v-for="c in columns" :key="c.key">{{ row[c.key] ?? "—" }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.action {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: var(--sp-4);
}
.action__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--sp-3);
}
.action__title { font-size: var(--fs-base); color: var(--ink-0); }
.action__count { color: var(--ink-2); }
.action__more { font-size: var(--fs-sm); color: var(--accent); text-decoration: none; }
.action__more:hover { text-decoration: underline; }
.action__na,
.action__empty { font-size: var(--fs-sm); color: var(--ink-2); padding: var(--sp-2) 0; }
.action__table { width: 100%; border-collapse: collapse; }
.action__table th {
  text-align: left;
  font-size: var(--fs-xs);
  text-transform: uppercase;
  color: var(--ink-2);
  font-weight: 500;
  padding: var(--sp-1) 0;
  border-bottom: 1px solid var(--line);
}
.action__table td {
  font-family: var(--mono);
  font-size: var(--fs-sm);
  color: var(--ink-1);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--line-soft);
}
</style>
