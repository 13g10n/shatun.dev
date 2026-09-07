<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { io } from "socket.io-client";
import {
  ArrowLeft,
  ExternalLink,
  GitPullRequest,
  MoreHorizontal,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Settings2,
  Square,
} from "lucide-vue-next";
import AgentEditor from "@/components/AgentEditor.vue";
import ChatLog from "@/components/ChatLog.vue";
import Identicon from "@/components/Identicon.vue";
import ProjectForm from "@/components/ProjectForm.vue";
import SettingsForm from "@/components/SettingsForm.vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { agentLabel, statusDot, taskLabel } from "@/lib/status";

const settings = ref({});
const projects = ref([]);
const agents = ref([]);
const tasks = ref([]);
const messages = ref([]);
const taskDetail = ref(null);
const selectedProject = ref(null);
const selectedAgent = ref(null);
const selectedTask = ref(null);
const selectedRun = ref(null);
const error = ref("");
const editorOpen = ref(false);
const editing = ref(null);
const projectOpen = ref(false);
const editingProject = ref(null);
const settingsOpen = ref(false);
const desktop = ref(true);
const mobileLevel = ref("projects");

const project = computed(() => projects.value.find((p) => p.id === selectedProject.value) || null);
const agent = computed(() => agents.value.find((a) => a.id === selectedAgent.value) || null);
const task = computed(() => tasks.value.find((t) => t.id === selectedTask.value) || taskDetail.value);
const selectedRunView = computed(() => {
  const runs = taskDetail.value?.runs || [];
  return runs.find((r) => r.id === selectedRun.value) || task.value?.latest_run || null;
});

function parseHash() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const out = { projectId: null, agentId: null, taskId: null, runId: null };
  for (let i = 0; i < parts.length; i += 2) {
    const key = parts[i];
    const val = parts[i + 1];
    if (key === "p") out.projectId = val;
    if (key === "a") out.agentId = val;
    if (key === "t") out.taskId = val;
    if (key === "r") out.runId = val;
  }
  return out;
}

function writeHash() {
  const bits = [];
  if (selectedProject.value) bits.push("p", selectedProject.value);
  if (selectedAgent.value) bits.push("a", selectedAgent.value);
  if (selectedTask.value) bits.push("t", selectedTask.value);
  if (selectedRun.value) bits.push("r", selectedRun.value);
  const next = bits.length ? `#/${bits.join("/")}` : "#/";
  if (location.hash !== next) history.replaceState(null, "", next);
}

function applyHash() {
  const parsed = parseHash();
  selectedProject.value = parsed.projectId;
  selectedAgent.value = parsed.agentId;
  selectedTask.value = parsed.taskId;
  selectedRun.value = parsed.runId;
  if (parsed.taskId) mobileLevel.value = "details";
  else if (parsed.agentId || parsed.projectId) mobileLevel.value = parsed.agentId ? "tasks" : "agents";
  else mobileLevel.value = "projects";
}

function updateDesktop() {
  desktop.value = window.matchMedia("(min-width: 1024px)").matches;
}

async function withError(fn) {
  error.value = "";
  try {
    await fn();
  } catch (err) {
    error.value = err.message;
  }
}

async function loadProjects() {
  const [st, data] = await Promise.all([api("/api/status"), api("/api/projects")]);
  settings.value = st.settings || {};
  projects.value = data.projects || [];
}

async function loadAgents() {
  if (!selectedProject.value) {
    agents.value = [];
    return;
  }
  const data = await api(`/api/projects/${selectedProject.value}/agents`);
  agents.value = data.agents || [];
}

async function loadTasks() {
  if (!selectedProject.value) {
    tasks.value = [];
    return;
  }
  const q = selectedAgent.value ? `?agent_id=${selectedAgent.value}` : "";
  const data = await api(`/api/projects/${selectedProject.value}/tasks${q}`);
  tasks.value = data.tasks || [];
}

async function loadTaskDetail() {
  if (!selectedProject.value || !selectedTask.value) {
    taskDetail.value = null;
    messages.value = [];
    return;
  }
  const data = await api(`/api/projects/${selectedProject.value}/issues/${selectedTask.value}`);
  taskDetail.value = data;
  const runId = selectedRun.value || data.latest_run_id;
  if (runId && runId !== selectedRun.value) selectedRun.value = runId;
  if (runId) {
    const msg = await api(`/api/runs/${runId}/messages`);
    messages.value = msg.messages || [];
  } else {
    messages.value = [];
  }
}

async function refresh() {
  await loadProjects();
  await loadAgents();
  await loadTasks();
  if (selectedTask.value) await loadTaskDetail();
}

function selectProject(id) {
  selectedProject.value = id;
  selectedAgent.value = null;
  selectedTask.value = null;
  selectedRun.value = null;
  taskDetail.value = null;
  messages.value = [];
  mobileLevel.value = "agents";
  writeHash();
}

function selectAgent(id) {
  selectedAgent.value = id;
  selectedTask.value = null;
  selectedRun.value = null;
  taskDetail.value = null;
  messages.value = [];
  mobileLevel.value = "tasks";
  writeHash();
}

function selectTask(id) {
  selectedTask.value = id;
  const found = tasks.value.find((t) => t.id === id);
  selectedRun.value = found?.latest_run_id || null;
  mobileLevel.value = "details";
  writeHash();
}

function selectRun(id) {
  selectedRun.value = id;
  writeHash();
}

function mobileBack() {
  if (mobileLevel.value === "details") {
    selectedTask.value = null;
    selectedRun.value = null;
    taskDetail.value = null;
    messages.value = [];
    mobileLevel.value = "tasks";
  } else if (mobileLevel.value === "tasks") {
    selectedAgent.value = null;
    mobileLevel.value = "agents";
  } else if (mobileLevel.value === "agents") {
    selectedProject.value = null;
    agents.value = [];
    tasks.value = [];
    mobileLevel.value = "projects";
  }
  writeHash();
}

function openCreateProject() {
  editingProject.value = null;
  projectOpen.value = true;
}
function openEditProject(item) {
  editingProject.value = item;
  projectOpen.value = true;
}
function openCreateAgent() {
  editing.value = null;
  editorOpen.value = true;
}
function openEditAgent(item) {
  editing.value = item;
  editorOpen.value = true;
}

async function saveProject(payload) {
  await withError(async () => {
    if (editingProject.value?.id) {
      await api(`/api/projects/${editingProject.value.id}`, { method: "PATCH", body: JSON.stringify(payload) });
    } else {
      const created = await api("/api/projects", { method: "POST", body: JSON.stringify(payload) });
      selectedProject.value = created.id;
      mobileLevel.value = "agents";
    }
    projectOpen.value = false;
    await refresh();
    writeHash();
  });
}

async function saveSettings(payload) {
  await withError(async () => {
    settings.value = await api("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
    settingsOpen.value = false;
  });
}

async function saveAgent(payload) {
  await withError(async () => {
    if (!selectedProject.value && !editing.value?.id) throw new Error("Select a project first");
    if (editing.value?.id) {
      await api(`/api/agents/${editing.value.id}`, { method: "PATCH", body: JSON.stringify(payload) });
    } else {
      await api(`/api/projects/${selectedProject.value}/agents`, { method: "POST", body: JSON.stringify(payload) });
    }
    editorOpen.value = false;
    await refresh();
  });
}

async function togglePause(item) {
  await withError(() =>
    api(`/api/agents/${item.id}`, { method: "PATCH", body: JSON.stringify({ paused: !item.paused }) }),
  );
  await loadAgents();
}

async function removeAgent(id) {
  await withError(() => api(`/api/agents/${id}`, { method: "DELETE" }));
  if (selectedAgent.value === id) selectAgent(null);
  await refresh();
}

async function removeProject(id) {
  await withError(() => api(`/api/projects/${id}`, { method: "DELETE" }));
  if (selectedProject.value === id) {
    selectedProject.value = null;
    selectedAgent.value = null;
    selectedTask.value = null;
    mobileLevel.value = "projects";
    writeHash();
  }
  await refresh();
}

async function pollProject() {
  if (!selectedProject.value) return;
  await withError(() => api(`/api/projects/${selectedProject.value}/poll`, { method: "POST" }));
  await refresh();
}

async function runTask(number) {
  await withError(() =>
    api(`/api/projects/${selectedProject.value}/tasks/${number}/run`, { method: "POST" }),
  );
  await refresh();
}

async function stopRun(id) {
  await withError(() => api(`/api/runs/${id}/stop`, { method: "POST" }));
  await refresh();
}

async function requeueRun(id) {
  await withError(() => api(`/api/runs/${id}/requeue`, { method: "POST" }));
  await refresh();
}

function paneVisible(name) {
  if (desktop.value) return true;
  return mobileLevel.value === name;
}

watch([selectedProject, selectedAgent], async () => {
  await loadAgents();
  await loadTasks();
});

watch([selectedTask, selectedRun], async () => {
  if (selectedTask.value) await loadTaskDetail();
});

let socket;
onMounted(async () => {
  updateDesktop();
  window.addEventListener("resize", updateDesktop);
  window.addEventListener("hashchange", applyHash);
  applyHash();
  await refresh();
  socket = io({ path: "/socket.io" });
  const reload = () => refresh();
  socket.on("agent.created", reload);
  socket.on("agent.updated", reload);
  socket.on("agent.deleted", reload);
  socket.on("project.created", reload);
  socket.on("project.updated", reload);
  socket.on("project.deleted", reload);
  socket.on("run.updated", reload);
  socket.on("issue.updated", reload);
  socket.on("issues.polled", reload);
  socket.on("settings.updated", reload);
  socket.on("run.message", (msg) => {
    if (msg.run_id === selectedRun.value) messages.value = [...messages.value, msg];
  });
});
onUnmounted(() => {
  window.removeEventListener("resize", updateDesktop);
  window.removeEventListener("hashchange", applyHash);
  if (socket) socket.disconnect();
});
</script>

<template>
  <TooltipProvider>
    <div class="flex h-full flex-col bg-background text-foreground">
      <header class="flex h-12 shrink-0 items-center gap-3 border-b px-3">
        <Button
          v-if="!desktop && mobileLevel !== 'projects'"
          size="icon-xs"
          variant="ghost"
          @click="mobileBack"
        >
          <ArrowLeft class="size-4" />
        </Button>
        <div class="flex items-center gap-2">
          <span class="size-2 rounded-full bg-foreground/80" />
          <h1 class="text-sm font-medium tracking-tight">shatun</h1>
        </div>
        <nav class="hidden min-w-0 items-center gap-1.5 text-xs text-muted-foreground sm:flex">
          <span v-if="project" class="truncate">{{ project.title }}</span>
          <span v-if="agent">/</span>
          <span v-if="agent" class="truncate text-foreground">{{ agent.name }}</span>
          <span v-if="task">/</span>
          <span v-if="task" class="truncate">#{{ task.number }}</span>
        </nav>
        <div class="ml-auto flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger as-child>
              <Button size="icon-xs" variant="ghost" @click="settingsOpen = true">
                <Settings2 class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Settings</TooltipContent>
          </Tooltip>
        </div>
      </header>

      <p v-if="error" class="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-red-200">
        {{ error }}
      </p>

      <div class="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[13.5rem_16rem_20rem_minmax(0,1fr)]">
        <section
          v-show="paneVisible('projects')"
          class="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r"
        >
          <div class="flex h-10 items-center justify-between px-3">
            <h2 class="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Projects</h2>
            <Button size="icon-xs" variant="ghost" @click="openCreateProject">
              <Plus class="size-3.5" />
            </Button>
          </div>
          <ScrollArea class="min-h-0 flex-1">
            <div v-if="!projects.length" class="px-3 py-10 text-center">
              <p class="text-sm text-muted-foreground">No projects yet.</p>
              <Button size="sm" class="mt-3" @click="openCreateProject">Create project</Button>
            </div>
            <button
              v-for="item in projects"
              :key="item.id"
              type="button"
              class="flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-accent/40"
              :class="item.id === selectedProject ? 'bg-accent/50' : ''"
              @click="selectProject(item.id)"
            >
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full" :class="item.running ? 'bg-emerald-400' : 'bg-zinc-600'" />
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <p class="truncate text-sm">{{ item.title }}</p>
                  <DropdownMenu>
                    <DropdownMenuTrigger as-child @click.stop>
                      <Button size="icon-xs" variant="ghost" class="ml-auto opacity-50 hover:opacity-100">
                        <MoreHorizontal class="size-3.5" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem @click="openEditProject(item)">Edit</DropdownMenuItem>
                      <DropdownMenuItem @click="selectProject(item.id); pollProject()">Poll issues</DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem class="text-red-300" @click="removeProject(item.id)">Delete</DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <p class="truncate font-mono text-[11px] text-muted-foreground">{{ item.repo }}</p>
              </div>
            </button>
          </ScrollArea>
        </section>

        <section
          v-show="paneVisible('agents')"
          class="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r"
        >
          <div class="flex h-10 items-center justify-between px-3">
            <h2 class="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Agents</h2>
            <Button size="icon-xs" variant="ghost" :disabled="!project" @click="openCreateAgent">
              <Plus class="size-3.5" />
            </Button>
          </div>
          <ScrollArea class="min-h-0 flex-1">
            <div v-if="!project" class="px-3 py-8 text-center text-sm text-muted-foreground">Select a project.</div>
            <template v-else>
              <button
                type="button"
                class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent/40"
                :class="!selectedAgent ? 'bg-accent/50' : ''"
                @click="selectAgent(null); mobileLevel = 'tasks'; writeHash()"
              >
                <span class="size-6 rounded-md bg-muted" />
                <span>All agents</span>
              </button>
              <button
                v-for="item in agents"
                :key="item.id"
                type="button"
                class="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-accent/40"
                :class="item.id === selectedAgent ? 'bg-accent/50' : ''"
                @click="selectAgent(item.id)"
              >
                <Identicon :seed="item.avatar_seed || item.id" :size="24" />
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <p class="truncate text-sm">{{ item.name }}</p>
                    <span class="ml-auto size-1.5 rounded-full" :class="statusDot(item.display_status)" />
                  </div>
                  <p class="truncate text-[11px] text-muted-foreground">{{ agentLabel(item) }}</p>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger as-child @click.stop>
                    <Button size="icon-xs" variant="ghost" class="opacity-50 hover:opacity-100">
                      <MoreHorizontal class="size-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem @click="openEditAgent(item)">Edit</DropdownMenuItem>
                    <DropdownMenuItem @click="togglePause(item)">
                      {{ item.paused ? "Back from OOO" : "Out of office" }}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem class="text-red-300" @click="removeAgent(item.id)">Remove</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </button>
            </template>
          </ScrollArea>
        </section>

        <section
          v-show="paneVisible('tasks')"
          class="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r"
        >
          <div class="flex h-10 items-center justify-between px-3">
            <h2 class="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Tasks</h2>
            <Button size="icon-xs" variant="ghost" :disabled="!project" @click="pollProject">
              <RefreshCw class="size-3.5" />
            </Button>
          </div>
          <ScrollArea class="min-h-0 flex-1">
            <div v-if="!project" class="px-3 py-8 text-center text-sm text-muted-foreground">Select a project.</div>
            <div v-else-if="!tasks.length" class="px-3 py-8 text-center text-sm text-muted-foreground">
              No labeled issues yet.
            </div>
            <button
              v-for="item in tasks"
              :key="item.id"
              type="button"
              class="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-accent/40"
              :class="item.id === selectedTask ? 'bg-accent/50' : ''"
              @click="selectTask(item.id)"
            >
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full" :class="statusDot(item.task_status)" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm">{{ item.title }}</p>
                <p class="mt-0.5 font-mono text-[11px] text-muted-foreground">
                  #{{ item.number }} · {{ taskLabel(item.task_status) }}
                  <span v-if="item.latest_run?.agent_name"> · {{ item.latest_run.agent_name }}</span>
                </p>
              </div>
            </button>
          </ScrollArea>
        </section>

        <section v-show="paneVisible('details')" class="flex min-h-0 flex-col">
          <div v-if="!task" class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            Select a task.
          </div>
          <template v-else>
            <div class="border-b px-5 py-4">
              <div class="flex items-start gap-3">
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="font-mono text-xs text-muted-foreground">#{{ task.number }}</span>
                    <Badge variant="outline" class="capitalize">{{ taskLabel(task.task_status) }}</Badge>
                    <a
                      v-if="task.html_url"
                      :href="task.html_url"
                      target="_blank"
                      rel="noreferrer"
                      class="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      GitHub <ExternalLink class="size-3" />
                    </a>
                    <a
                      v-if="selectedRunView?.pr_url"
                      :href="selectedRunView.pr_url"
                      target="_blank"
                      rel="noreferrer"
                      class="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      <GitPullRequest class="size-3" /> PR
                    </a>
                  </div>
                  <h3 class="mt-1 text-base font-medium tracking-tight">{{ task.title }}</h3>
                  <p v-if="task.body" class="mt-2 line-clamp-4 text-sm leading-6 text-muted-foreground">
                    {{ task.body }}
                  </p>
                </div>
                <div class="flex shrink-0 items-center gap-1">
                  <Button size="sm" :disabled="!task.can_run" @click="runTask(task.number)">
                    <Play class="size-3.5" />
                    Run
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    :disabled="!selectedRunView?.can_stop"
                    @click="stopRun(selectedRunView.id)"
                  >
                    <Square class="size-3.5" />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    :disabled="!selectedRunView?.can_requeue"
                    @click="requeueRun(selectedRunView.id)"
                  >
                    <RotateCcw class="size-3.5" />
                  </Button>
                </div>
              </div>
              <div v-if="taskDetail?.runs?.length" class="mt-3 flex flex-wrap gap-1.5">
                <button
                  v-for="run in taskDetail.runs"
                  :key="run.id"
                  type="button"
                  class="rounded-md border px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent/50"
                  :class="run.id === selectedRun ? 'border-foreground/30 bg-accent text-foreground' : ''"
                  @click="selectRun(run.id)"
                >
                  {{ run.agent_name || "unassigned" }} · {{ run.status }}
                </button>
              </div>
            </div>
            <div class="min-h-0 flex-1 px-4 py-3">
              <ChatLog :messages="messages" empty="No transcript yet. Run this task to start a session." />
            </div>
          </template>
        </section>
      </div>
    </div>

    <Dialog :open="projectOpen" @update:open="projectOpen = $event">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{{ editingProject ? "Edit project" : "New project" }}</DialogTitle>
          <DialogDescription>Title and GitHub repository this floor should work on.</DialogDescription>
        </DialogHeader>
        <ProjectForm :project="editingProject" @save="saveProject" @cancel="projectOpen = false" />
      </DialogContent>
    </Dialog>

    <Dialog :open="editorOpen" @update:open="editorOpen = $event">
      <DialogContent class="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{{ editing ? `Edit ${editing.name}` : "New agent" }}</DialogTitle>
          <DialogDescription>Persona, standing instructions, and per-agent MCP servers.</DialogDescription>
        </DialogHeader>
        <AgentEditor :agent="editing" @save="saveAgent" @cancel="editorOpen = false" />
      </DialogContent>
    </Dialog>

    <Sheet :open="settingsOpen" @update:open="settingsOpen = $event">
      <SheetContent class="overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Settings</SheetTitle>
          <SheetDescription>Stored in the database. Bind address and Postgres URL stay on the process environment.</SheetDescription>
        </SheetHeader>
        <div class="px-4 pb-6">
          <SettingsForm :settings="settings" @save="saveSettings" @cancel="settingsOpen = false" />
        </div>
      </SheetContent>
    </Sheet>
  </TooltipProvider>
</template>
