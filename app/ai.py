"""Optional OpenAI-compatible LLM. Disabled cleanly when LLM_API_KEY is empty."""
import requests
from . import config as C
def enabled(): return bool(C.LLM_API_KEY)
SYS = ("You explain trading signals from a 4H fair-value-gap + 5m FVG confirmation strategy. Be concise, factual, "
       "mention risk; never promise profit. This is not financial advice.")
def chat(prompt, context=""):
    if not enabled(): return "AI is disabled (set LLM_API_KEY in .env)."
    r = requests.post(C.LLM_BASE_URL.rstrip("/")+"/chat/completions", headers={"Authorization": f"Bearer {C.LLM_API_KEY}"},
        json=dict(model=C.LLM_MODEL, messages=[{"role":"system","content":SYS+("\nSignals:\n"+context if context else "")},
                                                {"role":"user","content":prompt}], temperature=0.3), timeout=60)
    r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
def explain(sig):
    return chat("Explain this signal and its main risks in <150 words.", str({k:sig[k] for k in
        ("symbol","direction","entry","sl","tp","confidence","in_session","reasons","status")}))
