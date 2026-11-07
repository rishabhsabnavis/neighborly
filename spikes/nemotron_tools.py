# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.40", "python-dotenv>=1.0"]
# ///
"""Spike: can Nemotron run a multi-step tool-calling loop via NVIDIA's API?

PASS = model makes >=1 tool call with valid JSON args, uses the tool result,
and finishes by calling report_verdict. Run: just spike-nemotron
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent / ".env")
key = os.getenv("NVIDIA_API_KEY")
if not key:
    sys.exit(
        "FAIL: NVIDIA_API_KEY missing. Get one at build.nvidia.com, put it in spikes/.env"
    )

client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key)

# 1. Find a Nemotron model this key can use.
ids = sorted(m.id for m in client.models.list().data if "nemotron" in m.id.lower())
print(f"Nemotron models visible ({len(ids)}):")
for i in ids:
    print("  ", i)
prefer = [
    os.getenv("NEMOTRON_MODEL", ""),
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
]
model = next((p for p in prefer if p and p in ids), ids[0] if ids else None)
if not model:
    sys.exit("FAIL: no Nemotron models listed for this key")
print(f"\nUsing: {model}\n")

# 2. Two-tool agent loop.
OFFICIAL = {
    "chase": "1-800-935-9935",
    "usps": "1-800-275-8777",
    "state farm": "1-800-732-5246",
}
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_official_number",
            "description": "Look up a company's official customer-service phone number.",
            "parameters": {
                "type": "object",
                "properties": {"company": {"type": "string"}},
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_verdict",
            "description": "Final answer. Call exactly once when done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "enum": ["scam", "legit", "unsure"]},
                    "confidence": {"type": "number", "description": "0-1"},
                    "next_steps": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label", "confidence", "next_steps"],
            },
        },
    },
]
messages = [
    {
        "role": "system",
        "content": "You check suspicious messages. Always verify the sender's claimed company with get_official_number before deciding, then call report_verdict.",
    },
    {
        "role": "user",
        "content": "Text from +1 (555) 013-2291: 'Chase Fraud Dept: your account is locked. Reply with the 6-digit code we just sent to unlock.' Legit?",
    },
]

calls, verdict, t0 = [], None, time.time()
for step in range(6):
    r = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0.2,
        max_tokens=1024,
    )
    msg = r.choices[0].message
    messages.append(msg.model_dump(exclude_none=True))
    if not msg.tool_calls:
        print(f"step {step}: text reply (no tool call): {(msg.content or '')[:200]}")
        break
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)  # raises if args aren't valid JSON
        calls.append(tc.function.name)
        print(f"step {step}: tool {tc.function.name}({args})")
        if tc.function.name == "get_official_number":
            result = OFFICIAL.get(args["company"].lower().strip(), "unknown")
        else:
            verdict, result = args, "recorded"
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({"result": result}),
            }
        )
    if verdict:
        break

elapsed = time.time() - t0
print(f"\nverdict: {verdict}\ntool calls: {calls}\nelapsed: {elapsed:.1f}s")
ok = "get_official_number" in calls and verdict is not None
print(
    "PASS" if ok else "FAIL: model did not complete the lookup -> verdict tool sequence"
)
sys.exit(0 if ok else 1)
