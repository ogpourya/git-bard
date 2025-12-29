import subprocess
import os
import sys
import argparse
from google import genai
from time import sleep

# --- CONFIGURATION ---
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3-flash-preview"

def get_git_output(command):
    """Runs a git command and returns the output as a list of strings."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        # Don't exit immediately on git errors, let the caller handle empty lists if needed
        # but print error for visibility
        print(f"⚠️  Git warning/error: {result.stderr.strip()}")
        return []
    return result.stdout.strip().split('\n')

def get_all_commits():
    """Returns a list of all commit hashes in the current branch (Oldest -> Newest)."""
    hashes = get_git_output("git log --reverse --pretty=format:'%H'")
    return [h for h in hashes if h]

def get_commits_in_range(range_spec):
    """Returns a list of commit hashes within the specified range."""
    # If no range, git log returns everything, but we handle that in main
    cmd = f"git log --reverse --pretty=format:'%H' {range_spec}"
    hashes = get_git_output(cmd)
    return [h for h in hashes if h]

def get_commit_diff(commit_hash):
    """Gets the diff and metadata for a specific commit."""
    result = subprocess.run(f"git show {commit_hash}", shell=True, capture_output=True, text=True)
    return result.stdout[:50000]

def generate_conventional_message(client, diff_content):
    """Sends the diff to Gemini to get a conventional commit message."""
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

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        if response.text:
            return response.text.strip().replace('"', '').replace("`", "")
        return "chore: updated code (empty response)"
    except Exception as e:
        print(f"⚠️ API Error: {e}")
        return "chore: updated code (api error fallback)"

def check_dependencies():
    """Checks if cmsg is installed."""
    if subprocess.run("which cmsg", shell=True, capture_output=True).returncode != 0:
        print("❌ Error: 'cmsg' tool not found.")
        print("   Please install it: https://github.com/ogpourya/cmsg")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Rewrite git history with AI-generated conventional commit messages.")
    parser.add_argument("commit_range", nargs="?", help="Git commit range (e.g., HEAD~5..HEAD, origin/main..HEAD). Defaults to ALL commits (0 to hero).")
    args = parser.parse_args()

    if not API_KEY:
        print("🛑 Please set the GEMINI_API_KEY environment variable.")
        sys.exit(1)

    client = genai.Client(api_key=API_KEY)
    
    print("🎻 Git Bard: Tuning instruments...")
    check_dependencies()

    # 1. Determine targets
    # We need to map the requested range to INDICES. 
    # Why? Because rewriting commit #5 changes the hash of commit #6. 
    # Validating targets by Hash is impossible after the rewrite starts.
    # Validating by Index (relative to root) is stable for linear rewrites.
    
    all_initial_commits = get_all_commits()
    
    if args.commit_range:
        if args.commit_range.lower() == "head":
            print("📜 'head' detected. Targeting only the latest commit.")
            if not all_initial_commits:
                print("❌ No commits found in repository.")
                sys.exit(1)
            target_hashes = [all_initial_commits[-1]]
        else:
            print(f"📜 Analyzing range: {args.commit_range}")
            target_hashes = get_commits_in_range(args.commit_range)

        if not target_hashes:
            print("❌ No commits found in that range.")
            sys.exit(1)
            
        # Map hashes to indices
        target_indices = []
        for h in target_hashes:
            if h in all_initial_commits:
                target_indices.append(all_initial_commits.index(h))
        
        target_indices.sort()
        if not target_indices:
            print("❌ Could not map range hashes to current history indices.")
            sys.exit(1)
    else:
        print("📜 No range specified. Selecting ALL commits (From 0 to Hero mode).")
        target_indices = list(range(len(all_initial_commits)))

    total_ops = len(target_indices)
    print(f"🚀 Ready to rewrite {total_ops} commits.\n")

    # 2. Iterate through the calculated indices
    for step, index in enumerate(target_indices):
        # Always fetch fresh history because hashes changed in previous iteration
        current_history = get_all_commits()
        
        if index >= len(current_history):
            print(f"⚠️ Index {index} is out of bounds (history shortened?). Skipping.")
            continue
            
        target_hash = current_history[index]
        
        print(f"[{step+1}/{total_ops}] Processing history index {index} (Current Hash: {target_hash[:7]})...")

        # Get diff & Generate
        diff = get_commit_diff(target_hash)
        print("   ✨ Composing ballad...")
        new_msg = generate_conventional_message(client, diff)
        print(f"   📝 New Message: {new_msg}")

        # Rewrite
        print(f"   🔨 Reforging {target_hash[:7]}...")
        proc = subprocess.run(["cmsg", "-c", target_hash, "-m", new_msg], text=True)
        
        if proc.returncode != 0:
            print(f"❌ cmsg failed at index {index}. Stopping to prevent corruption.")
            print("   You may need to run 'git rebase --abort' or fix conflicts manually.")
            sys.exit(1)
        
        print("   ✅ Success.\n")
        sleep(0.5)

    print("\n🎉 The saga is complete. Force push when ready!")

if __name__ == "__main__":
    main()
