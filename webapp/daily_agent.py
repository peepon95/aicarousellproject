#!/usr/bin/env python3
"""
Daily draft agent (Mac cron, draft-only — never auto-posts).
Each run: pull newest high-signal repos for the topics in sources.yaml,
build a DRAFT carousel, and drop it in inbox/YYYY-MM-DD/ with a manifest
for you to review + approve in the web UI before posting.

Install cron:  python webapp/daily_agent.py --install-cron 08:00
Run once now:  python webapp/daily_agent.py
"""
import os, sys, json, shutil, datetime, subprocess
import yaml
import pipeline as P

ROOT = P.ROOT
INBOX = os.path.join(ROOT, "inbox")
SOURCES = os.path.join(ROOT, ".claude", "skills", "ai-resource-carousel", "sources.yaml")


def pick_candidates(limit=6):
    """Pull across all configured GitHub topics, dedupe, keep the top by stars."""
    cfg = yaml.safe_load(open(SOURCES))
    seen, pool = set(), []
    for topic in cfg.get("github", {}).get("topics", []):
        try:
            for r in P.pull_github(topic.replace("+", " "), n=8):
                if r["name"] in seen:
                    continue
                seen.add(r["name"])
                pool.append(r)
        except Exception as e:
            print("pull failed for", topic, e)
    pool.sort(key=lambda r: r["stars"], reverse=True)
    return pool[:limit]


def run():
    day = datetime.date.today().isoformat()
    folder = os.path.join(INBOX, day)
    os.makedirs(folder, exist_ok=True)

    cands = pick_candidates()
    if not cands:
        print("No candidates pulled — check network / GitHub token.")
        return
    # draft hooks = repo name; you rewrite them in the UI (taste stays human)
    for c in cands:
        c["hook"] = c["name"].split("/")[-1].replace("-", " ")

    result = P.build_carousel(cands, cover_title="TODAY'S AI DROP",
                              cover_hook="fresh repos worth a look", run_id=f"draft_{day}")

    # move the generated PNGs into the dated inbox folder
    moved = []
    for name in result["slides"]:
        src = os.path.join(P.OUT, name)
        if os.path.exists(src):
            shutil.move(src, os.path.join(folder, name))
            moved.append(name)

    manifest = {"date": day, "status": "draft", "slides": moved,
                "resources": cands, "credits": result["credits"]}
    json.dump(manifest, open(os.path.join(folder, "manifest.json"), "w"), indent=2)
    print(f"Draft ready: inbox/{day}/ ({len(moved)} slides). Review before posting.")


def install_cron(hhmm):
    hh, mm = hhmm.split(":")
    py = sys.executable
    script = os.path.abspath(__file__)
    log = os.path.join(ROOT, "inbox", "cron.log")
    line = f"{int(mm)} {int(hh)} * * * cd {ROOT} && {py} {script} >> {log} 2>&1"
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    existing = "\n".join(l for l in existing.splitlines() if script not in l)
    new = (existing + "\n" + line + "\n").lstrip("\n")
    subprocess.run(["crontab", "-"], input=new, text=True)
    print(f"Installed cron: builds a draft daily at {hhmm}. Logs -> inbox/cron.log")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--install-cron":
        install_cron(sys.argv[2] if len(sys.argv) > 2 else "08:00")
    else:
        run()
