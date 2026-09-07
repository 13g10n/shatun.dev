<script setup>
import { reactive, watch } from "vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const props = defineProps({
  settings: { type: Object, default: null },
});
const emit = defineEmits(["save", "cancel"]);

const form = reactive({
  grok_bin: "grok",
  grok_args: "agent --always-approve --no-leader stdio",
  xai_api_key: "",
  poll_seconds: 60,
  scheduler_seconds: 5,
  run_timeout_sec: 2700,
  default_agent_name: "Bob",
});

watch(
  () => props.settings,
  (settings) => {
    if (!settings) return;
    form.grok_bin = settings.grok_bin || "grok";
    form.grok_args = (settings.grok_args || []).join(" ");
    form.xai_api_key = settings.xai_api_key || "";
    form.poll_seconds = settings.poll_seconds ?? 60;
    form.scheduler_seconds = settings.scheduler_seconds ?? 5;
    form.run_timeout_sec = settings.run_timeout_sec ?? 2700;
    form.default_agent_name = settings.default_agent_name || "Bob";
  },
  { immediate: true },
);

function save() {
  emit("save", {
    grok_bin: form.grok_bin.trim() || "grok",
    grok_args: form.grok_args.trim().split(/\s+/).filter(Boolean),
    xai_api_key: form.xai_api_key,
    poll_seconds: Number(form.poll_seconds),
    scheduler_seconds: Number(form.scheduler_seconds),
    run_timeout_sec: Number(form.run_timeout_sec),
    default_agent_name: form.default_agent_name.trim() || "Bob",
  });
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="save">
    <div class="space-y-1.5">
      <Label>Grok binary</Label>
      <Input v-model="form.grok_bin" class="font-mono" />
    </div>
    <div class="space-y-1.5">
      <Label>Grok args</Label>
      <Input v-model="form.grok_args" class="font-mono text-xs" />
    </div>
    <div class="space-y-1.5">
      <Label>xAI API key</Label>
      <Input v-model="form.xai_api_key" type="password" placeholder="Leave empty to use cached_token" />
    </div>
    <div class="grid grid-cols-3 gap-3">
      <div class="space-y-1.5">
        <Label>Poll (s)</Label>
        <Input v-model="form.poll_seconds" type="number" min="5" />
      </div>
      <div class="space-y-1.5">
        <Label>Schedule (s)</Label>
        <Input v-model="form.scheduler_seconds" type="number" min="1" />
      </div>
      <div class="space-y-1.5">
        <Label>Timeout (s)</Label>
        <Input v-model="form.run_timeout_sec" type="number" min="30" />
      </div>
    </div>
    <div class="space-y-1.5">
      <Label>Default agent</Label>
      <Input v-model="form.default_agent_name" />
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <Button type="button" variant="ghost" @click="emit('cancel')">Cancel</Button>
      <Button type="submit">Save settings</Button>
    </div>
  </form>
</template>
