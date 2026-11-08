# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.40", "python-dotenv>=1.0"]
# ///
"""Spike (SPEC risk #2): can Nemotron write a correct claim draft + a policy-aware follow-up?

Input: Maria's case (policy + iMessage replies + the real call transcript from the outbound spike).
Checks, per run (3 runs):
  claim:  valid JSON with the SPEC claim_draft keys; roof -> dwelling, water-damaged belongings ->
          contents; ale_requested true; oxygen in injuries_or_medical; non-empty missing_info;
          no invented damages (car, windows, fence... were never mentioned); under 8s.
  follow-up: one question, mentions the $18,000 hotel (ALE) limit or the home address, under 300 chars.
PASS = every check passes in at least 2 of 3 runs. Run: just spike-claim
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "backend" / ".env")
load_dotenv(ROOT / "spikes" / ".env")
KEY = (os.getenv("NVIDIA_API_KEY") or "").strip()
MODEL = (
    os.getenv("NEMOTRON_AGENT_MODEL") or "nvidia/nemotron-3.5-super-vl-120b-a12b"
).strip()
FAST = (
    os.getenv("NEMOTRON_TRIAGE_MODEL") or "nvidia/nemotron-3.5-lightning-30b-a3b"
).strip()
if not KEY:
    sys.exit("FAIL: NVIDIA_API_KEY not set")
client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=KEY, timeout=30)

CASE = {
    "policyholder": {
        "id": "ph_017",
        "name": "Maria Lopez",
        "address": "412 Harbor Dr, Panama City, FL",
        "county": "Bay",
    },
    "policy": {
        "number": "SF-HO-88213",
        "type": "homeowners",
        "covered_property": ["Dwelling: 412 Harbor Dr", "2019 Toyota Camry"],
        "coverages": {"dwelling": 320000, "contents": 160000, "ale": 18000},
        "deductible": 2500,
        "household": {"size": 3, "notes": ["Mother, 74, home oxygen"]},
    },
    "disaster": {"number": 4955, "name": "Hurricane Isaias", "declared": "2026-10-27"},
    "messages": [
        {
            "id": "m_1",
            "from": "agent",
            "channel": "imessage",
            "text": "Maria, this is Neighborly. Hurricane Isaias hit Bay County. Reply 1 Safe, 2 Need help, 3 Emergency, 4 Call me, 0 Talk to a person.",
        },
        {"id": "m_2", "from": "policyholder", "channel": "imessage", "text": "2"},
        {
            "id": "m_3",
            "from": "agent",
            "channel": "imessage",
            "text": "Is there damage to your home at 412 Harbor Dr?",
        },
        {
            "id": "m_4",
            "from": "policyholder",
            "channel": "imessage",
            "text": "roof caved in, water in the living room, couch and tv ruined. yes need hotel",
        },
        {"id": "m_5", "from": "policyholder", "channel": "imessage", "text": "4"},
    ],
    "calls": [
        {
            "call_id": "conv_6701m6wjc13xfhpty77105bddcqr",
            "transcript": [
                [
                    "agent",
                    "Hi Maria, this is Neighborly's storm check-in line. You texted us that your roof caved in and there's water in the living room. Are you and everyone with you safe right now?",
                ],
                ["user", "No."],
                ["agent", "I'm sorry to hear that. Is anyone injured or trapped?"],
                ["user", "My mom is on oxygen and the power is out."],
                [
                    "agent",
                    "Please hang up and call nine-one-one for immediate assistance.",
                ],
            ],
        }
    ],
}

CLAIM_SYSTEM = """You are a Neighborly catastrophe claims assistant. Write a FIRST NOTICE OF LOSS claim draft
from the case JSON. Use ONLY facts stated in the messages or call transcript. Never invent damage, items,
injuries or amounts. Map each damage to one policy coverage: dwelling (the structure: roof, walls, floors),
contents (belongings: furniture, electronics, clothing), auto (a covered vehicle), or ale (additional living
expense: hotel/temporary housing). List what an adjuster still needs in missing_info. Output ONLY a JSON
object with exactly these keys:
{"claim_id": str, "status": "draft", "policy_number": str, "date_of_loss": "YYYY-MM-DD",
 "cause_of_loss": str, "loss_location": str,
 "damages": [{"item": str, "description": str, "coverage": "dwelling|contents|auto|ale", "severity": "minor|moderate|major"}],
 "ale_requested": bool, "injuries_or_medical": [str], "deductible": number, "missing_info": [str],
 "evidence": [message or call ids the facts came from]}"""

FOLLOWUP_SYSTEM = """You are a Neighborly catastrophe check-in agent texting a policyholder over iMessage.
They replied "2" (need help). Using their policy, write ONE short follow-up question (under 300 characters,
plain words, no emoji) that helps us help them tonight: ask about damage to their covered home and mention
the exact dollar limit their policy has for hotel / temporary housing (ALE). Output only the message text."""

REQUIRED = {
    "claim_id",
    "status",
    "policy_number",
    "date_of_loss",
    "cause_of_loss",
    "loss_location",
    "damages",
    "ale_requested",
    "injuries_or_medical",
    "deductible",
    "missing_info",
    "evidence",
}
INVENTED = re.compile(
    r"\b(car|camry|vehicle|auto|window|fence|garage|kitchen|bedroom|tree|flood insurance|basement)\b",
    re.I,
)


def chat(model: str, system: str, user: str, max_tokens: int) -> tuple[str, float]:
    t = time.time()
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        # reasoning off: otherwise hidden thinking eats max_tokens and content comes back empty
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        max_tokens=max_tokens,
    )
    return (r.choices[0].message.content or "").strip(), time.time() - t


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def check_claim(d: dict, secs: float) -> dict[str, bool]:
    dmg = d.get("damages") or []
    cov = {
        (x.get("item", "") + " " + x.get("description", "")).lower(): x.get("coverage")
        for x in dmg
    }
    text_all = json.dumps(dmg)
    return {
        "keys": REQUIRED <= set(d),
        "roof->dwelling": any("roof" in k and v == "dwelling" for k, v in cov.items()),
        "belongings->contents": any(v == "contents" for v in cov.values()),
        "ale_requested": d.get("ale_requested") is True,
        "oxygen noted": "oxygen"
        in json.dumps(d.get("injuries_or_medical") or []).lower(),
        "missing_info": len(d.get("missing_info") or []) > 0,
        "no invented damage": not INVENTED.search(text_all),
        "policy/deductible": d.get("policy_number") == "SF-HO-88213"
        and d.get("deductible") == 2500,
        "under 8s": secs < 8,
    }


def check_followup(text: str, secs: float) -> dict[str, bool]:
    return {
        "mentions $18,000": bool(re.search(r"18,?000|18k", text, re.I)),
        "one question": text.count("?") >= 1 and len(text) < 300,
        "under 4s": secs < 4,
    }


def main() -> None:
    case_json = json.dumps(CASE)
    results = []
    for run in range(1, 4):
        print(f"\n=== run {run} ===")
        raw, secs = chat(MODEL, CLAIM_SYSTEM, case_json, 1500)
        try:
            claim = extract_json(raw)
        except json.JSONDecodeError:
            claim = {}
        cc = check_claim(claim, secs)
        print(f"claim ({MODEL.split('/')[-1]}, {secs:.1f}s):")
        for x in claim.get("damages", []):
            print(
                f"   - {x.get('item')}: {x.get('description')} -> {x.get('coverage')} ({x.get('severity')})"
            )
        print(
            f"   ale={claim.get('ale_requested')} medical={claim.get('injuries_or_medical')}"
        )
        print(f"   missing={claim.get('missing_info')}")
        fu_res = {}
        for model in (FAST, MODEL):
            fu, fsecs = chat(
                model,
                FOLLOWUP_SYSTEM,
                json.dumps(
                    {"policyholder": CASE["policyholder"], "policy": CASE["policy"]}
                ),
                400,
            )
            fu = re.sub(r"<think>.*?</think>", "", fu, flags=re.S).strip()
            fc = check_followup(fu, fsecs)
            fu_res[model] = fc
            print(f"follow-up ({model.split('/')[-1]}, {fsecs:.1f}s): {fu!r}")
        failed = [k for k, v in cc.items() if not v]
        fast_ok = all(fu_res[FAST].values())
        big_ok = all(fu_res[MODEL].values())
        print(
            f"   claim checks failed: {failed or 'none'} | follow-up ok: lightning={fast_ok} super={big_ok}"
        )
        results.append((not failed, fast_ok or big_ok, cc, fu_res))
    claims_ok = sum(r[0] for r in results)
    fus_ok = sum(r[1] for r in results)
    print(f"\nclaim passed {claims_ok}/3, follow-up passed {fus_ok}/3")
    print("PASS" if claims_ok >= 2 and fus_ok >= 2 else "FAIL")
    sys.exit(0 if claims_ok >= 2 and fus_ok >= 2 else 1)


if __name__ == "__main__":
    main()
