from openai import OpenAI

client = OpenAI(
    api_key="sk-V4CTFQlGeYYFY57p_iCwug",
    base_url="http://172.16.48.97:4000"
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[
        {"role": "user", "content": "Hello"}
    ]
)