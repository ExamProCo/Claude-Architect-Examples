# Doom Codebase Exploration Orchestration


I want to use Claude Code to explore the DOOM codebase 
eg. How does a player take damage

I a concerned that due to the size of codebase that 
Claude Code will lose context as it summarized information

I want to have external key information saved to FINDINGS.md
so that it helps guide memory

I want to run exploration as a subgent so that it does not muddy
the context of the main/parent Claude Code runtime so it can effectivly coordinate

I want to be ble to recover or resume subagent tasks and so I want
that state to be stored in mainfest.json

I want a subgent defined based on Claude Code's conventions eg. /.claude/agents