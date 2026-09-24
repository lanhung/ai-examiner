---
id: en_git_branching
domain: Software engineering
language: en
title: Git Branching and Merging
---
A Git branch is a lightweight movable pointer to a commit. Creating a branch does not copy files; it only creates a new reference. When you commit on a branch, the branch pointer moves forward to the new commit, while other branches stay where they were.

There are two common ways to integrate work. A merge creates a new merge commit that has two parents, preserving the exact history of both branches. If the target branch has not moved since the feature branch was created, Git can perform a fast-forward merge, which simply moves the pointer forward and creates no merge commit. A rebase instead replays the feature commits on top of the target branch, producing a linear history, but it rewrites commit identifiers.

Because rebase rewrites history, a widely followed rule is not to rebase commits that have already been pushed to a shared branch that other people are using. Doing so forces collaborators to reconcile diverged histories and can cause lost work.

A merge conflict happens when both branches changed the same lines of the same file, or one branch deleted a file that the other modified. Git cannot decide automatically; the developer must edit the file, choose the correct content, mark it resolved with git add, and complete the merge. Running the test suite after resolving a conflict is important, because a conflict-free merge can still produce code that does not work when two independent changes interact.
