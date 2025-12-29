# git-bard

**git-bard** turns your messy git history into an epic saga. It iterates through your commits (or a specific range), analyzes the changes using Google's Gemini 3 Flash, and rewrites the commit messages using the Conventional Commits standard.

> "From 0 to Hero!"

## Prerequisites

1.  **`cmsg`**: This tool relies on `cmsg` to perform the actual git surgery.
    * [cmsg on GitHub](https://github.com/ogpourya/cmsg "null") (ensure `cmsg` is in your PATH).
2.  **Gemini API Key**: Get one from Google AI Studio.


## Installation with `uv`

```
uv tool install https://github.com/ogpourya/git-bard.git
```

## Usage

Set your API key:

```
export GEMINI_API_KEY="your_key_here"
```

Optionally, set a specific model (defaults to `gemini-3-flash-preview`):

```
export GEMINI_API_MODEL="gemini-1.5-pro-latest"
```

### 1. The "0 to Hero" Mode (Default)

Rewrite **every** commit in the repository history, starting from the first commit.

```
git-bard
```

### 2. Range Mode

Rewrite only a specific range of commits. Useful for cleaning up a feature branch before merging.

```
# Rewrite ONLY the last commit (equivalent to git commit --amend)
git-bard head

# Rewrite the last 5 commits
git-bard HEAD~5..HEAD

# Rewrite everything on your branch that isn't on main
git-bard origin/main..HEAD
```

## Safety

This tool rewrites git history using `cmsg` (which uses rebase logic).

*   **`git-bard head`**: Safe to use on your latest local commit (equivalent to `git commit --amend`).
*   **Ranges/All**: Rewriting past commits changes their hashes. Avoid using this on commits already pushed to a shared repository unless you intend to force-push and coordinate with your team.
