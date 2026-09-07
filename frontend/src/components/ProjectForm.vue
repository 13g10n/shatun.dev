<script setup>
import { reactive, watch } from "vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const props = defineProps({
  project: { type: Object, default: null },
});
const emit = defineEmits(["save", "cancel"]);

const form = reactive({ title: "", repo: "", label: "agent" });

watch(
  () => props.project,
  (project) => {
    form.title = project?.title || "";
    form.repo = project?.repo || "";
    form.label = project?.label || "agent";
  },
  { immediate: true },
);

function save() {
  emit("save", {
    title: form.title.trim(),
    repo: form.repo.trim(),
    label: form.label.trim() || "agent",
  });
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="save">
    <div class="space-y-1.5">
      <Label for="project-title">Title</Label>
      <Input id="project-title" v-model="form.title" placeholder="Architecture tests" required />
    </div>
    <div class="space-y-1.5">
      <Label for="project-repo">GitHub repo</Label>
      <Input id="project-repo" v-model="form.repo" placeholder="owner/name" required class="font-mono" />
    </div>
    <div class="space-y-1.5">
      <Label for="project-label">Issue label</Label>
      <Input id="project-label" v-model="form.label" placeholder="agent" />
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <Button type="button" variant="ghost" @click="emit('cancel')">Cancel</Button>
      <Button type="submit">{{ project?.id ? "Save" : "Create project" }}</Button>
    </div>
  </form>
</template>
