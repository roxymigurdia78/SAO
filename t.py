from openai import OpenAI

env = {}
for l in open(r"mvl-skeleton\python\.env", encoding="utf-8-sig"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, _, v = l.partition("="); env[k.strip()] = v.strip()

c = OpenAI(api_key=env["LLM_KEY"], base_url=env["LLM_BASE_URL"],
           default_headers={"User-Agent": "curl/8.5.0"})

for m in ["qwen3.5:35b", "gemma4:12b", "qwen3.5:4b", "bge-m3:latest"]:
    try:
        r = c.chat.completions.create(model=m,
            messages=[{"role": "user", "content": "こんにちは"}],
            reasoning_effort="none", stream=False)
        print(m, "OK:", r.choices[0].message.content[:60])
    except Exception as e:
        print(m, "NG:", str(e)[:160])