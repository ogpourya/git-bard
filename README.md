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

# Rewrite the last commit using range syntax
git-bard HEAD~1..

# Rewrite the last 5 commits
git-bard HEAD~5..HEAD

# Rewrite everything on your branch that isn't on main
git-bard origin/main..HEAD
```

## Safety

This tool performs a destructive action (`git filter-branch` / rebase logic via `cmsg`).
