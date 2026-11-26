"""HEXA file-first production CLI. Python 3.10+, standard library only."""
import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False, suffix=".tmp") as f:
        tmp = Path(f.name)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def inside(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Expected project-relative path")
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"Invalid relative path: {relative}")
    target = (root / p).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"Path escapes project: {relative}")
    return target


def ident(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"[A-Za-z0-9_-]+", value):
        raise ValueError(f"Invalid ID: {value}")
    return value


def load(root):
    p = read(root / "project.json")
    if p.get("schemaVersion") != 2 or p.get("fps") != 24:
        raise ValueError("Expected HEXA Studio schemaVersion 2, 24fps")
    if not isinstance(p.get("cuts"), list) or len(set(p["cuts"])) != len(p["cuts"]):
        raise ValueError("Invalid or duplicate cut IDs")
    for cid in p["cuts"]:
        ident(cid, "C")
        base = inside(root, f"cuts/{cid}")
        c = read(base / "cut.json")
        if c.get("id") != cid or type(c.get("frames")) is not int or not 1 <= c["frames"] <= 120:
            raise ValueError(f"Invalid cut: {cid}")
        if len(set(c["keyframes"])) != len(c["keyframes"]):
            raise ValueError(f"Duplicate keyframe IDs: {cid}")
        keys = []
        for kid in c["keyframes"]:
            ident(kid, "K")
            k = read(inside(root, f"cuts/{cid}/keyframes/{kid}/keyframe.json"))
            if k.get("id") != kid or type(k.get("frame")) is not int or not 0 <= k["frame"] < c["frames"]:
                raise ValueError(f"Invalid keyframe: {cid}/{kid}")
            keys.append(k)
        if len({k["frame"] for k in keys}) != len(keys):
            raise ValueError(f"Duplicate keyframe positions: {cid}")
        yield c, sorted(keys, key=lambda k: k["frame"])


def media_state(path, extensions):
    files = sorted(p.name for p in path.iterdir() if p.is_file() and p.suffix.lower() in extensions) if path.is_dir() else []
    meta = read(path / "result.json") if (path / "result.json").is_file() else {}
    approved = meta.get("approved")
    state = ("approved" if approved in files else "running" if meta.get("state") == "running"
             else "failed" if meta.get("error") else "review" if files else "pending")
    return {"state": state, "approved": approved if approved in files else None,
            "candidates": files, "error": meta.get("error")}


def cut_status(root, c, keys):
    cid = c["id"]
    b = inside(root, f"cuts/{cid}")
    out = inside(root, f"output/{cid}")
    issues = []
    refs = list(c.get("characters", [])) + ([c["location"]] if c.get("location") else [])
    if not c.get("characters"):
        issues.append("No cast selected")
    if not c.get("location"):
        issues.append("No location selected")
    for ref in refs:
        try:
            a = inside(root, ref)
            meta = read(a / "asset.json")
            for n in meta.get("files", []):
                if not isinstance(n, str) or Path(n).name != n or n in (".", ".."):
                    raise ValueError("Invalid asset filename")
                if not inside(root, str((a / n).relative_to(root))).is_file():
                    issues.append(f"Missing asset file: {ref}/{n}")
        except (OSError, ValueError, TypeError) as e:
            issues.append(f"Asset {ref}: {e}")
    if not (b / "previs.json").is_file():
        issues.append("Missing previs.json")
    if not keys:
        issues.append("No keyframes")
    kstates = []
    for k in keys:
        kid = k["id"]
        kb = b / "keyframes" / kid
        if not (kb / "previs.png").is_file():
            issues.append(f"{kid}: missing previs.png")
        if not (kb / "prompt.md").is_file():
            issues.append(f"{kid}: missing prompt.md")
        kstates.append({"id": kid, "frame": k["frame"],
                        **media_state(out / "keyframes" / kid, {".png", ".jpg", ".jpeg", ".webp"})})
    motion = media_state(out / "videos", {".mp4", ".webm"})
    return {"id": cid, "name": c.get("name", cid), "issues": issues,
            "keyframes": kstates, "motion": motion}


def manifest(root, c, keys):
    """Compose prompt text and hash input files, without executing a generator."""
    cid = c["id"]
    b = inside(root, f"cuts/{cid}")
    shared = [b / "cut.json", b / "previs.json", b / "direction.md", b / "motion_prompt.md"]
    sections = []
    refs = list(c.get("characters", [])) + [c["location"]]
    for ref in refs:
        a = inside(root, ref)
        meta = read(a / "asset.json")
        shared.append(a / "asset.json")
        sections.append(f"## {meta.get('name', ref)}")
        for n in meta.get("files", []):
            if not isinstance(n, str) or Path(n).name != n or n in (".", ".."):
                raise ValueError("Invalid asset filename")
            f = inside(root, str((a / n).relative_to(root)))
            shared.append(f)
            if f.suffix.lower() in (".md", ".txt"):
                sections.append(f.read_text(encoding="utf-8"))
    sections.append((b / "direction.md").read_text(encoding="utf-8"))
    def hashes(files):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in files if p.is_file()}
    result = []
    for k in keys:
        kb = b / "keyframes" / k["id"]
        prompt = "\n\n".join(sections + [(kb / "prompt.md").read_text(encoding="utf-8")])
        result.append({"id": k["id"], "frame": k["frame"], "prompt": prompt,
                       "inputs": hashes(shared + [kb / "keyframe.json", kb / "previs.png", kb / "prompt.md"])})
    return {"schemaVersion": 1, "cut": cid, "frames": c["frames"], "fps": 24,
            "keyframes": result, "motionPrompt": (b / "motion_prompt.md").read_text(encoding="utf-8"),
            "execution": "not_submitted"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "status", "plan"])
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--cut")
    args = parser.parse_args()
    root = args.project.resolve()
    try:
        records = [(c, k) for c, k in load(root) if not args.cut or c["id"] == args.cut]
        if args.cut and not records:
            raise ValueError(f"Unknown cut: {args.cut}")
        statuses = [cut_status(root, c, k) for c, k in records]
        if args.command == "plan":
            for (c, k), s in zip(records, statuses):
                if s["issues"]:
                    continue
                write(inside(root, f"output/{c['id']}/plan.json"), manifest(root, c, k))
        print(json.dumps(statuses, ensure_ascii=False, indent=2))
        return 1 if args.command != "status" and any(s["issues"] for s in statuses) else 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"HEXA: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
