import os
from dotenv import load_dotenv
import anthropic

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def generate_message(message):
	response = client.messages.create(
		model="claude-sonnet-5",
		max_tokens=1024,
		messages=[{"role": "user", "content": message}]
	)
	return response

if __name__ == "__main__":
	result = generate_message("Hello, how are you?")
	print(result.content[0].text)