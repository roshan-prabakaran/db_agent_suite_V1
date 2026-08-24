from openai import OpenAI

client = OpenAI(
    api_key="sk-exyuMNpb8i066uZK2yBLnw",
    base_url="http://172.16.48.97:4000/v1"
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[
        {
            "role": "user",
            "content": "Explain what an inference engine is."
        }
    ]
)

print(response.choices[0].message.content)