<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { io } from "socket.io-client";
import {
  Bot,
  CirclePause,
  ExternalLink,
  GitPullRequest,
  Play,
  Plus,
  RotateCcw,
  Square,
} from "lucide-vue-next";
import AgentEditor from "@/components/AgentEditor.vue";
import ChatLog from "@/components/ChatLog.vue";
import Identicon from "@/components/Identicon.vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";

const status = ref({ repo: "", label: "", agents: [], running: 0 });
const issues = ref([]);
const runs = ref([]);
const messages = ref([]);
const selectedRun = ref(null);
const error = ref("");
const editorOpen = ref(false);
const editing = ref(null);

const selected = computed(() => runs.value.find((r) => r.id === selectedRun.value) || null);

async function api(path, opts) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(detail);
  }
  if (res.status === 204) return {};
  return res.json();
}

async function refresh() {
  const [st, is, rs] = await Promise.all([api("/api/status"), api("/api/issues"), api("/api/runs")]);
  status.value = st;
  issues.value = is.issues || [];
  runs.value = rs.runs || [];
}

async function loadMessages(id) {
  if (!id) {
    messages.value = [];
    return;
  }
  const data = await api(`/api/runs/${id}/messages`);
  messages.value = data.messages || [];
}

async function selectRun(id) {
  selectedRun.value = id;
  await loadMessages(id);
}

async function withError(fn) {
  error.value = "";
  try {
    await fn();
    await refresh();
  } catch (err) {
    error.value = err.message;
  }
}

function openCreate() {
  editing.value = null;
  editorOpen.value = true;
}
function openEdit(agent) {
  editing.value = agent;
  editorOpen.value = true;
}

async function saveAgent(payload) {
  await withError(async () => {
    if (editing.value?.id) {
      await api(`/api/agents/${editing.value.id}`, { method: "PATCH", body: JSON.stringify(payload) });
    } else {
      await api("/api/agents", { method: "POST", body: JSON.stringify(payload) });
    }
    editorOpen.value = false;
  });
}

async function togglePause(agent) {
  await withError(() =>
    api(`/api/agents/${agent.id}`, { method: "PATCH", body: JSON.stringify({ paused: !agent.paused }) }),
  );
}

async function removeAgent(id) {
  await withError(() => api(`/api/agents/${id}`, { method: "DELETE" }));
}

async function runIssue(number) {
  await withError(() => api(`/api/issues/${number}/run`, { method: "POST" }));
}
async function stopRun(id) {
  await withError(() => api(`/api/runs/${id}/stop`, { method: "POST" }));
}
async function requeueRun(id) {
  await withError(() => api(`/api/runs/${id}/requeue`, { method: "POST" }));
}

function statusLabel(agent) {
  if (agent.display_status === "running") return "Working";
  if (agent.display_status === "ooo" || agent.paused) return "Out of office";
  if (agent.display_status === "offline") return "Offline";
  return "Available";
}

function statusClass(value) {
  return {
    running: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    idle: "bg-secondary text-secondary-foreground",
    ooo: "bg-amber-500/15 text-amber-200 border-amber-500/30",
    paused: "bg-amber-500/15 text-amber-200 border-amber-500/30",
    offline: "bg-muted text-muted-foreground",
    queued: "bg-indigo-500/15 text-indigo-200 border-indigo-500/30",
    succeeded: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    failed: "bg-destructive/20 text-red-300 border-destructive/30",
    stopped: "bg-amber-500/15 text-amber-200 border-amber-500/30",
  }[value] || "bg-secondary";
}

let socket;
onMounted(async () => {
  await refresh();
  socket = io({ path: "/socket.io" });
  socket.on("agent.created", refresh);
  socket.on("agent.updated", refresh);
  socket.on("agent.deleted", refresh);
  socket.on("run.updated", refresh);
  socket.on("issue.updated", refresh);
  socket.on("issues.polled", refresh);
  socket.on("run.message", (msg) => {
    if (msg.run_id === selectedRun.value) messages.value = [...messages.value, msg];
  });
});
onUnmounted(() => socket && socket.disconnect());
</script>

<template>
  <div class="min-h-svh bg-background text-foreground">
    <header class="sticky top-0 z-20 border-b bg-card/80 backdrop-blur">
      <div class="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-4 py-3">
        <div class="flex items-center gap-2">
          <Bot class="size-5 text-primary" />
          <div>
            <h1 class="text-base font-semibold leading-none">shatun</h1>
            <p class="text-xs text-muted-foreground">Grok Build floor</p>
          </div>
        </div>
        <Separator orientation="vertical" class="hidden h-8 sm:block" />
        <div class="text-sm">
          <span class="text-muted-foreground">repo</span>
          <span class="ml-2 font-mono">{{ status.repo }}</span>
        </div>
        <Badge variant="outline">{{ status.label }}</Badge>
        <div class="ml-auto text-sm text-muted-foreground">{{ status.running }} working</div>
      </div>
    </header>

    <p v-if="error" class="border-b border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-red-200">
      {{ error }}
    </p>

    <main class="mx-auto grid max-w-[1600px] grid-cols-1 gap-4 p-4 xl:grid-cols-[20rem_minmax(0,1fr)_minmax(20rem,1.25fr)]">
      <Card class="min-h-0">
        <CardHeader class="flex-row items-center justify-between space-y-0">
          <CardTitle class="text-sm">Agents</CardTitle>
          <Button size="sm" @click="openCreate">
            <Plus class="size-4" />
            Add
          </Button>
        </CardHeader>
        <CardContent>
          <ScrollArea class="h-[28rem] xl:h-[calc(100svh-12rem)]">
            <div class="space-y-3 pr-2">
              <article
                v-for="agent in status.agents"
                :key="agent.id"
                class="rounded-xl border p-3"
                :class="agent.paused ? 'opacity-80' : ''"
              >
                <div class="flex items-start gap-3">
                  <Identicon :seed="agent.avatar_seed || agent.id" :size="40" />
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <h3 class="truncate font-medium">{{ agent.name }}</h3>
                      <Badge variant="outline" :class="statusClass(agent.display_status)">
                        {{ statusLabel(agent) }}
                      </Badge>
                    </div>
                    <p class="mt-1 line-clamp-2 text-xs text-muted-foreground">
                      {{ agent.persona || "No persona yet." }}
                    </p>
                    <p class="mt-1 text-[11px] text-muted-foreground">
                      {{ (agent.mcp_servers || []).length }} MCP
                    </p>
                  </div>
                </div>
                <div class="mt-3 flex flex-wrap gap-1.5">
                  <Button size="xs" variant="outline" @click="openEdit(agent)">Edit</Button>
                  <Button size="xs" variant="outline" @click="togglePause(agent)">
                    <CirclePause v-if="!agent.paused" class="size-3" />
                    <Play v-else class="size-3" />
                    {{ agent.paused ? "Back" : "OOO" }}
                  </Button>
                  <Button size="xs" variant="ghost" @click="removeAgent(agent.id)">Remove</Button>
                </div>
              </article>
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      <div class="flex min-h-0 flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle class="text-sm">Issues</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea class="h-48">
              <div v-if="!issues.length" class="text-sm text-muted-foreground">No labeled issues yet.</div>
              <div
                v-for="issue in issues"
                :key="issue.id"
                class="flex items-center gap-3 border-b py-2 last:border-0"
              >
                <span class="w-10 shrink-0 font-mono text-xs text-muted-foreground">#{{ issue.number }}</span>
                <a :href="issue.html_url" class="min-w-0 flex-1 truncate text-sm hover:underline" target="_blank">
                  {{ issue.title }}
                </a>
                <Button size="xs" :disabled="!issue.can_run" @click="runIssue(issue.number)">Run</Button>
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        <Card class="flex-1">
          <CardHeader>
            <CardTitle class="text-sm">Tasks</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea class="h-64 xl:h-[calc(100svh-28rem)]">
              <button
                v-for="run in runs"
                :key="run.id"
                type="button"
                class="flex w-full items-start gap-3 rounded-lg border px-3 py-2 text-left transition-colors hover:bg-accent/40"
                :class="run.id === selectedRun ? 'border-primary/50 bg-accent/50' : ''"
                @click="selectRun(run.id)"
              >
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-xs text-muted-foreground">#{{ run.issue_number }}</span>
                    <p class="truncate text-sm font-medium">{{ run.issue_title }}</p>
                  </div>
                  <p class="mt-1 text-xs text-muted-foreground">
                    {{ run.agent_name || "unassigned" }} · {{ run.phase }}
                  </p>
                </div>
                <Badge variant="outline" :class="statusClass(run.status)">{{ run.status }}</Badge>
                <div class="flex items-center gap-1" @click.stop>
                  <Button v-if="run.pr_url" size="icon-xs" variant="ghost" as-child>
                    <a :href="run.pr_url" target="_blank" rel="noreferrer">
                      <GitPullRequest class="size-3.5" />
                    </a>
                  </Button>
                  <Button size="icon-xs" variant="ghost" :disabled="!run.can_stop" @click="stopRun(run.id)">
                    <Square class="size-3.5" />
                  </Button>
                  <Button size="icon-xs" variant="ghost" :disabled="!run.can_requeue" @click="requeueRun(run.id)">
                    <RotateCcw class="size-3.5" />
                  </Button>
                </div>
              </button>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      <Card class="min-h-[28rem]">
        <CardHeader class="space-y-1">
          <CardTitle class="text-sm">Chat</CardTitle>
          <p v-if="selected" class="text-xs text-muted-foreground">
            #{{ selected.issue_number }} · {{ selected.status }}
            <a v-if="selected.pr_url" :href="selected.pr_url" class="ml-2 inline-flex items-center gap-1" target="_blank">
              PR <ExternalLink class="size-3" />
            </a>
          </p>
        </CardHeader>
        <CardContent class="h-[28rem] xl:h-[calc(100svh-12rem)]">
          <ChatLog :messages="messages" />
        </CardContent>
      </Card>
    </main>

    <Dialog :open="editorOpen" @update:open="editorOpen = $event">
      <DialogContent class="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{{ editing ? `Edit ${editing.name}` : "New agent" }}</DialogTitle>
          <DialogDescription>Persona, standing instructions, and per-agent MCP servers.</DialogDescription>
        </DialogHeader>
        <AgentEditor :agent="editing" @save="saveAgent" @cancel="editorOpen = false" />
      </DialogContent>
    </Dialog>
  </div>
</template>
