<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { io } from "socket.io-client";

const status = ref({ repo: "", label: "", agents: [], running: 0 });
const issues = ref([]);
const runs = ref([]);
const messages = ref([]);
const selectedRun = ref(null);
const newAgent = ref("");
const error = ref("");

const selected = computed(() => runs.value.find((r) => r.id === selectedRun.value) || null);

const chat = computed(() => {
  const out = [];
  for (const msg of messages.value) {
    const prev = out[out.length - 1];
    if (prev && (msg.kind === "message" || msg.kind === "thought") && prev.kind === msg.kind) {
      prev.text = (prev.text || "") + (msg.text || "");
      continue;
    }
    out.push({ ...msg });
  }
  return out;
});

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

async function addAgent() {
  error.value = "";
  try {
    await api("/api/agents", { method: "POST", body: JSON.stringify({ name: newAgent.value }) });
    newAgent.value = "";
    await refresh();
  } catch (err) {
    error.value = err.message;
  }
}

async function removeAgent(id) {
  error.value = "";
  try {
    await api(`/api/agents/${id}`, { method: "DELETE" });
    await refresh();
  } catch (err) {
    error.value = err.message;
  }
}

async function defAction(fn) {
  error.value = "";
  try {
    await fn();
    await refresh();
  } catch (err) {
    error.value = err.message;
  }
}

async function runIssue(number) {
  await defAction(() => api(`/api/issues/${number}/run`, { method: "POST" }));
}
async function stopRun(id) {
  await defAction(() => api(`/api/runs/${id}/stop`, { method: "POST" }));
}
async function requeueRun(id) {
  await defAction(() => api(`/api/runs/${id}/requeue`, { method: "POST" }));
}

function badge(status) {
  return {
    idle: "bg-zinc-800 text-zinc-300",
    running: "bg-emerald-950 text-emerald-300",
    queued: "bg-indigo-950 text-indigo-300",
    succeeded: "bg-emerald-950 text-emerald-300",
    failed: "bg-red-950 text-red-300",
    stopped: "bg-amber-950 text-amber-200",
    offline: "bg-zinc-800 text-zinc-500",
  }[status] || "bg-zinc-800 text-zinc-300";
}

function payloadText(payload) {
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload || "");
  }
}

function kindClass(kind) {
  return {
    thought: "border-violet-800 bg-violet-950/40 text-violet-100",
    message: "border-zinc-700 bg-zinc-900 text-zinc-100",
    tool: "border-sky-800 bg-sky-950/50 text-sky-100",
    tool_update: "border-sky-900 bg-zinc-900 text-sky-200",
    plan: "border-amber-800 bg-amber-950/30 text-amber-100",
    status: "border-zinc-800 bg-zinc-900 text-zinc-400",
    stderr: "border-red-900 bg-red-950/30 text-red-200",
    usage: "border-zinc-800 bg-zinc-900 text-zinc-500",
  }[kind] || "border-zinc-800 bg-zinc-900";
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
  <div class="min-h-screen grid grid-rows-[auto_1fr]">
    <header class="flex flex-wrap items-center gap-6 px-4 py-3 border-b border-zinc-800 bg-zinc-900">
      <div>
        <h1 class="text-lg tracking-wide font-semibold">shatun</h1>
        <p class="text-xs text-zinc-500">Grok Build orchestrator</p>
      </div>
      <div class="font-mono text-sm">
        <span class="text-zinc-500 mr-2">repo</span>{{ status.repo }}
      </div>
      <div class="font-mono text-sm">
        <span class="text-zinc-500 mr-2">label</span>{{ status.label }}
      </div>
      <div class="ml-auto text-sm text-zinc-400">{{ status.running }} running</div>
    </header>

    <p v-if="error" class="px-4 py-2 bg-red-950 text-red-200 text-sm">{{ error }}</p>

    <main class="grid grid-cols-1 lg:grid-cols-[16rem_1fr_1.2fr] gap-3 p-3 min-h-0">
      <section class="rounded-lg border border-zinc-800 bg-zinc-900 p-3 flex flex-col min-h-0">
        <h2 class="text-xs uppercase tracking-widest text-zinc-500 mb-3">Agents</h2>
        <ul class="space-y-2 flex-1 overflow-auto">
          <li v-for="agent in status.agents" :key="agent.id" class="rounded-md border border-zinc-800 p-2">
            <div class="flex items-center justify-between gap-2">
              <strong>{{ agent.name }}</strong>
              <span class="text-[11px] px-2 py-0.5 rounded-full" :class="badge(agent.status)">{{ agent.status }}</span>
            </div>
            <button class="mt-2 text-xs text-red-300 hover:underline" @click="removeAgent(agent.id)">Remove</button>
          </li>
        </ul>
        <form class="mt-3 flex gap-2" @submit.prevent="addAgent">
          <input v-model="newAgent" class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm" placeholder="New agent" />
          <button class="px-2 py-1 text-sm rounded bg-zinc-800 hover:bg-zinc-700">Add</button>
        </form>
      </section>

      <section class="rounded-lg border border-zinc-800 bg-zinc-900 p-3 flex flex-col min-h-0 gap-4">
        <div class="min-h-0 overflow-auto">
          <h2 class="text-xs uppercase tracking-widest text-zinc-500 mb-2">Issues</h2>
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="issue in issues" :key="issue.id" class="border-b border-zinc-800">
                <td class="py-2 pr-2 whitespace-nowrap">#{{ issue.number }}</td>
                <td class="py-2 pr-2">
                  <a :href="issue.html_url" class="text-sky-300 hover:underline" target="_blank">{{ issue.title }}</a>
                </td>
                <td class="py-2 text-right">
                  <button class="px-2 py-0.5 rounded bg-zinc-800 disabled:opacity-40" :disabled="!issue.can_run" @click="runIssue(issue.number)">Run</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="min-h-0 overflow-auto flex-1">
          <h2 class="text-xs uppercase tracking-widest text-zinc-500 mb-2">Tasks</h2>
          <table class="w-full text-sm">
            <tbody>
              <tr
                v-for="run in runs"
                :key="run.id"
                class="border-b border-zinc-800 cursor-pointer"
                :class="run.id === selectedRun ? 'bg-zinc-800/70' : ''"
                @click="selectRun(run.id)"
              >
                <td class="py-2 pr-2 whitespace-nowrap">#{{ run.issue_number }}</td>
                <td class="py-2 pr-2">
                  <div>{{ run.issue_title }}</div>
                  <div class="text-xs text-zinc-500">{{ run.agent_name || "unassigned" }} · {{ run.phase }}</div>
                </td>
                <td class="py-2 pr-2">
                  <span class="text-[11px] px-2 py-0.5 rounded-full" :class="badge(run.status)">{{ run.status }}</span>
                </td>
                <td class="py-2 text-right whitespace-nowrap">
                  <a v-if="run.pr_url" :href="run.pr_url" class="text-sky-300 mr-2" target="_blank" @click.stop>PR</a>
                  <button class="px-2 py-0.5 rounded bg-zinc-800 disabled:opacity-40 mr-1" :disabled="!run.can_stop" @click.stop="stopRun(run.id)">Stop</button>
                  <button class="px-2 py-0.5 rounded bg-zinc-800 disabled:opacity-40" :disabled="!run.can_requeue" @click.stop="requeueRun(run.id)">Requeue</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="rounded-lg border border-zinc-800 bg-zinc-900 p-3 flex flex-col min-h-[24rem]">
        <h2 class="text-xs uppercase tracking-widest text-zinc-500 mb-2">
          Chat
          <span v-if="selected" class="normal-case tracking-normal text-zinc-400">
            · #{{ selected.issue_number }} · {{ selected.status }}
          </span>
        </h2>
        <div class="flex-1 overflow-auto chat-scroll space-y-2 font-mono text-xs">
          <p v-if="!selected" class="text-zinc-500">Select a task.</p>
          <article
            v-for="msg in chat"
            :key="msg.id"
            class="rounded-md border px-2 py-2 whitespace-pre-wrap break-words"
            :class="kindClass(msg.kind)"
          >
            <div class="flex justify-between gap-2 mb-1 text-[10px] uppercase tracking-wider opacity-70">
              <span>{{ msg.kind }}{{ msg.title ? " · " + msg.title : "" }}{{ msg.status ? " · " + msg.status : "" }}</span>
              <span>{{ msg.created_at }}</span>
            </div>
            <div>{{ msg.text || payloadText(msg.payload) }}</div>
          </article>
        </div>
      </section>
    </main>
  </div>
</template>
