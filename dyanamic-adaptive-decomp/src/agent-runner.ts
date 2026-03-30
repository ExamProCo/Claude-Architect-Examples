import Anthropic from '@anthropic-ai/sdk';
import fs from 'fs/promises';
import path from 'path';
import dotenv from 'dotenv';

// Load .env from parent directory
dotenv.config({ path: path.join(__dirname, '..', '..', '.env') });

const client = new Anthropic();
const AGENTS_DIR = path.join(__dirname, '..', 'agents');
const MODEL = 'claude-haiku-4-5-20251001';

export async function callAgent(
  agentName: string,
  input: Record<string, unknown>,
  maxTokens: number = 1024
): Promise<unknown> {
  // 1. Read the agent's markdown file as system prompt
  const agentFile = path.join(AGENTS_DIR, `${agentName}.md`);
  const systemPrompt = await fs.readFile(agentFile, 'utf-8');

  // 2. Construct user message with JSON input
  const userMessage = `Process this input and respond with valid JSON only:\n\n${JSON.stringify(input, null, 2)}`;

  // 3. Call Claude API
  const response = await client.messages.create({
    model: MODEL,
    max_tokens: maxTokens,
    system: systemPrompt,
    messages: [{ role: 'user', content: userMessage }],
  });

  // 4. Parse JSON response
  const text = response.content.find((b) => b.type === 'text')?.text ?? '{}';

  // Extract JSON from the response (may be wrapped in markdown code blocks)
  const fenceMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const jsonStr = fenceMatch ? fenceMatch[1] : text;

  try {
    return JSON.parse(jsonStr.trim());
  } catch {
    // Try to extract a JSON object or array from the text
    const objMatch = jsonStr.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
    if (objMatch) {
      try {
        return JSON.parse(objMatch[1]);
      } catch {
        // fall through to error
      }
    }
    throw new Error(
      `Agent ${agentName} returned non-JSON: ${text.slice(0, 200)}`
    );
  }
}
