import subprocess
import os
import sys
import argparse
import shutil
from time import sleep

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_API_MODEL") or "gemini-3-flash-preview"
MAX_DIFF_CHARS = 50000

def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, errors="replace", **kwargs)

def is_git_repo():
    return run(["git", "rev-parse", "--git-dir"]).returncode == 0

def is_working_tree_clean():
    res = run(["git", "status", "--porcelain"])
    if res.returncode != 0:
        return False
    return res.stdout.strip() == ""

def get_git_output(command):
    res = run(command)
    if res.returncode != 0:
        err = res.stderr.strip()
        if err:
            print(f"[!] Git warning/error: {err}")
        return []
    out = res.stdout.strip()
    return out.splitlines() if out else []

def get_all_commits():
    return [h for h in get_git_output(["git", "log", "--reverse", "--pretty=format:%H"]) if h]

def get_commits_in_range(range_spec):
    return [h for h in get_git_output(["git", "log", "--reverse", "--pretty=format:%H", range_spec]) if h]

def get_commit_diff(commit_hash):
    res = run(["git", "show", commit_hash])
    if res.returncode != 0:
        print(f"[!] Could not get diff for {commit_hash[:7]}")
        return ""
    return res.stdout[:MAX_DIFF_CHARS]

def sanitize_commit_message(msg):
    if not msg:
        return None
    msg = msg.replace('\r\n', '\n').replace('\r', '\n').split('\n')[0].strip()
    msg = ''.join(c for c in msg if c.isprintable())
    msg = msg[:200]
    if not msg:
        return None
    return msg

def generate_conventional_message(client, diff_content, retries=3):
    prompt = (
        "You are a strict code reviewer. Analyze the following git diff and commit metadata.\n"
        "Write a single, professional 'Conventional Commit' message for this change.\n"
        "Format: <type>: <description>\n"
        "Allowed types: feat, fix, chore, docs, style, refactor, perf, test, ci, build.\n"
        "Rules:\n"
        "1. Keep the first line under 72 characters.\n"
        "2. Use lowercase for the description.\n"
        "3. Do not end with a period.\n"
        "4. return ONLY the commit message string. No markdown, no quotes.\n\n"
        f"DIFF:\n{diff_content}"
    )

    for attempt in range(retries):
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
            if getattr(response, "text", None):
                text = response.text.strip().replace('"', '').replace("`", "")
                text = sanitize_commit_message(text)
                if text:
                    return text
            print(f"   [!] Empty response (attempt {attempt+1}/{retries})")
        except Exception as e:
            print(f"   [!] API Error: {e} (attempt {attempt+1}/{retries})")
        
        if attempt < retries - 1:
            sleep(2 ** attempt)
    
    return None

def generate_batch_messages(client, commits_with_diffs, retries=3):
    commit_sections = []
    for i, (commit_hash, diff) in enumerate(commits_with_diffs):
        commit_sections.append(f"=== COMMIT #{i+1} (hash: {commit_hash[:7]}) ===\n{diff}")
    
    all_diffs = "\n\n".join(commit_sections)
    
    prompt = (
        "You are a strict code reviewer. Analyze the following git diffs for multiple commits.\n"
        "Write a professional 'Conventional Commit' message for EACH commit.\n"
        "Format for each: <type>: <description>\n"
        "Allowed types: feat, fix, chore, docs, style, refactor, perf, test, ci, build.\n"
        "Rules:\n"
        "1. Keep each commit message under 72 characters.\n"
        "2. Use lowercase for the description.\n"
        "3. Do not end with a period.\n"
        "4. Return ONLY the commit messages, one per line, in order.\n"
        "5. Each line format: COMMIT#<number>: <message>\n"
        "   Example: COMMIT#1: feat: add user authentication\n\n"
        f"DIFFS:\n{all_diffs}"
    )

    for attempt in range(retries):
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
            if getattr(response, "text", None):
                text = response.text.strip()
                if text:
                    messages = {}
                    for line in text.splitlines():
                        line = line.strip()
                        if line.startswith("COMMIT#"):
                            try:
                                num_part, msg = line.split(": ", 1)
                                num = int(num_part.replace("COMMIT#", ""))
                                msg = sanitize_commit_message(msg.replace('"', '').replace("`", ""))
                                if msg:
                                    messages[num] = msg
                            except (ValueError, IndexError):
                                continue
                    if len(messages) == len(commits_with_diffs):
                        return messages
                    print(f"   [!] Got {len(messages)}/{len(commits_with_diffs)} messages (attempt {attempt+1}/{retries})")
            else:
                print(f"   [!] Empty response (attempt {attempt+1}/{retries})")
        except Exception as e:
            print(f"   [!] API Error: {e} (attempt {attempt+1}/{retries})")
        
        if attempt < retries - 1:
            sleep(2 ** attempt)
    
    return None

def check_cmsg_installed():
    if shutil.which("cmsg") is None:
        print("[X] Error: 'cmsg' tool not found.")
        print("   Please install it: https://github.com/ogpourya/cmsg")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Rewrite git history with AI-generated conventional commit messages.")
    parser.add_argument("commit_range", nargs="?", help="Git commit range (e.g., HEAD~5..HEAD, origin/main..HEAD). Defaults to ALL commits.")
    parser.add_argument("--yes", action="store_true", help="Skip all confirmation prompts.")
    parser.add_argument("--crazy", action="store_true", help="Use a single AI request for all commits (faster but less reliable).")
    args = parser.parse_args()

    if not is_git_repo():
        print("[!] Not a git repository. Aborting.")
        sys.exit(1)

    if not is_working_tree_clean():
        print("[!] Working tree is not clean. Stash or commit changes.")
        sys.exit(1)

    check_cmsg_installed()

    try:
        from google import genai
    except Exception as e:
        print(f"[!] Failed to import Gemini client library: {e}")
        print("   Make sure the library is installed and importable.")
        sys.exit(1)

    if not API_KEY:
        print("[!] Please set the GEMINI_API_KEY environment variable.")
        sys.exit(1)

    client = genai.Client(api_key=API_KEY)

    print(f"\n[*] Git Bard: Tuning instruments...")
    if os.getenv("GEMINI_API_MODEL"):
        print(f"    - Model: {MODEL_NAME}")
    else:
        print(f"    - Model: {MODEL_NAME} (default)")

    all_initial_commits = get_all_commits()
    if not all_initial_commits:
        print(f"\n[X] Error: No commits found.")
        sys.exit(1)

    target_indices = []

    if args.commit_range:
        if args.commit_range.lower() == "head":
            print(f"    - Target: Latest commit (HEAD)")
            target_indices = [len(all_initial_commits) - 1]
        else:
            print(f"    - Range:  {args.commit_range}")
            target_hashes = get_commits_in_range(args.commit_range)
            if not target_hashes:
                print(f"\n[X] Error: No commits in range.")
                sys.exit(1)
            for h in target_hashes:
                try:
                    idx = all_initial_commits.index(h)
                    target_indices.append(idx)
                except ValueError:
                    pass
            target_indices.sort()
    else:
        print(f"    - Range:  All commits")
        target_indices = list(range(len(all_initial_commits)))

    if not target_indices:
        print(f"\n[X] Error: No valid commits found to process.")
        sys.exit(1)

    total_ops = len(target_indices)
    print(f"    - Total:  {total_ops} commits\n")

    if args.yes:
        print("[*] Proceeding with rewrite (--yes)")
    else:
        confirm = input("[?] Proceed with rewrite? (y/N): ").lower()
        if confirm != 'y':
            print("Aborted.")
            sys.exit(0)

    target_indices.reverse()

    if args.crazy:
        print("[!] CRAZY MODE: Fetching all diffs...")
        
        indices_oldest_first = list(reversed(target_indices))
        
        commits_with_diffs = []
        for index in indices_oldest_first:
            target_hash = all_initial_commits[index]
            diff = get_commit_diff(target_hash)
            if diff:
                commits_with_diffs.append((index, target_hash, diff))
        
        if not commits_with_diffs:
            print("[X] No valid diffs found.")
            sys.exit(1)
        
        prompt_data = [(h, d) for (_, h, d) in commits_with_diffs]
        
        print(f"[*] Composing {len(commits_with_diffs)} messages in one request...")
        messages = generate_batch_messages(client, prompt_data)
        if messages is None:
            print("[X] API failure. Could not generate batch messages.")
            sys.exit(1)
        
        missing = [i for i in range(1, len(commits_with_diffs) + 1) if not messages.get(i)]
        if missing:
            print(f"[X] API returned incomplete messages. Missing: {missing}")
            sys.exit(1)
        
        print("[*] Applying messages (newest to oldest)...")
        crazy_total = len(commits_with_diffs)
        for step, (index, _, _) in enumerate(reversed(commits_with_diffs)):
            msg_num = crazy_total - step
            new_msg = messages[msg_num]
            
            current_history = get_all_commits()
            if index >= len(current_history):
                print(f"[X] Index {index} out of bounds. History corrupted?")
                sys.exit(1)
            
            current_hash = current_history[index]
            print(f"\n[{step+1}/{crazy_total}] Commit {current_hash[:7]}")
            print(f"    [+] Message: {new_msg}")
            
            if new_msg.startswith("-"):
                new_msg = " " + new_msg
            
            print(f"    [#] Reforging...", end="\r")
            proc = run(["cmsg", "-c", current_hash, "-m", new_msg])
            if proc.returncode != 0:
                print(f"\n    [X] Rewrite failed at {current_hash[:7]}.")
                print(f"    [i] Check 'git status'. You may need to 'git rebase --abort' or '--continue'.")
                sys.exit(1)
            
            print("    [V] Success.   ")
            sleep(0.1)
    else:
        for step, index in enumerate(target_indices):
            current_history = get_all_commits()
            if index >= len(current_history):
                print(f"[!] Index {index} is out of bounds (history shortened?). Skipping.")
                continue

            target_hash = current_history[index]
            print(f"\n[{step+1}/{total_ops}] Commit {target_hash[:7]}")

            diff = get_commit_diff(target_hash)
            if not diff:
                print("    [!] Empty diff, skipping.")
                continue

            print("    [*] Composing...", end="\r")
            new_msg = generate_conventional_message(client, diff)
            if new_msg is None:
                print(f"\n    [X] API failure. Stopping.")
                print(f"    [i] Progress saved. You may need to 'git rebase --abort' if a rebase is in progress.")
                sys.exit(1)
                
            print(f"    [+] Message: {new_msg}")

            if new_msg.startswith("-"):
                new_msg = " " + new_msg

            print(f"    [#] Reforging...", end="\r")
            proc = run(["cmsg", "-c", target_hash, "-m", new_msg])
            if proc.returncode != 0:
                print(f"\n    [X] Rewrite failed at {target_hash[:7]}.")
                print(f"    [i] Check 'git status'. You may need to 'git rebase --abort' or '--continue'.")
                sys.exit(1)

            print("    [V] Success.   ")
            sleep(0.1)

    print(f"\n[!] The saga is complete.")
    if args.yes:
        confirm = "yes"
    else:
        confirm = input("[?] Force push changes? (type 'yes'): ")
    
    if confirm == "yes":
        print("[>] Pushing...")
        res = run(["git", "push", "--force"])
        if res.returncode == 0:
            print("[V] Success.")
        else:
            print(f"[X] Failed:\n{res.stderr}")
    else:
        print("[i] Skipped push.")

if __name__ == "__main__":
    main()
