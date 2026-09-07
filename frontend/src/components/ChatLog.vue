<script setup>
import { computed } from "vue";
import { Brain, ChevronRight, Terminal, Wrench } from "lucide-vue-next";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";

const props = defineProps({
  messages: { type: Array, default: () => [] },
  empty: { type: String, default: "Select a task to read the transcript." },
});

const blocks = computed(() => {
  const out = [];
  for (const msg of props.messages) {
    if (msg.kind === "message" || msg.kind === "thought") {
      const prev = out[out.length - 1];
      if (prev && prev.kind === msg.kind) {
        prev.text += msg.text || "";
        continue;
      }
      out.push({ kind: msg.kind, id: msg.id, text: msg.text || "", created_at: msg.created_at });
      continue;
    }
    if (msg.kind === "tool" || msg.kind === "tool_update") {
      const key = msg.tool_call_id || msg.id;
      let block = out.find((item) => item.kind === "tool" && item.tool_call_id === key);
      if (!block) {
        block = {
          kind: "tool",
          id: msg.id,
          tool_call_id: key,
          title: msg.title || "Tool",
          status: msg.status || "pending",
          input: "",
          output: "",
        };
        out.push(block);
      }
      if (msg.kind === "tool") {
        block.title = msg.title || block.title;
        block.input = msg.text || block.input;
        block.status = msg.status || block.status;
      } else {
        block.status = msg.status || block.status;
        if (msg.title) block.title = msg.title;
        block.output = (block.output || "") + (msg.text ? `${msg.text}\n` : "");
      }
      continue;
    }
    out.push({ ...msg });
  }
  return out;
});
</script>

<template>
  <ScrollArea class="h-full">
    <div class="space-y-3 p-1 pr-3">
      <p v-if="!blocks.length" class="text-sm text-muted-foreground">{{ empty }}</p>
      <template v-for="block in blocks" :key="block.id">
        <article v-if="block.kind === 'message'" class="rounded-lg border bg-card px-3 py-2">
          <div class="chat-text text-sm leading-6">{{ block.text }}</div>
        </article>

        <Collapsible v-else-if="block.kind === 'thought'" :default-open="false">
          <article class="rounded-lg border border-violet-900/50 bg-violet-950/20">
            <CollapsibleTrigger class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-violet-200">
              <Brain class="size-4" />
              <span class="font-medium">Thought</span>
              <ChevronRight class="ml-auto size-4 transition-transform [[data-state=open]_&]:rotate-90" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div class="chat-text border-t border-violet-900/40 px-3 py-2 text-sm leading-6 text-violet-100/90">
                {{ block.text }}
              </div>
            </CollapsibleContent>
          </article>
        </Collapsible>

        <Collapsible v-else-if="block.kind === 'tool'" :default-open="false">
          <article class="rounded-lg border border-sky-900/50 bg-sky-950/20">
            <CollapsibleTrigger class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm">
              <Wrench class="size-4 text-sky-300" />
              <span class="font-medium truncate">{{ block.title }}</span>
              <Badge variant="secondary" class="ml-auto capitalize">{{ block.status }}</Badge>
              <ChevronRight class="size-4 transition-transform [[data-state=open]_&]:rotate-90" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div class="space-y-2 border-t border-sky-900/40 px-3 py-2">
                <div v-if="block.input">
                  <p class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Input</p>
                  <pre class="chat-text overflow-x-auto rounded-md bg-black/30 p-2 text-xs">{{ block.input }}</pre>
                </div>
                <div v-if="block.output">
                  <p class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Result</p>
                  <pre class="chat-text overflow-x-auto rounded-md bg-black/30 p-2 text-xs">{{ block.output }}</pre>
                </div>
              </div>
            </CollapsibleContent>
          </article>
        </Collapsible>

        <article v-else-if="block.kind === 'stderr'" class="rounded-lg border border-red-900/50 bg-red-950/20 px-3 py-2">
          <div class="mb-1 flex items-center gap-2 text-xs text-red-300">
            <Terminal class="size-3.5" />
            stderr
          </div>
          <pre class="chat-text text-xs text-red-100/90">{{ block.text }}</pre>
        </article>

        <article v-else class="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          <div class="mb-1 uppercase tracking-wide">{{ block.kind }}{{ block.title ? ` · ${block.title}` : "" }}</div>
          <div class="chat-text">{{ block.text }}</div>
        </article>
      </template>
    </div>
  </ScrollArea>
</template>
