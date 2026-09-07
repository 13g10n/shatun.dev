<script setup>
import { computed, reactive, watch } from "vue";
import { Plus, Trash2 } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import Identicon from "./Identicon.vue";

const props = defineProps({
  agent: { type: Object, default: null },
});
const emit = defineEmits(["save", "cancel"]);

const blankMcp = () => ({ type: "stdio", name: "", command: "", args: "", url: "", env: "" });

const form = reactive({
  name: "",
  persona: "",
  instructions: "",
  paused: false,
  avatar_seed: "",
  mcp_servers: [],
});

watch(
  () => props.agent,
  (agent) => {
    form.name = agent?.name || "";
    form.persona = agent?.persona || "";
    form.instructions = agent?.instructions || "";
    form.paused = Boolean(agent?.paused);
    form.avatar_seed = agent?.avatar_seed || Math.random().toString(16).slice(2, 10);
    form.mcp_servers = (agent?.mcp_servers || []).map((item) => ({
      type: item.type || "stdio",
      name: item.name || "",
      command: item.command || "",
      args: Array.isArray(item.args) ? item.args.join(" ") : item.args || "",
      url: item.url || "",
      env: Array.isArray(item.env)
        ? item.env.map((row) => `${row.name}=${row.value || ""}`).join("\n")
        : item.env || "",
    }));
  },
  { immediate: true },
);

const title = computed(() => (props.agent?.id ? `Edit ${props.agent.name}` : "New agent"));

function addMcp() {
  form.mcp_servers.push(blankMcp());
}
function removeMcp(index) {
  form.mcp_servers.splice(index, 1);
}

function parseEnv(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf("=");
      if (idx < 0) return { name: line, value: "" };
      return { name: line.slice(0, idx), value: line.slice(idx + 1) };
    });
}

function save() {
  emit("save", {
    name: form.name.trim(),
    persona: form.persona,
    instructions: form.instructions,
    paused: form.paused,
    avatar_seed: form.avatar_seed,
    mcp_servers: form.mcp_servers
      .filter((item) => item.name.trim())
      .map((item) => ({
        type: item.type,
        name: item.name.trim(),
        command: item.command.trim(),
        args: item.args.trim() ? item.args.trim().split(/\s+/) : [],
        url: item.url.trim(),
        env: parseEnv(item.env),
      })),
  });
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="save">
    <div class="flex items-center gap-3">
      <Identicon :seed="form.avatar_seed || form.name" :size="48" />
      <div class="flex-1 space-y-1">
        <Label>Name</Label>
        <Input v-model="form.name" required placeholder="Bob" />
      </div>
    </div>
    <div class="flex items-center justify-between rounded-lg border px-3 py-2">
      <div>
        <p class="text-sm font-medium">Out of office</p>
        <p class="text-xs text-muted-foreground">Paused agents skip the queue.</p>
      </div>
      <Switch :model-value="form.paused" @update:model-value="form.paused = $event" />
    </div>
    <div class="space-y-1">
      <Label>Persona</Label>
      <Textarea v-model="form.persona" rows="3" placeholder="Who this agent is." />
    </div>
    <div class="space-y-1">
      <Label>Instructions</Label>
      <Textarea v-model="form.instructions" rows="4" placeholder="Standing rules for every task." />
    </div>
    <div class="space-y-2">
      <div class="flex items-center justify-between">
        <Label>MCP servers</Label>
        <Button type="button" size="sm" variant="outline" @click="addMcp">
          <Plus class="size-4" />
          Add
        </Button>
      </div>
      <p class="text-xs text-muted-foreground">Each agent gets its own MCP list on session/new.</p>
      <div v-for="(mcp, index) in form.mcp_servers" :key="index" class="space-y-2 rounded-lg border p-3">
        <div class="flex gap-2">
          <select v-model="mcp.type" class="h-9 rounded-md border bg-background px-2 text-sm">
            <option value="stdio">stdio</option>
            <option value="http">http</option>
            <option value="sse">sse</option>
          </select>
          <Input v-model="mcp.name" placeholder="name" />
          <Button type="button" size="icon" variant="ghost" @click="removeMcp(index)">
            <Trash2 class="size-4" />
          </Button>
        </div>
        <Input v-if="mcp.type === 'stdio'" v-model="mcp.command" placeholder="command, e.g. npx" />
        <Input v-if="mcp.type === 'stdio'" v-model="mcp.args" placeholder="args, space-separated" />
        <Input v-if="mcp.type !== 'stdio'" v-model="mcp.url" placeholder="https://..." />
        <Textarea v-model="mcp.env" rows="2" placeholder="ENV_NAME=value, one per line" />
      </div>
    </div>
    <div class="flex justify-end gap-2">
      <Button type="button" variant="ghost" @click="emit('cancel')">Cancel</Button>
      <Button type="submit">{{ title.startsWith('Edit') ? 'Save' : 'Create' }}</Button>
    </div>
  </form>
</template>
