from openai import OpenAI
import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)
print(f"{os.getenv('OPENAI_API_KEY')}")

client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY')
)

try:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",  # test model phổ biến trước
        messages=[{"role": "user", "content": "Ping?"}],
        max_tokens=10,
    )
    print("OK:", resp.choices[0].message.content)
except Exception as e:
    print("ERR:", e)
