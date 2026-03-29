import { query, forkSession } from "@anthropic-ai/claude-agent-sdk";

const MODEL = "claude-haiku-4-5-20251001";

/**
 * Run the shared baseline conversation and return the session ID at the
 * fork point. All branches will fork from this exact state.
 */
async function buildBaseline(): Promise<string> {
  let sessionId = "";
  let resultText = "";

  for await (const message of query({
    prompt: "Analyse the EV market briefly.",
    options: { model: MODEL },
  })) {
    if (message.type === "system" && message.subtype === "init") {
      sessionId = message.session_id;
    }
    if (message.type === "result" && !message.is_error) {
      resultText = (message as { result: string }).result;
    }
  }

  console.log(`[baseline] complete — ${resultText.length} chars, session: ${sessionId}`);
  return sessionId;
}

/**
 * Fork from the baseline session and run an isolated branch conversation.
 */
async function runBranch(
  name: string,
  baselineSessionId: string,
  prompt: string,
): Promise<[string, string]> {
  // Create an isolated copy of the baseline session state
  const { sessionId: branchSessionId } = await forkSession(baselineSessionId);

  let result = "";
  for await (const message of query({
    prompt,
    options: { model: MODEL, resume: branchSessionId },
  })) {
    if (message.type === "result" && !message.is_error) {
      result = (message as { result: string }).result;
    }
  }

  return [name, result];
}

async function main(): Promise<void> {
  // ── Phase 1: shared baseline ──────────────────────────────────────────────
  console.log("Building shared baseline...");
  console.log("-".repeat(60));
  const baselineSessionId = await buildBaseline();

  // ── Phase 2: concurrent forked branches ──────────────────────────────────
  const branches: Record<string, string> = {
    optimistic:
      "What is the most optimistic 5-year EV adoption scenario? Focus on best-case growth.",
    pessimistic:
      "What is the most pessimistic 5-year EV adoption scenario? Focus on risks and headwinds.",
    regulatory:
      "How could upcoming government regulations reshape the EV market over the next 5 years?",
  };

  console.log(`\nForking into ${Object.keys(branches).length} isolated branches concurrently...`);
  console.log("-".repeat(60));

  const results = await Promise.all(
    Object.entries(branches).map(([name, prompt]) =>
      runBranch(name, baselineSessionId, prompt),
    ),
  );

  // ── Output ─────────────────────────────────────────────────────────────────
  console.log("\nResults");
  console.log("=".repeat(60));
  for (const [name, text] of results) {
    console.log(`\n[${name.toUpperCase()}]`);
    console.log(text);
    console.log("-".repeat(60));
  }
}

main().catch(console.error);
