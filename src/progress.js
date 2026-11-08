// Live progress of the backend's AI agents (Server-Sent Events from /generate/stream).

// What the AI agents do, in order. `nodes` are the backend workflow steps.
const STAGES = [
  { key: 'read', label: 'Reading your ingredients', nodes: ['input_agent'] },
  { key: 'search', label: 'Finding real recipes', nodes: ['retriever'] },
  { key: 'adapt', label: 'Adapting recipes to your kitchen', nodes: ['chef_agent', 'fallback_chef'] },
  { key: 'diet', label: 'Checking your diet', nodes: ['diet_checker'] },
  { key: 'nutrition', label: 'Calculating nutrition (USDA)', nodes: ['nutrition_agent'] },
];
const REDO_NODES = ['chef_agent', 'fallback_chef', 'diet_checker', 'nutrition_agent'];

// Replays the progress events into "which steps are finished" + revision round.
export function progressState(events) {
  const finished = new Set();
  let revision = 0;
  for (const { event, data } of events) {
    if (event === 'step') finished.add(data.step);
    if (event === 'revision') {
      revision = data.round;
      REDO_NODES.forEach((n) => finished.delete(n));
    }
  }
  const done = STAGES.map((s) => s.nodes.some((n) => finished.has(n)));
  // Diet check and nutrition run in parallel: both are active once recipes exist.
  const firstOpen = done.indexOf(false);
  const active = STAGES.map((s, i) => !done[i] && (i === firstOpen || (i > firstOpen && done[2] && i >= 3)));
  return { stages: STAGES.map((s, i) => ({ ...s, done: done[i], active: active[i] })), revision };
}
