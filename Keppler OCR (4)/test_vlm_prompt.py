import asyncio
import base64
from openai import AsyncOpenAI
import time

async def main():
    client = AsyncOpenAI(base_url="http://localhost:8700/v1", api_key="EMPTY", timeout=60.0)
    
    # We need the image base64. The user uploaded it, it should be in the chat context, but we don't have it locally as a file.
    # Wait, the user uploaded the image, it's not saved locally automatically unless it's in the workspace.
    pass

asyncio.run(main())
