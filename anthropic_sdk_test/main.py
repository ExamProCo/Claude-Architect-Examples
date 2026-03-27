import os
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).parent.parent / ".env")

def test():
  client = Anthropic(
      # This is the default and can be omitted
      api_key=os.environ.get("ANTHROPIC_API_KEY"),
  )

  message = client.messages.create(
      max_tokens=1024,
      messages=[
          {
              "role": "user",
              "content": "Hello, Claude",
          }
      ],
      model="claude-haiku-4-5-20251001",
  )
  print(message.content)

def list_models():
  # list out models
  client = Anthropic(
      api_key=os.environ.get("ANTHROPIC_API_KEY"),  # This is the default and can be omitted
  )
  page = client.models.list()
  for data in page.data:
    print(data.id)

test()