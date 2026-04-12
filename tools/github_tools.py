from __future__ import annotations

import base64
import re
from typing import Any, Dict, List

import requests

from config import Settings
from tools.retry import retry


class GitHubTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = f"https://api.github.com/repos/{settings.github_repo_full}"
        self.headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @retry()
    def get_base_sha(self, branch: str = "main") -> str:
        ref_resp = requests.get(
            f"{self.base_url}/git/refs/heads/{branch}",
            headers=self.headers,
            timeout=30,
        )
        if ref_resp.ok:
            return ref_resp.json()["object"]["sha"]

        # Some repos return 409/404 on git/ref routes (empty/default branch mismatch).
        # Fall back to repository metadata + branches API for a stable commit SHA lookup.
        if ref_resp.status_code in (404, 409):
            repo_resp = requests.get(self.base_url, headers=self.headers, timeout=30)
            repo_resp.raise_for_status()
            default_branch = repo_resp.json().get("default_branch") or branch
            branch_resp = requests.get(
                f"{self.base_url}/branches/{default_branch}",
                headers=self.headers,
                timeout=30,
            )
            branch_resp.raise_for_status()
            return branch_resp.json()["commit"]["sha"]

        ref_resp.raise_for_status()
        return ref_resp.json()["object"]["sha"]

    @retry()
    def create_branch(self, branch_name: str, base_sha: str) -> None:
        resp = requests.post(
            f"{self.base_url}/git/refs",
            headers=self.headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
            timeout=30,
        )
        resp.raise_for_status()

    @retry()
    def commit_file(
        self, path: str, content: str, message: str, branch_name: str, sha: str | None = None
    ) -> Dict[str, Any]:
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        body = {
            "message": message,
            "content": encoded,
            "branch": branch_name,
            "committer": {"name": "EngineerAgent", "email": "agent@launchmind.ai"},
            "author": {"name": "EngineerAgent", "email": "agent@launchmind.ai"},
        }
        if sha:
            body["sha"] = sha
        resp = requests.put(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @retry()
    def get_file_sha(self, path: str, branch_name: str) -> str | None:
        resp = requests.get(
            f"{self.base_url}/contents/{path}",
            headers=self.headers,
            params={"ref": branch_name},
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()["sha"]

    @retry()
    def create_issue(self, title: str, body: str) -> str:
        resp = requests.post(
            f"{self.base_url}/issues",
            headers=self.headers,
            json={"title": title, "body": body},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["html_url"]

    @retry()
    def open_pull_request(self, title: str, body: str, branch_name: str, base: str = "main") -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/pulls",
            headers=self.headers,
            json={"title": title, "body": body, "head": branch_name, "base": base},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @retry()
    def get_pr_files(self, pull_number: int) -> List[Dict[str, Any]]:
        resp = requests.get(
            f"{self.base_url}/pulls/{pull_number}/files",
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @retry()
    def post_pr_review(self, pull_number: int, comments: list[str], event: str = "COMMENT") -> str:
        pr_resp = requests.get(
            f"{self.base_url}/pulls/{pull_number}",
            headers=self.headers,
            timeout=30,
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()
        commit_id = pr_data["head"]["sha"]
        files = self.get_pr_files(pull_number)
        inline_comments = self._build_inline_comments(files, comments)

        review_body = {
            "commit_id": commit_id,
            "body": "LaunchMind QA Review",
            "event": event,
            "comments": inline_comments,
        }
        resp = requests.post(
            f"{self.base_url}/pulls/{pull_number}/reviews",
            headers=self.headers,
            json=review_body,
            timeout=30,
        )
        # Fallback: if inline coordinates fail validation, submit a non-inline review
        # so the QA phase can still complete gracefully.
        if resp.status_code == 422:
            fallback_body = {
                "commit_id": commit_id,
                "body": "LaunchMind QA Review\n\n" + "\n".join([f"- {c}" for c in comments[:2]]),
                "event": event,
            }
            fallback = requests.post(
                f"{self.base_url}/pulls/{pull_number}/reviews",
                headers=self.headers,
                json=fallback_body,
                timeout=30,
            )
            fallback.raise_for_status()
            return fallback.json()["html_url"]
        resp.raise_for_status()
        return resp.json()["html_url"]

    def _build_inline_comments(self, files: List[Dict[str, Any]], comments: List[str]) -> List[Dict[str, Any]]:
        lines_by_file: List[tuple[str, List[int]]] = []
        for f in files:
            filename = f.get("filename")
            patch = f.get("patch") or ""
            if not filename or not patch:
                continue
            changed_lines = self._extract_added_lines(patch)
            if changed_lines:
                lines_by_file.append((filename, changed_lines))

        if not lines_by_file:
            fallback_path = files[0]["filename"] if files else "index.html"
            return [
                {"path": fallback_path, "line": 1, "side": "RIGHT", "body": comments[0] if comments else "QA note 1"},
                {"path": fallback_path, "line": 1, "side": "RIGHT", "body": comments[1] if len(comments) > 1 else "QA note 2"},
            ]

        inline_comments: List[Dict[str, Any]] = []
        comment_texts = comments[:2] if comments else ["QA note 1", "QA note 2"]
        while len(comment_texts) < 2:
            comment_texts.append(f"QA note {len(comment_texts) + 1}")

        for idx, comment in enumerate(comment_texts):
            file_idx = idx % len(lines_by_file)
            path, lines = lines_by_file[file_idx]
            line_num = lines[min(idx, len(lines) - 1)]
            inline_comments.append(
                {
                    "path": path,
                    "line": line_num,
                    "side": "RIGHT",
                    "body": comment,
                }
            )
        return inline_comments

    @staticmethod
    def _extract_added_lines(patch: str) -> List[int]:
        # Parse unified diff hunks and return line numbers on the new/right side
        # where additions occurred, since GitHub review comments must target diff lines.
        added: List[int] = []
        new_line = None
        for raw in patch.splitlines():
            if raw.startswith("@@"):
                match = re.search(r"\+(\d+)", raw)
                if match:
                    new_line = int(match.group(1))
                continue
            if new_line is None:
                continue
            if raw.startswith("+") and not raw.startswith("+++"):
                added.append(new_line)
                new_line += 1
            elif raw.startswith("-") and not raw.startswith("---"):
                # Deletion does not advance new-side line counter.
                continue
            else:
                new_line += 1
        return added
