"""Readable projection of revalidated observations, never a fact migration."""
from datetime import datetime
import time

APP_NAMES = {"com.google.Chrome":"Chrome", "com.apple.Safari":"Safari", "com.apple.finder":"Finder",
             "com.openai.codex":"Codex", "com.microsoft.VSCode":"VS Code", "com.apple.Notes":"备忘录",
             "com.tencent.xinWeChat":"微信", "com.tencent.qq":"QQ"}


def context_cards(rows, now=None, limit=6):
    now = time.time() if now is None else now
    cards, seen = [], set()
    for row in rows:
        if row.get("kind") != "ax.snapshot" or not 0 <= now-row["timestamp"] <= 86400:
            continue
        obj, proof = row["object"], row["evidence"]
        bundle, title = obj.get("bundle_id", ""), proof.get("window_title", "")
        key = (bundle, title)
        if key in seen:
            continue
        seen.add(key)
        texts = list(dict.fromkeys(n["text"].strip() for n in proof.get("nodes", [])
                                  if n.get("role") == "AXStaticText" and isinstance(n.get("text"), str) and n["text"].strip()))
        cards.append({"id":row["id"], "app":obj.get("app") or APP_NAMES.get(bundle, bundle),
                      "title":title or "窗口标题未读取", "text":"\n".join(texts)[:600],
                      "timestamp":row["timestamp"], "time":datetime.fromtimestamp(row["timestamp"]).strftime("%m-%d %H:%M"),
                      "source":row["source"], "source_reference":row.get("source_reference") or bundle,
                      "evidence_type":row["evidence_type"], "read_status":proof.get("read_status", "UNKNOWN"),
                      "text_chars":sum(map(len,texts)), "occurrences":row.get("occurrences",1)})
        if len(cards) >= limit:
            break
    return cards


def context_text(cards):
    if not cards:
        return "还没有近期可显示的窗口观察。打开普通应用后，我会在这里显示读到的内容。"
    return "近期观察（窗口标题与界面文字，不代表任务已完成）：\n\n" + "\n\n".join(
        f"{c['app']} · {c['title']}\n{c['time']} · {c['read_status']}\n可读文字：{c['text'] or '没有读到静态文字，无法判断正文'}" for c in cards)
