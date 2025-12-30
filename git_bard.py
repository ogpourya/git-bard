import subprocess
import os
import sys
import argparse
import shutil
from time import sleep

# --- CONFIGURATION ---
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_API_MODEL") or "gemini-3-flash-preview"
MAX_DIFF_CHARS = 50000

def run(cmd, **kwargs):
    """Run a command and return CompletedProcess. Avoid shell=True when possible."""
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, errors="replace", **kwargs)

def is_git_repo():
    """Return True if current dir is inside a git repo."""
    return run(["git", "rev-parse", "--git-dir"]).returncode == 0

def is_working_tree_clean():
    """Return True if no staged or unstaged changes exist."""
    res = run(["git", "status", "--porcelain"])
    if res.returncode != 0:
        # treat errors as not clean so caller can choose to abort
        return False
    return res.stdout.strip() == ""

def get_git_output(command):
    """Runs a git command (list form or string) and returns lines list, empty list on error."""
    res = run(command)
    if res.returncode != 0:
        # print small warning for visibility but do not explode
        err = res.stderr.strip()
        if err:
            print(f"⚠️  Git warning/error: {err}")
        return []
    out = res.stdout.strip()
    return out.splitlines() if out else []

def get_all_commits():
    """List all commits oldest first."""
    return [h for h in get_git_output(["git", "log", "--reverse", "--pretty=format:%H"]) if h]

def get_commits_in_range(range_spec):
    """List commits in the given range (oldest first)."""
    return [h for h in get_git_output(["git", "log", "--reverse", "--pretty=format:%H", range_spec]) if h]

def get_commit_diff(commit_hash):
    """Return a bounded amount of git show output for the commit."""
    res = run(["git", "show", commit_hash])
    if res.returncode != 0:
        print(f"⚠️  Could not get diff for {commit_hash[:7]}")
        return ""
    return res.stdout[:MAX_DIFF_CHARS]

def generate_conventional_message(client, diff_content, retries=3):
    """Ask Gemini for a conventional commit message. Caller provides a ready client."""
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
                if text:
                    return text
            print(f"   ⚠️ Empty response (attempt {attempt+1}/{retries})")
        except Exception as e:
            print(f"   ⚠️ API Error: {e} (attempt {attempt+1}/{retries})")
        
        if attempt < retries - 1:
            sleep(2 ** attempt)  # exponential backoff
    
    return None

def check_cmsg_installed():
    if shutil.which("cmsg") is None:
        print("❌ Error: 'cmsg' tool not found.")
        print("   Please install it: https://github.com/ogpourya/cmsg")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Rewrite git history with AI-generated conventional commit messages.")
    parser.add_argument("commit_range", nargs="?", help="Git commit range (e.g., HEAD~5..HEAD, origin/main..HEAD). Defaults to ALL commits.")
    args = parser.parse_args()

    # Fast preflight checks that should exit quickly
    if not is_git_repo():
        print("🛑 Not a git repository. Aborting.")
        sys.exit(1)

    if not is_working_tree_clean():
        print("🛑 Working tree is not clean. Stash or commit changes.")
        sys.exit(1)

    check_cmsg_installed()

    # Delay importing the heavy genai until we have validated the environment
    try:
        from google import genai
    except Exception as e:
        print(f"🛑 Failed to import Gemini client library: {e}")
        print("   Make sure the library is installed and importable.")
        sys.exit(1)

    if not API_KEY:
        print("🛑 Please set the GEMINI_API_KEY environment variable.")
        sys.exit(1)

    client = genai.Client(api_key=API_KEY)

    print("🎻 Git Bard: Tuning instruments...")
    if os.getenv("GEMINI_API_MODEL"):
        print(f"ℹ️  Using configured model: {MODEL_NAME}")
    else:
        print(f"ℹ️  Using default model: {MODEL_NAME} (Set GEMINI_API_MODEL to override)")

    # Determine targets
    all_initial_commits = get_all_commits()
    if not all_initial_commits:
        print("❌ No commits found in repository.")
        sys.exit(1)

    if args.commit_range:
        if args.commit_range.lower() == "head":
            print("📜 'head' detected. Targeting only the latest commit.")
            target_indices = [len(all_initial_commits) - 1]
        else:
            print(f"📜 Analyzing range: {args.commit_range}")
            target_hashes = get_commits_in_range(args.commit_range)
            if not target_hashes:
                print("❌ No commits found in that range.")
                sys.exit(1)
            # Map hashes to indices in the baseline history
            target_indices = []
            for h in target_hashes:
                try:
                    idx = all_initial_commits.index(h)
                    target_indices.append(idx)
                except ValueError:
                    # hash not in baseline history, will handle later
                    pass
            target_indices.sort()
            if not target_indices:
                print("❌ Could not map range hashes to current history indices.")
                sys.exit(1)
    else:
        print("📜 No range specified. Selecting ALL commits.")
        target_indices = list(range(len(all_initial_commits)))

    total_ops = len(target_indices)
    print(f"🚀 Ready to rewrite {total_ops} commits.\n")

    # We process from newest to oldest. 
    # cmsg uses rebase. Rewriting an old commit changes hashes of all descendant commits.
    # By going NEWEST to OLDEST, we modify a leaf, and its parents/ancestors 
    # remain at the same index in the history (though their children's hashes changed).
    target_indices.reverse()

    start_range = args.commit_range or "ALL"
    for step, index in enumerate(target_indices):
        current_history = get_all_commits()
        if index >= len(current_history):
            print(f"⚠️ Index {index} is out of bounds (history shortened?). Skipping.")
            continue

        target_hash = current_history[index]
        print(f"[{step+1}/{total_ops}] Processing history index {index} (hash {target_hash[:7]})...")

        diff = get_commit_diff(target_hash)
        if not diff:
            print("   ⚠️ Empty diff, skipping.")
            continue

        print("   ✨ Composing ballad...")
        new_msg = generate_conventional_message(client, diff)
        if new_msg is None:
            print(f"\n❌ API failed after multiple retries.")
            print(f"📊 Status Report:")
            print(f"   - Starting Range: {start_range}")
            print(f"   - Total Commits in Range: {total_ops}")
            print(f"   - Successfully Processed: {step}")
            print(f"   - Failed at Index: {index} (hash {target_hash[:7]})")
            print(f"   - Remaining: {total_ops - step}")
            sys.exit(1)
            
        print(f"   📝 New Message: {new_msg}")

        # Protect against messages starting with hyphen being interpreted as flags
        if new_msg.startswith("-"):
            new_msg = " " + new_msg

        print(f"   🔨 Reforging {target_hash[:7]}...")
        proc = run(["cmsg", "-c", target_hash, "-m", new_msg])
        if proc.returncode != 0:
            print(f"❌ cmsg failed at index {index}. Stopping to prevent corruption.")
            print("   You may need to run 'git rebase --abort' or fix conflicts manually.")
            sys.exit(1)

        print("   ✅ Success.\n")
        sleep(0.25)

    print("\n🎉 The saga is complete. Force push when ready!")

if __name__ == "__main__":
    main()
