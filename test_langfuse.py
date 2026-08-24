import os
from dotenv import load_dotenv
from langfuse import Langfuse

load_dotenv()

print("BASE URL:", os.getenv("LANGFUSE_BASE_URL"))
print("PUBLIC KEY:", os.getenv("LANGFUSE_PUBLIC_KEY"))
print("SECRET SET:", bool(os.getenv("LANGFUSE_SECRET_KEY")))

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_BASE_URL"),
)

print("Running auth check...")

print(langfuse.auth_check())

print("Creating test trace...")

trace = langfuse.trace(
    name="self-hosted-test"
)

trace.update(
    input="Hello Langfuse",
    output="Self-hosted Langfuse test successful"
)

langfuse.flush()

print("DONE")