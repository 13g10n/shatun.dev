<script setup>
import { computed } from "vue";

const props = defineProps({
  seed: { type: String, default: "bob" },
  size: { type: Number, default: 40 },
});

function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

const palette = ["#eb6d6f", "#6db6eb", "#6deb9a", "#ebc86d", "#b06deb", "#5fd4d4", "#eb8f5f"];

const model = computed(() => {
  let n = hash(String(props.seed || "agent"));
  const color = palette[n % palette.length];
  n = Math.floor(n / palette.length);
  const cells = [];
  for (let y = 0; y < 5; y += 1) {
    const cols = [];
    for (let x = 0; x < 3; x += 1) {
      cols.push(Boolean(n & 1));
      n >>>= 1;
    }
    cells.push([cols[0], cols[1], cols[2], cols[1], cols[0]]);
  }
  return { color, cells };
});
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 5 5"
    shape-rendering="crispEdges"
    class="rounded-md shrink-0 bg-black/40"
    role="img"
    :aria-label="`Avatar for ${seed}`"
  >
    <rect width="5" height="5" fill="#111318" />
    <template v-for="(row, y) in model.cells" :key="y">
      <rect
        v-for="(on, x) in row"
        :key="`${y}-${x}`"
        v-show="on"
        :x="x"
        :y="y"
        width="1"
        height="1"
        :fill="model.color"
      />
    </template>
  </svg>
</template>
