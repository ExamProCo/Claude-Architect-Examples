## Business Usecase

ExamPro Training Inc is a tech platform that has multiple self-paced tech education courses.
They need a customer support agent that will resolve common issues.

### Common Requests
The agent needs to the following:
- refunds
- swaping out courses eg. purchased wrong course
- not recieving confirmation email
- bug with the platform eg. star count is incorrect
- specific content problems eg. state content, no audio in video
- business development oppurintiy 
- GDPR request

## Version 1
Implement an Agent using the Anthropic's Agent SDK not the Anthropic Low level SDK
and and will mock out API requests as tool call eg. create a ticket, issue a refund 
We probably would have an MCP server that goes to exampro endpoints and so tool calls wwould live there

## Todos

Adding explicit escalation criteria with few-shot examples to the system prompt demonstrating when to escalate versus resolve autonomously
- Honoring explicit customer requests for human agents immediately without fi rst attempting investigation
- Acknowledging frustration while offering resolution when the issue is within the agent's capability, escalating only if the customer reiterates their preference
- Escalating when policy is ambiguous or silent on the customer's specifi c request (e.g., competitor price matching when policy only addresses own-site adjustments)
- Instructing the agent to ask for additional identifi ers when tool results return multiple matches, rather than selecting based on heuristics