import { BranchTask, WorldState } from './types';
import { callAgent } from './agent-runner';

// ============================================================
// Token budget per agent type
// ============================================================

export function getMaxTokensForAgent(agentName: string): number {
  const tokenMap: Record<string, number> = {
    orchestrator: 2048,
    'room-builder': 1024,
    npc: 1024,
    quest: 1024,
    lore: 512,
    'lore-consistency': 1024,
    'code-writer': 2048,
    combat: 1536,
    puzzle: 1536,
  };
  return tokenMap[agentName] ?? 1024;
}

// ============================================================
// Topological sort — returns tasks in dependency order
// ============================================================

export function topologicalSort(tasks: BranchTask[]): BranchTask[] {
  const taskMap = new Map<string, BranchTask>(tasks.map((t) => [t.id, t]));
  const visited = new Set<string>();
  const result: BranchTask[] = [];

  function visit(task: BranchTask): void {
    if (visited.has(task.id)) return;
    visited.add(task.id);

    for (const depId of task.dependsOn) {
      const dep = taskMap.get(depId);
      if (dep) visit(dep);
    }
    result.push(task);
  }

  for (const task of tasks) {
    visit(task);
  }

  return result;
}

// ============================================================
// Check whether all dependencies for a task are complete
// ============================================================

function depsComplete(task: BranchTask, allTasks: BranchTask[]): boolean {
  if (task.dependsOn.length === 0) return true;
  const taskMap = new Map(allTasks.map((t) => [t.id, t]));
  return task.dependsOn.every((depId) => {
    const dep = taskMap.get(depId);
    return dep?.status === 'complete';
  });
}

// ============================================================
// Resolve a single branch task by calling the appropriate agent
// ============================================================

export async function resolveBranch(
  task: BranchTask,
  worldState: WorldState
): Promise<unknown> {
  task.status = 'running';
  try {
    const result = await callAgent(
      task.agentName,
      { ...task.input, _worldStateMeta: worldState.meta },
      getMaxTokensForAgent(task.agentName)
    );
    task.status = 'complete';
    task.result = result;
    return result;
  } catch (err) {
    task.status = 'complete'; // Mark complete even on error so dependents unblock
    task.result = null;
    console.error(`[branch-resolver] Task ${task.id} (${task.agentName}) failed:`, err);
    return null;
  }
}

// ============================================================
// Resolve tasks in waves — each wave contains tasks whose deps are all complete
// ============================================================

export async function resolveParallel(
  tasks: BranchTask[],
  worldState: WorldState
): Promise<unknown[]> {
  const pending = [...tasks];
  const results: unknown[] = [];

  while (pending.some((t) => t.status !== 'complete')) {
    // Find tasks ready to run (pending + deps complete)
    const ready = pending.filter(
      (t) => t.status === 'pending' && depsComplete(t, pending)
    );

    if (ready.length === 0) {
      // Prevent infinite loop if something is blocked
      const blocked = pending.filter((t) => t.status !== 'complete');
      console.warn(
        `[branch-resolver] ${blocked.length} task(s) blocked with unresolved deps — marking complete.`
      );
      for (const t of blocked) {
        t.status = 'complete';
        t.result = null;
      }
      break;
    }

    const wave = await Promise.all(ready.map((t) => resolveBranch(t, worldState)));
    results.push(...wave);
  }

  return results;
}
