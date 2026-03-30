## Claude Code Agent Dungeon

## Technical Goal

Implement Dynamic adaptive decomposition when intermediate findings should change what you do next which agents to call, how many times, in what order.

anything where you don't know upfront how deep or wide the work needs to go.

## Business Goal

We will implement dynamic adaptive decomposition for a Agent Dunegon.
We are generating the world as we play the game.
The agent has to figure a way to build the static world in code as we play along.

# Technical Considerations

We want to Claude Agent SDK
We want to use the filesystem for Agents eg. /agents directory instead coding them using AgentDef
