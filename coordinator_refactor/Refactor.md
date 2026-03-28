## Refactor Tasks

This document is the tasks I want completed to refactor our coordinator agent.
Currently all code sits in the main.py and we need to break it input multiple files.

-[x] all prompts should be stored as markdown files in a prompts directory
-[x] tools should be indivually defines as their own files in the tools/ directory we should have .py for each actual tool code and the tools.json for the tools = [] that gets passed to create
-[x] partition generation should be in lib as its own file
-[x] we should have logger that refactor all the logs to be consistent in a file called logger.py in inr lib directory
-[x] coverage report should be in own file in lib called coverage_report
-[x] right now we have hardcoded data make a data folder and store data artifacts and load them into the app
-[x] there are templates for content for messages that should really be templated files that take varaibles and loaded in technically they are prompts for content: and so move them to prompt folders