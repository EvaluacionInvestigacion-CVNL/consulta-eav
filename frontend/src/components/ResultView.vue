<script setup>
import { ref, computed } from 'vue'
import { Table2, BarChart3 } from 'lucide-vue-next'
import DataTable from './DataTable.vue'
import PivotTables from './PivotTables.vue'
import ChartView from './ChartView.vue'

const props = defineProps({
  data: { type: Object, required: true },
})

const tab = ref('chart')
const isPivot = computed(() => props.data?.format === 'pivot')
</script>

<template>
  <div class="overflow-hidden">
    <!-- Tab header -->
    <div class="border-b border-surface px-5 py-3 flex gap-8">
      <button
        @click="tab = 'table'"
        class="flex items-center gap-2 pb-2 border-b-2 transition-colors"
        :class="
          tab === 'table'
            ? 'border-brand text-brand'
            : 'border-transparent text-faint'
        "
      >
        <Table2 class="size-3.5" />
        <span class="font-bold text-sm">Tabla</span>
      </button>
      <button
        @click="tab = 'chart'"
        class="flex items-center gap-2 pb-2 border-b-2 transition-colors"
        :class="
          tab === 'chart'
            ? 'border-brand text-brand'
            : 'border-transparent text-faint'
        "
      >
        <BarChart3 class="size-3.5" />
        <span class="font-bold text-sm">Gráfica</span>
      </button>
    </div>

    <!-- Table view -->
    <div v-show="tab === 'table'" class="p-5 space-y-6">
      <PivotTables v-if="isPivot" :data="data" />
      <DataTable v-else :data="data" />
    </div>

    <!-- Chart view -->
    <div v-show="tab === 'chart'" class="p-5">
      <ChartView :data="data" :active="tab === 'chart'" />
    </div>
  </div>
</template>
